from sqlalchemy.util import NoneType
from .config import get_config
from logging import config
import logging
from multiprocessing import Queue
from threading import Thread
from pathlib import Path
from typing import Any


class _LoggingSystem:
    """内部类：控制整个日志系统（单例）"""

    __instance = None
    _is_initialized = False
    _is_started = False
    _is_stopped = False

    _alive_loggers = set()
    def __new__(cls):
        if cls.__instance is None:
            cls.__instance = super().__new__(cls)
        return cls.__instance

    def __init__(self):
        if _LoggingSystem._is_initialized:
            return
        _LoggingSystem._is_initialized = True
        self.logger_setting = get_config().logger_setting
        self.queue = Queue()

    def _load_config(self):
        for handler in self.logger_setting['handlers'].values():
            if 'filename' in handler:
                temp_path = Path(handler['filename'])
                temp_path.parent.mkdir(parents=True, exist_ok=True)
        config.dictConfig(self.logger_setting)

    def _worker(self):
        while True:
            record = self.queue.get()
            if record is None:
                break
            logger = logging.getLogger(record.name)
            logger.handle(record)

    def start(self):
        if not self._is_started:
            self._load_config()
            self.logger_thread = Thread(target=self._worker)
            self.logger_thread.start()
            self._is_started = True



    def stop(self):
        if self._is_started and not self._is_stopped:
            self.queue.put(None)
            self.logger_thread.join(timeout=5)
            self.queue.close()
            self._is_stopped = True

    def __del__(self):
        self.stop()

class LoggerService:
    """日志服务（代理模式），每次创建新实例代理对应的 logger"""
    _is_stopped = False

    def __init__(self, name: str | None = None):
        if name is None:
            name = "root"
        self._logger_name = name
        # 确保日志系统已初始化
        self._LoggingSystem = _LoggingSystem()
        self._logger = logging.getLogger(self._logger_name)

    def stop(self) -> None:
        """停止当前 logger 实例"""
        self._is_stopped = True
        self._LoggingSystem._alive_loggers.discard(self)
        thread = Thread(target=self._auto_stop_logger_service, daemon=True)
        thread.start()
        print(f"Stopped logger {self._logger_name}")

    def __getattr__(self, name:str) -> Any:
        """代理所有方法调用到对应的 logger"""
        if self._is_stopped:
            print(f"Logger {self._logger_name} has been stopped, no method can be called")
            return lambda *args, **kwargs: None
        if name.startswith("_"):
            if hasattr(self._logger, name):
                return getattr(self._LoggingSystem, name)
            else:
                raise AttributeError(f"{self.__class__.__name__} has no attribute '{name}'")

        if hasattr(self._LoggingSystem, name):
            return getattr(self._LoggingSystem, name)
        
        if not hasattr(self._logger, name):
            raise AttributeError(f"{self.__class__.__name__} has no attribute '{name}'")
        return getattr(self._logger, name)
    
    def _auto_stop_logger_service(self):
        import time
        print(f"Auto stop logger service in 10 seconds...")
        is_stopped = True
        for i in range(1,11):
            if self._LoggingSystem._alive_loggers:
                is_stopped = False
                break
            time.sleep(1)
        if is_stopped:
            print("Auto stop logger service  hutting down logger service...")
            shutdown_logger_service()


def get_logger(name: str | None = None) -> LoggerService:
    """获取 LoggerService 实例（每次调用返回新实例，记住对应的 logger 名称）"""
    logger = LoggerService(name)
    logger.start()
    logger._LoggingSystem._alive_loggers.add(logger)
    return logger

def shutdown_logger_service():
    _LoggingSystem().stop()
