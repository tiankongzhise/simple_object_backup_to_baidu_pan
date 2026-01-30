# 产品需求文档 (PRD): 智能云备份归档系统 (Smart Cloud Archiver)

| 项目 | 内容 |
| --- | --- |
| **文档版本** | v3.0 (Enhanced) |
| **状态** | **已锁定 / 待开发** |
| **最后更新** | 2026-01-30 |
| **目标平台** | Windows 10/11 |

---

## 1. 项目概述与目标

设计一款运行在 Windows 环境下的自动化备份工具，旨在将本地分散的文件/文件夹加密归档至百度网盘，并释放本地空间。

**核心价值：**

1. **自动化减负：** 自动打包上传，释放本地磁盘。
2. **数据安全：** 本地加密，云端存储，防止隐私泄露。
3. **鲁棒性：** 具备断点续传、异常崩溃恢复、多机去重能力。
4. **内容合规：** 自动识别敏感内容（色情）并标记。

---

## 2. 技术栈约束 (Technical Stack)

* **语言:** Python 3.10+
* **GUI:** PyQt6 / PySide6 (支持 Dark Mode, 响应式布局)
* **数据库:** MySQL 8.0
* **ORM:** SQLAlchemy 2.0 (Async Style) + `aiomysql` (或 `pymysql` + ThreadPool)
* **云存储:** 百度网盘 OpenAPI (自定义 SDK 封装)
* **文件操作:** `send2trash` (回收站支持), `7zip` (命令行调用或 `py7zr`)
* **并发模型:** `asyncio` 事件循环 + `ProcessPoolExecutor` (计算密集型) + `ThreadPoolExecutor` (IO密集型)

---

## 3. 系统架构设计

系统采用 **生产者-消费者 (Producer-Consumer)** 模型，辅以 **Session 机制** 保证状态一致性。

### 3.1 核心模块

1. **Session Manager (会话/恢复管理器):** 负责生成运行时 ID，启动时清理上次崩溃残留。
2. **Scanner & Classifier (扫描分类器):** 遍历目录，推断属性，识别敏感词。
3. **Global Deduplicator (全局去重器):** 基于 Hash 和 DB 校验文件唯一性。
4. **Resource Manager (资源管控):** 基于 `asyncio.Semaphore` 的磁盘配额锁。
5. **Task Scheduler (任务调度器):** 负责任务排队、资源调度、暂停/取消控制。
6. **Processor (执行引擎):**
   - *Hasher:* 极速哈希计算（含分片MD5计算）。
   - *Packer:* AES-256 加密压缩。
   - *Verifier:* 解压回验。
   - *Uploader:* 百度网盘分片流式上传（含全部分片MD5列表上传）。

7. **Safety Cleaner (安全清理器):** 区分"物理删除"与"回收站删除"。

---

## 4. 任务状态机设计 (新增)

### 4.1 完整状态流转图

```
                    ┌─────────────────────────────────────────────────────────┐
                    │                      用户操作                           │
                    └─────────────────────────────────────────────────────────┘
                                      │      │      │      │
                                      ▼      ▼      ▼      ▼
┌──────────┐    submit     ┌──────────┐    ┌──────────┐    ┌──────────┐
│   NEW    │ ──────────▶   │ QUEUED   │    │ PAUSED   │ ◀─── pause │
│  (新建)  │               │(排队中)  │    │ (暂停)   │      │
└──────────┘               └────┬─────┘    └────┬─────┘    ┌───────┘
                                │               │          │
                                │ scheduler     │          │ resume
                                │ dispatch      │          ▼
                                ▼               │    ┌──────────┐
                        ┌───────────────┐       │    │ CANCELLED│
                        │   PENDING     │       │    │ (已取消) │
                        │   (待处理)    │       │    └────┬────┘
                        └───────┬───────┘       │         │
                                │               │         │
                                │ start         │         │
                                ▼               │         │
                        ┌───────────────┐       │         │
                        │   HASHING     │       │         │
                        │   (计算哈希)  │       │         │
                        └───────┬───────┘       │         │
                                │               │         │ cancel
                                │ complete      │         │
                                ▼               │         │
                        ┌───────────────┐       │         │
                        │   PACKING     │       │         │
                        │   (打包中)    │       │         │
                        └───────┬───────┘       │         │
                                │               │         │
                                │ complete      │         │
                                ▼               │         │
                        ┌───────────────┐       │         │
                        │  VERIFYING    │       │         │
                        │   (验证中)    │       │         │
                        └───────┬───────┘       │         │
                                │               │         │
                                │ complete      │         │
                                ▼               │         │
                        ┌───────────────┐       │         │
                        │  UPLOADING    │       │         │
                        │   (上传中)    │       │         │
                        └───────┬───────┘       │         │
                                │               │         │
          ┌─────────────────────┼────────────────┘         │
          │                     │                          │
          │ complete            │ error                   │ cancel
          ▼                     ▼                          │
    ┌───────────────┐    ┌───────────────┐                │
    │   COMPLETED   │    │    FAILED     │ ◀──────────────┘
    │   (已完成)    │    │   (失败)      │
    └───────────────┘    └───────┬───────┘
                                │
                                │ retry (用户手动重试)
                                ▼
                          ┌──────────┐
                          │  PENDING │
                          │  (待处理)│
                          └──────────┘
```

### 4.2 状态定义详解

| 状态 | 枚举值 | 说明 | 允许的操作 |
|------|--------|------|-----------|
| NEW | `new` | 任务刚创建，尚未进入队列 | submit, cancel |
| QUEUED | `queued` | 已提交，等待调度器分配资源 | pause, cancel |
| PENDING | `pending` | 调度器已分配资源，等待处理 | pause, cancel |
| HASHING | `hashing` | 正在计算文件哈希 | cancel |
| PACKING | `packing` | 正在加密打包 | cancel |
| VERIFYING | `verifying` | 正在验证打包完整性 | cancel |
| UPLOADING | `uploading` | 正在上传到云端 | cancel |
| PAUSED | `paused` | 用户主动暂停 | resume, cancel |
| CANCELLED | `cancelled` | 用户主动取消 | retry (重新提交) |
| COMPLETED | `completed` | 全部流程完成 | - |
| FAILED | `failed` | 任务执行失败 | retry (手动重试), cancel |

### 4.3 状态设计原则

1. **NEW → QUEUED**: 用户点击"开始备份"后立即转换
2. **QUEUED → PENDING**: 调度器分配到执行槽位
3. **PAUSED状态特殊性**: 可从 PENDING/HASHING/PACKING/VERIFYING/UPLOADING 任意阶段进入
4. **FAILED/CANCELLED**: 提供手动重试入口，用户可选择重新执行

---

## 5. 任务操作接口设计

### 5.1 操作权限矩阵

| 操作 | 前置条件 | 生效状态 | 目标状态 |
|------|----------|----------|----------|
| submit | NEW | NEW | QUEUED |
| pause | QUEUED/PENDING/HASHING/PACKING/VERIFYING/UPLOADING | any active | PAUSED |
| resume | PAUSED | PAUSED | QUEUED (重新排队) |
| cancel | NEW/QUEUED/PENDING/HASHING/PACKING/VERIFYING/UPLOADING/PAUSED/FAILED | any | CANCELLED |
| retry | FAILED/CANCELLED | FAILED/CANCELLED | QUEUED (新session) |

### 5.2 任务操作事件流

```
用户点击"重试" → 验证权限 → 创建新session_id → 状态: FAILED → QUEUED → 开始执行
用户点击"取消" → 验证权限 → 发送取消信号 → 等待当前阶段完成 → 状态: CANCELLED → 清理资源
用户点击"暂停" → 验证权限 → 记录暂停点 → 保存上下文 → 状态: PAUSED
用户点击"继续" → 验证权限 → 恢复上下文 → 状态: QUEUED
```

---

## 6. 百度网盘分片上传增强设计

### 6.1 问题背景

百度网盘分片上传API要求：
- 支持断点续传（需要upload_id）
- 支持秒传（需要文件MD5）
- **支持预查询分片MD5列表以优化上传体验**

### 6.2 分片MD5计算方案

**设计原则：**
1. 分片大小固定为 4MB（兼顾计算速度和百度API兼容性）
2. 每个分片独立计算MD5
3. 所有分片MD5组成列表，作为上传请求的一部分

**计算流程：**
```
┌─────────────────────────────────────────────────────────────────┐
│                      分片MD5计算流程                             │
├─────────────────────────────────────────────────────────────────┤
│  1. 读取加密后的归档文件                                          │
│  2. 按4MB分片切分（最后一个分片可能不足4MB）                       │
│  3. 对每个分片计算MD5:                                            │
│       chunk_1_md5 = md5(file[0:4MB])                             │
│       chunk_2_md5 = md5(file[4MB:8MB])                           │
│       ...                                                         │
│  4. 拼接所有分片MD5为字符串: "md5_1,md5_2,md5_3,..."              │
│  5. 将MD5列表存入DB字段 `block_list_md5`                          │
└─────────────────────────────────────────────────────────────────┘
```

### 6.3 数据库字段扩展

```python
class BackupRecord(Base):
    # ... 现有字段 ...

    # === 6.1 分片MD5列表 (新增) ===
    # 格式: "md5_1,md5_2,md5_3,..." (逗号分隔的十六进制字符串)
    block_list_md5: Mapped[str] = mapped_column(String(2048), nullable=True)

    # === 6.2 分片信息 (新增) ===
    block_size: Mapped[int] = mapped_column(BigInteger, default=4*1024*1024)  # 默认4MB
    total_blocks: Mapped[int] = mapped_column(default=0)  #总分片数
    uploaded_blocks: Mapped[int] = mapped_column(default=0)  #已上传分片数

    # === 6.3 任务元数据 (新增) ===
    retry_count: Mapped[int] = mapped_column(default=0)  # 重试次数
    max_retries: Mapped[int] = mapped_column(default=3)  # 最大重试次数
    paused_at_stage: Mapped[str] = mapped_column(String(32), nullable=True)  # 暂停时的阶段
    cancel_reason: Mapped[str] = mapped_column(String(512), nullable=True)  # 取消原因
```

### 6.4 上传API调用流程

```
┌─────────────────────────────────────────────────────────────────┐
│                    百度网盘上传完整流程                           │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Step 1: 预检查                                                 │
│  ├─ 检查文件是否已存在 (file_md5)                                │
│  ├─ 检查upload_id是否存在（断点续传）                             │
│  └─ 检查block_list_md5是否存在                                   │
│                                                                 │
│  Step 2: 计算分片MD5列表                                         │
│  ├─ 读取加密文件                                                 │
│  ├─ 按4MB分片切分                                                │
│  ├─ 计算每个分片MD5                                              │
│  └─ 拼接为字符串: "md51,md52,md3..."                             │
│                                                                 │
│  Step 3: 发起上传请求                                            │
│  ├─ 调用 create_super_file2 (预上传)                             │
│  ├─ 传入参数:                                                    │
│  │   - path: 云端路径                                            │
│  │   - size: 文件大小                                            │
│  │   - isexist: 1                                               │
│  │   - block_list: [md5_1, md5_2, ...]  ← 关键！                │
│  │   - upload_id: (可选，用于断点续传)                            │
│  └─ 获取返回值:                                                  │
│      - upload_id: 用于后续分片上传                                │
│      - block_seq: 需要上传的分片序号列表                          │
│                                                                 │
│  Step 4: 分片上传                                                │
│  ├─ 遍历需要上传的分片                                           │
│  ├─ 读取分片数据 (流式读取，不一次性加载内存)                      │
│  ├─ 调用 upload_part 接口                                        │
│  └─ 更新 uploaded_blocks 计数                                    │
│                                                                 │
│  Step 5: 完成上传                                                │
│  ├─ 调用 finish_super_file2                                      │
│  ├─ 传入参数:                                                    │
│  │   - path: 云端路径                                            │
│  │   - upload_id: 从Step3获取                                     │
│  │   - block_list: MD5列表 (再次确认)                             │
│  └─ 获取返回的 file_id                                            │
│                                                                 │
│  Step 6: 更新数据库                                              │
│  ├─ 更新 status = COMPLETED                                      │
│  ├─ 更新 cloud_path                                              │
│  └─ 清理临时文件                                                  │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 6.5 百度API参数映射

| 百度API参数 | 本地字段 | 说明 |
|-------------|----------|------|
| path | `cloud_path` | 云端存储路径 |
| size | `total_size` | 文件总大小 |
| block_list | `block_list_md5` | 分片MD5列表 |
| upload_id | `upload_id` | 断点续传ID |
| file_name | `file_name` | 文件名 |

---

## 7. 任务调度器设计

### 7.1 调度器核心职责

1. **资源管理**: 控制并发任务数、磁盘配额
2. **状态维护**: 维护任务队列、暂停/恢复状态
3. **负载均衡**: 根据任务优先级分配资源
4. **事件处理**: 处理用户操作（暂停/取消/重试）

### 7.2 调度器数据结构

```python
class TaskScheduler:
    def __init__(self, max_concurrent: int = 3, max_disk_usage: int = 10*1024**3):
        self.max_concurrent = max_concurrent
        self.max_disk_usage = max_disk_usage
        self.active_tasks: Set[int] = set()  # 正在执行的任务ID
        self.queued_tasks: Deque[int] = deque()  # 排队中的任务ID
        self.paused_tasks: Set[int] = set()  # 暂停的任务ID
        self.semaphore = asyncio.Semaphore(max_concurrent)
        self.disk_quota = DiskQuotaManager(max_disk_usage)

    async def submit(self, task_id: int):
        """提交任务到队列"""
        await self.queued_tasks.append(task_id)
        await self._update_status(task_id, TaskStatus.QUEUED)
        await self._schedule_next()

    async def pause(self, task_id: int):
        """暂停任务"""
        if task_id in self.active_tasks:
            await self._send_cancel_signal(task_id)
        elif task_id in self.queued_tasks:
            self.queued_tasks.remove(task_id)
        self.paused_tasks.add(task_id)
        await self._update_status(task_id, TaskStatus.PAUSED)

    async def resume(self, task_id: int):
        """恢复任务"""
        if task_id in self.paused_tasks:
            self.paused_tasks.remove(task_id)
            await self.submit(task_id)

    async def cancel(self, task_id: int):
        """取消任务"""
        if task_id in self.active_tasks:
            await self._send_cancel_signal(task_id)
        elif task_id in self.queued_tasks:
            self.queued_tasks.remove(task_id)
        elif task_id in self.paused_tasks:
            self.paused_tasks.remove(task_id)
        await self._update_status(task_id, TaskStatus.CANCELLED)
        await self._cleanup_task(task_id)

    async def retry(self, task_id: int):
        """重试任务"""
        record = await self._get_record(task_id)
        if record.status in (TaskStatus.FAILED, TaskStatus.CANCELLED):
            record.retry_count += 1
            record.session_id = generate_new_session_id()
            await self._update_status(task_id, TaskStatus.QUEUED)
            await self.queued_tasks.append(task_id)
            await self._schedule_next()
```

---

## 8. 数据库设计 (Schema v3.0)

```python
import enum
from datetime import datetime
from sqlalchemy import String, BigInteger, Boolean, Enum, ForeignKey, UniqueConstraint, Index, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

class Base(DeclarativeBase):
    pass

class TaskStatus(enum.Enum):
    NEW = "new"
    QUEUED = "queued"
    PENDING = "pending"
    HASHING = "hashing"
    PACKING = "packing"
    VERIFYING = "verifying"
    UPLOADING = "uploading"
    PAUSED = "paused"
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    FAILED = "failed"

class FileCategory(enum.Enum):
    VIDEO = "video"
    IMAGE = "image"
    INSTALLER = "installer"
    ARCHIVE = "archive"
    MIXED = "mixed"

class BackupRecord(Base):
    __tablename__ = "backup_records"

    id: Mapped[int] = mapped_column(primary_key=True)

    # --- 1. 身份与定位 ---
    device_id: Mapped[str] = mapped_column(String(64), nullable=False)
    source_path: Mapped[str] = mapped_column(String(512), nullable=False)
    file_name: Mapped[str] = mapped_column(String(255))

    # --- 2. 属性与分类 ---
    is_directory: Mapped[bool] = mapped_column(Boolean, default=False)
    total_size: Mapped[int] = mapped_column(BigInteger, default=0)
    category: Mapped[FileCategory] = mapped_column(Enum(FileCategory), default=FileCategory.MIXED)
    is_porn_sensitive: Mapped[bool] = mapped_column(Boolean, default=False)

    # --- 3. 核心指纹 (全局去重) ---
    file_hash: Mapped[str] = mapped_column(String(64), index=True, nullable=True)
    is_duplicate: Mapped[bool] = mapped_column(Boolean, default=False)
    original_record_id: Mapped[int] = mapped_column(ForeignKey("backup_records.id"), nullable=True)

    # --- 4. 任务控制与恢复 ---
    session_id: Mapped[str] = mapped_column(String(36), index=True, nullable=True)
    status: Mapped[TaskStatus] = mapped_column(Enum(TaskStatus), default=TaskStatus.NEW)
    error_log: Mapped[str] = mapped_column(String(1024), nullable=True)

    # === 4.1 任务操作控制 (新增) ===
    retry_count: Mapped[int] = mapped_column(default=0)
    max_retries: Mapped[int] = mapped_column(default=3)
    paused_at_stage: Mapped[str] = mapped_column(String(32), nullable=True)
    cancel_reason: Mapped[str] = mapped_column(String(512), nullable=True)

    # --- 5. 临时资源 (用于清理) ---
    temp_archive_path: Mapped[str] = mapped_column(String(512), nullable=True)
    verify_extract_path: Mapped[str] = mapped_column(String(512), nullable=True)

    # --- 6. 云端信息 ---
    cloud_path: Mapped[str] = mapped_column(String(512), nullable=True)
    upload_id: Mapped[str] = mapped_column(String(128), nullable=True)

    # === 6.1 分片MD5列表 (新增) ===
    block_list_md5: Mapped[str] = mapped_column(Text, nullable=True)
    block_size: Mapped[int] = mapped_column(BigInteger, default=4*1024*1024)
    total_blocks: Mapped[int] = mapped_column(default=0)
    uploaded_blocks: Mapped[int] = mapped_column(default=0)

    created_at: Mapped[datetime] = mapped_column(default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(default=datetime.now, onupdate=datetime.now)

    __table_args__ = (
        UniqueConstraint('device_id', 'source_path', name='uix_device_src_path'),
        Index('idx_status_session', 'status', 'session_id'),
        Index('idx_status_retry', 'status', 'retry_count'),
    )
```

---

## 9. 异常处理规范

1. **网络异常:** `try-except` 包裹所有 SDK 调用。重试 3 次后失败，标记状态 `FAILED`，保留本地文件，不执行删除。
2. **磁盘空间不足:** 在申请磁盘配额时，如果系统总盘符剩余空间 < 5GB，强制暂停所有新任务，UI 弹窗报警。
3. **加密/解压错误:** 必须捕获 `BadZipFile` 等异常，视为严重错误，标记 `FAILED`。
4. **用户取消:** 捕获取消信号，清理已分配的临时资源，状态设为 `CANCELLED`。
5. **分片MD5计算失败:** 记录错误日志，状态设为 `FAILED`，允许用户重试。

---

## 10. UI 界面需求 (PyQt6)

### 10.1 主面板

**Dashboard:**
- 仪表盘显示：已备份大小 / 总释放空间
- 当前并发线程数 / 实时上传速度
- 队列统计：排队中/进行中/已完成/失败/暂停

**Task Grid (任务列表):**
- 列：文件名 | 大小 | 状态 | 进度条 | 类别 | 耗时 | 重试次数
- **状态列显示规则:**
  - NEW: "新建"
  - QUEUED: "排队中"
  - PENDING: "准备中"
  - HASHING/PACKING/VERIFYING/UPLOADING: 进度条 + 百分比
  - PAUSED: "已暂停" (蓝色)
  - CANCELLED: "已取消" (灰色)
  - COMPLETED: "已完成" (绿色)
  - FAILED: "失败" (红色) + 重试按钮

**操作按钮 (上下文敏感):**
- 新建任务: "添加任务"
- 选中排队/暂停任务: "暂停" / "取消"
- 选中失败任务: "重试" / "取消"
- 选中已暂停任务: "继续"

**高亮规则:**
- `is_porn_sensitive == True`: 该行文字变红或显示 "18+" 图标
- `is_duplicate == True`: 状态栏显示 "秒传完成"
- `retry_count > 0`: 显示重试次数图标

---

## 11. 开发实施计划

1. **Phase 1: Core & DB (天数: 2)**
   - 完成 SQLAlchemy 模型定义 (v3.0)
   - 实现 `SessionManager` 和崩溃恢复逻辑
   - 实现状态机基础框架

2. **Phase 2: Task Scheduler (天数: 2)**
   - 实现任务调度器 (排队/暂停/恢复/取消)
   - 实现重试机制
   - 实现磁盘配额管理

3. **Phase 3: Local Logic (天数: 3)**
   - 实现 `Scanner` (含敏感词、属性推断)
   - 实现 `Hasher` (mmap, 分片MD5计算)
   - 实现 `Packer` & `Verifier` (集成 7z, 磁盘配额 Semaphore)

4. **Phase 4: Cloud & Upload (天数: 3)**
   - 封装百度网盘 SDK (获取 Token, 刷新 Token)
   - 实现分片MD5列表计算
   - 实现 Generator 流式分片上传 (含block_list参数)

5. **Phase 5: Integration & UI (天数: 4)**
   - 开发 PyQt6 界面 (状态显示、操作按钮)
   - 将异步逻辑与 UI 线程对接
   - 集成 `send2trash` 安全删除
   - 全链路测试 (暂停/恢复/取消/重试场景)

---

## 12. 附录A: 分片MD5计算工具函数

```python
import hashlib
import os
from typing import List

def calculate_block_md5_list(file_path: str, block_size: int = 4 * 1024 * 1024) -> List[str]:
    """
    计算文件的分片MD5列表

    Args:
        file_path: 文件路径
        block_size: 分片大小，默认4MB

    Returns:
        MD5十六进制字符串列表
    """
    md5_list = []

    with open(file_path, 'rb') as f:
        while True:
            chunk = f.read(block_size)
            if not chunk:
                break
            md5_hash = hashlib.md5(chunk).hexdigest()
            md5_list.append(md5_hash)

    return md5_list

def encode_block_list(md5_list: List[str]) -> str:
    """
    将MD5列表编码为逗号分隔的字符串

    Args:
        md5_list: MD5字符串列表

    Returns:
        逗号分隔的字符串
    """
    return ','.join(md5_list)

def decode_block_list(encoded: str) -> List[str]:
    """
    解码MD5列表字符串

    Args:
        encoded: 逗号分隔的字符串

    Returns:
        MD5字符串列表
    """
    if not encoded:
        return []
    return encoded.split(',')
```

---

## 13. 附录B: 任务操作日志记录

```python
class TaskOperationLog(Base):
    __tablename__ = "task_operation_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("backup_records.id"), nullable=False)
    operation: Mapped[str] = mapped_column(String(32), nullable=False)  # submit/pause/resume/cancel/retry
    from_status: Mapped[TaskStatus] = mapped_column(Enum(TaskStatus), nullable=True)
    to_status: Mapped[TaskStatus] = mapped_column(Enum(TaskStatus), nullable=False)
    operator: Mapped[str] = mapped_column(String(32), default="user")  # user/system
    reason: Mapped[str] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=datetime.now)
```

---

## 14. 附录C: 百度API调用示例

```python
# create_super_file2 预上传请求示例
def pre_upload_request(file_path: str, cloud_path: str, block_list: List[str], upload_id: str = None):
    """
    百度网盘预上传请求

    API: POST /xpan/filesize
         POST /xpan/file/precreate

    Args:
        file_path: 本地文件路径
        cloud_path: 云端目标路径
        block_list: 分片MD5列表
        upload_id: 断点续传ID (可选)
    """
    file_size = os.path.getsize(file_path)

    # Step 1: 获取文件大小
    params = {'method': 'filesize', 'path': cloud_path}
    response = requests.post(BAIDU_PAN_API, params=params)

    # Step 2: 预创建请求
    precreate_params = {
        'method': 'precreate',
        'path': cloud_path,
        'size': file_size,
        'isexist': 1,
        'block_list': json.dumps(block_list),  # 关键：传入分片MD5列表
        'uploadid': upload_id or '',
    }

    return response.json()

# upload_part 分片上传请求示例
def upload_part(upload_id: str, part_number: int, data: bytes):
    """
    分片上传

    API: POST /xpan/filesize
         POST /xpan/file/uploadpart

    Args:
        upload_id: 预上传返回的upload_id
        part_number: 分片序号 (从1开始)
        data: 分片数据
    """
    upload_params = {
        'method': 'uploadpart',
        'uploadid': upload_id,
        'partnumber': part_number,
    }
    files = {'file': data}
    return requests.post(BAIDU_PAN_API, params=upload_params, files=files)

# finish_super_file2 完成上传请求示例
def finish_upload(cloud_path: str, upload_id: str, block_list: List[str]):
    """
    完成上传

    API: POST /xpan/file/create

    Args:
        cloud_path: 云端路径
        upload_id: 预上传返回的ID
        block_list: 分片MD5列表
    """
    finish_params = {
        'method': 'create',
        'path': cloud_path,
        'uploadid': upload_id,
        'block_list': json.dumps(block_list),
    }
    return requests.post(BAIDU_PAN_API, params=finish_params)
```
