这是一份经过严格整合的、达到工业级开发标准的 **产品需求文档 (PRD) v2.0**。该文档合并了初始需求与后续增强的安全机制，可直接作为架构设计和代码开发的蓝本。

---

# 产品需求文档 (PRD): 智能云备份归档系统 (Smart Cloud Archiver)

| 项目 | 内容 |
| --- | --- |
| **文档版本** | v2.0 (Integrated Final) |
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
5. **Processor (执行引擎):**
* *Hasher:* 极速哈希计算。
* *Packer:* AES-256 加密压缩。
* *Verifier:* 解压回验。
* *Uploader:* 百度网盘分片流式上传。


6. **Safety Cleaner (安全清理器):** 区分“物理删除”与“回收站删除”。

---

## 4. 详细业务流程 (Business Logic)

### 4.1 启动与崩溃恢复 (Crash Recovery)

* **Session ID:** 每次启动生成唯一 UUID (`runtime_session_id`)。
* **自愈逻辑 (The Janitor):**
1. 程序启动时，查询 DB 中所有状态为 `PROCESSING` (Hash/Pack/Verify/Upload) 的任务。
2. 若任务 `session_id` != 当前 ID，判定为 **崩溃残留**。
3. **清理动作:**
* 读取 DB 中记录的 `temp_path` 和 `verify_path`，执行物理删除 (`os.remove/rmtree`)。
* 重置 DB 状态为 `PENDING`，清除 `upload_id`。
* 记录恢复日志。





### 4.2 扫描与属性推断

* **一级目录原则:** 仅处理指定根目录下的第一级子目录或文件。
* **敏感内容检测 (Porn Detection):**
* 基于正则匹配文件名（如常见关键词）。
* 若命中，DB 标记 `is_sensitive=True`，UI 标红，但不阻止上传。


* **文件夹属性推断:**
* 若内部文件数 > 100 且平均大小 < 1MB -> **文档/杂项**。
* 若视频文件体积占比 > 50% -> **视频文件夹**。
* 若包含 `.exe`/`.msi` 且体积 > 100MB -> **安装包**。



### 4.3 极速哈希与去重 (Hashing & Deduplication)

* **多机唯一性:** 使用 `Device_ID` (机器码) + `Source_Path` 作为本地唯一键。
* **加速策略:**
* **大文件:** 使用 `mmap` 内存映射读取，避免频繁内核态拷贝。
* **海量小文件文件夹(文件数量大于100，不计算文件夹):** **不读取全部内容**。
* 算法示例：
    ```
    dir_hash_obj = hashlib.new(algorithm)
    files = sorted([file_name for file_name in dit_path.rglobs(*) if file_name.is_file() ])
    for file in files:
        dir_hash_obj.update(calculate_file_partial_hash(dile,algorithm))
    return dir_hash_obj.hexdigest().upper()
def calculate_file_partial_hash(file_path, algorithm='sha256'):
    """
    计算文件头4KB和尾4KB数据的合并哈希值
    """
    header_size = 4096  # 4KB
    trailer_size = 4096 # 4KB
    total_size = header_size + trailer_size

    try:
        file_size = os.path.getsize(file_path)
    except OSError as e:
        raise RuntimeError(f"无法获取文件大小: {e}")

    # 如果文件太小，则直接读取整个文件
    if file_size <= total_size:
        with open(file_path, 'rb') as f:
            data = f.read()
    else:
        with open(file_path, 'rb') as f:
            # 读取头部4KB
            header_data = f.read(header_size)
            # 移动指针到文件末尾前4KB处，读取尾部数据
            f.seek(-trailer_size, 2)
            trailer_data = f.read(trailer_size)
            # 合并两部分数据
            data = header_data + trailer_data

    # 计算合并数据的哈希值
    hash_obj = hashlib.new(algorithm)
    hash_obj.update(data)
    return hash_obj.digest()
    ```





* **全局去重逻辑:**
1. 计算 Hash。
2. 查询 DB: `SELECT * FROM backup_records WHERE file_hash = ? AND status = 'COMPLETED'`。
3. **命中:** 标记当前任务 `is_duplicate=True`，关联旧记录 ID，**跳过**打包上传，直接进入删除流程。



### 4.4 安全打包与验证闭环

* **配额控制:** 申请磁盘空间信号量，若 `current_temp_usage > LIMIT` 则挂起等待。
* **加密:** AES-256 算法。
* **强制验证:**
1. 解压加密包到临时目录 `VERIFY_DIR`。
2. 比对解压后文件与源文件的 Hash。
3. **验证失败:** 立即报错，禁止上传，保留源文件。
4. **验证成功:** 释放验证区的磁盘空间，进入上传。



### 4.5 分片上传 (Streaming Upload)

* **流式处理:** 不生成物理分片文件。使用 Python Generator (`yield chunk`) 直接喂给百度 SDK 接口，减少 IO 损耗。
* **分片大小:** 动态调整 (4MB - 32MB)。

### 4.6 安全删除 (Cleanup)

* **临时文件 (Zip/Enc/Verify):** 使用 `os.remove` **物理删除**，不进回收站。
* **源文件 (Source):**
* **必须** 使用 `send2trash` 库放入 **Windows 回收站**。
* 防止程序误判导致数据永久丢失，留给人工最后一道防线。



---

## 5. 数据库设计 (Schema)

使用 SQLAlchemy 2.0 风格定义。

```python
import enum
from datetime import datetime
from sqlalchemy import String, BigInteger, Boolean, Enum, ForeignKey, UniqueConstraint, Index
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

class Base(DeclarativeBase):
    pass

class TaskStatus(enum.Enum):
    PENDING = "pending"
    HASHING = "hashing"
    PACKING = "packing"
    VERIFYING = "verifying"
    UPLOADING = "uploading"
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
    device_id: Mapped[str] = mapped_column(String(64), nullable=False)  # 机器码
    source_path: Mapped[str] = mapped_column(String(512), nullable=False) # 本地路径
    file_name: Mapped[str] = mapped_column(String(255))
    
    # --- 2. 属性与分类 ---
    is_directory: Mapped[bool] = mapped_column(Boolean, default=False)
    total_size: Mapped[int] = mapped_column(BigInteger, default=0)
    category: Mapped[FileCategory] = mapped_column(Enum(FileCategory), default=FileCategory.MIXED)
    is_porn_sensitive: Mapped[bool] = mapped_column(Boolean, default=False) # 敏感标记

    # --- 3. 核心指纹 (全局去重) ---
    file_hash: Mapped[str] = mapped_column(String(64), index=True, nullable=True) # SHA256
    is_duplicate: Mapped[bool] = mapped_column(Boolean, default=False)
    original_record_id: Mapped[int] = mapped_column(ForeignKey("backup_records.id"), nullable=True)

    # --- 4. 任务控制与恢复 ---
    session_id: Mapped[str] = mapped_column(String(36), index=True, nullable=True) # 崩溃恢复锚点
    status: Mapped[TaskStatus] = mapped_column(Enum(TaskStatus), default=TaskStatus.PENDING)
    error_log: Mapped[str] = mapped_column(String(1024), nullable=True)

    # --- 5. 临时资源 (用于清理) ---
    temp_archive_path: Mapped[str] = mapped_column(String(512), nullable=True)
    verify_extract_path: Mapped[str] = mapped_column(String(512), nullable=True)

    # --- 6. 云端信息 ---
    cloud_path: Mapped[str] = mapped_column(String(512), nullable=True)
    upload_id: Mapped[str] = mapped_column(String(128), nullable=True) # 百度断点续传ID

    created_at: Mapped[datetime] = mapped_column(default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(default=datetime.now, onupdate=datetime.now)

    # 约束: 同一台机器的同一个路径只能有一条记录
    __table_args__ = (
        UniqueConstraint('device_id', 'source_path', name='uix_device_src_path'),
        Index('idx_status_session', 'status', 'session_id'),
    )

```

---

## 6. 异常处理规范

1. **网络异常:** `try-except` 包裹所有 SDK 调用。重试 3 次后失败，标记状态 `FAILED`，保留本地文件，不执行删除。
2. **磁盘空间不足:** 在申请磁盘配额时，如果系统总盘符剩余空间 < 5GB，强制暂停所有新任务，UI 弹窗报警。
3. **加密/解压错误:** 必须捕获 `BadZipFile` 等异常，视为严重错误，标记 `FAILED`。

---

## 7. UI 界面需求 (PyQt6)

### 7.1 主面板

* **Dashboard:**
* 仪表盘显示：已备份大小 / 总释放空间。
* 当前并发线程数 / 实时上传速度。


* **Task Grid (任务列表):**
* 列：文件名 | 大小 | 状态 | 进度条 | 类别 | 耗时。
* **高亮规则:** 若 `is_porn_sensitive == True`，该行文字变红或显示 "18+" 图标。
* **去重显示:** 若 `is_duplicate == True`，状态栏显示 "秒传完成"。


* **Log Console:** 底部可折叠的日志窗口。

---

## 8. 开发实施计划

1. **Phase 1: Core & DB (天数: 2)**
* 完成 SQLAlchemy 模型定义。
* 实现 `SessionManager` 和崩溃恢复逻辑 (Janitor)。
* 实现日志模块 (Loguru)。


2. **Phase 2: Local Logic (天数: 3)**
* 实现 `Scanner` (含敏感词、属性推断)。
* 实现 `Hasher` (mmap, Merkle Root)。
* 实现 `Packer` & `Verifier` (集成 7z, 磁盘配额 Semaphore)。


3. **Phase 3: Cloud & Upload (天数: 3)**
* 封装百度网盘 SDK (获取 Token, 刷新 Token)。
* 实现 Generator 流式分片上传。


4. **Phase 4: Integration & UI (天数: 4)**
* 开发 PyQt6 界面。
* 将异步逻辑 (`asyncio`) 与 UI 线程 (`QThread`) 对接。
* 集成 `send2trash` 安全删除。
* 全链路测试 (模拟断电、断网)。



---

## 9. 附录：关键算法伪代码

### 磁盘配额锁 (Async Disk Semaphore)

```python
import asyncio

class DiskQuotaManager:
    def __init__(self, limit_bytes):
        self.limit = limit_bytes
        self.used = 0
        self.condition = asyncio.Condition()

    async def acquire(self, size):
        async with self.condition:
            while self.used + size > self.limit:
                await self.condition.wait()
            self.used += size

    async def release(self, size):
        async with self.condition:
            self.used -= size
            self.condition.notify_all()

```