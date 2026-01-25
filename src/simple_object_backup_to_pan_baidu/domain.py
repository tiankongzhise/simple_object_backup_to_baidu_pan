from abc import ABC, abstractmethod
from typing import List, Set,Literal
from concurrent.futures import Future, ThreadPoolExecutor,ProcessPoolExecutor
import threading

class BaseService(ABC):
    """服务基类"""
    
    def __init__(self, name: str, max_workers: int = 5, pool_type:Literal["thread", "process"] = "thread"):
        self.name = name
        _executor = ThreadPoolExecutor if pool_type == "thread" else ProcessPoolExecutor
        _executor_params = self._create_executor_params(name, max_workers, pool_type)
        self._executor = _executor(
            **_executor_params
        )
        self._stop_accepting = threading.Event()
        self._pending_futures: Set[Future] = set()
        self._futures_lock = threading.Lock()
    def _create_executor_params(self, name: str, max_workers: int, pool_type:Literal["thread", "process"]):
        if pool_type == "thread":
            return {"max_workers": max_workers, "thread_name_prefix": f"{name}_"}
        elif pool_type == "process":
            return {"max_workers": max_workers, "process_name_prefix": f"{name}_"}
        else:
            raise ValueError("Invalid pool_type. Use 'thread' or 'process'.")

    def submit_task(self, task_func, *args, **kwargs) -> Future:
        """提交任务"""
        if self._stop_accepting.is_set():
            raise RuntimeError(f"服务 {self.name} 已停止接受新任务")
            
        future = self._executor.submit(self._wrapped_task, task_func, *args, **kwargs)
        
        with self._futures_lock:
            self._pending_futures.add(future)
            
        # 添加回调，任务完成后从集合中移除
        future.add_done_callback(self._remove_future)
        return future
        
    def _wrapped_task(self, task_func, *args, **kwargs):
        """包装任务，添加异常处理"""
        try:
            return task_func(*args, **kwargs)
        except Exception as e:
            logger.error(f"服务 {self.name} 任务执行出错: {e}")
            raise
            
    def _remove_future(self, future: Future):
        """从待处理集合中移除future"""
        with self._futures_lock:
            self._pending_futures.discard(future)
            
    def stop_accepting_tasks(self):
        """停止接受新任务"""
        self._stop_accepting.set()
        logger.info(f"服务 {self.name} 已停止接受新任务")
        
    def prepare_shutdown(self):
        """准备关闭"""
        logger.info(f"服务 {self.name} 准备关闭...")
        # 这里可以执行服务特定的关闭准备操作
        # 比如保存状态、通知外部系统等
        
    def get_pending_futures(self) -> List[Future]:
        """获取待处理的future列表"""
        with self._futures_lock:
            return list(self._pending_futures)
            
    def wait_for_completion(self, timeout: float = 30) -> bool:
        """等待所有任务完成"""
        start = time.time()
        
        while time.time() - start < timeout:
            with self._futures_lock:
                if not self._pending_futures:
                    return True
                    
            time.sleep(0.1)
            
        with self._futures_lock:
            remaining = len(self._pending_futures)
            
        logger.warning(f"服务 {self.name} 在 {timeout} 秒后仍有 {remaining} 个任务未完成")
        return False
        
    def cleanup(self):
        """清理资源"""
        # 子类可以重写此方法
        pass
        
    def shutdown_executor(self, wait: bool = True, timeout: float = 5):
        """关闭线程池"""
        self._executor.shutdown(wait=wait, timeout=timeout)
        
    @abstractmethod
    def run(self):
        """服务主循环（如果需要）"""
        pass