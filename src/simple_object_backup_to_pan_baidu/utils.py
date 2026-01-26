import time
from typing import TypeVar,Callable,Any
from functools import wraps
T = TypeVar('T')

class UtilsError(Exception):
    """Base class for utils errors"""
class RetryError(UtilsError):
    """Error raised when a function call is retried too many times"""

def logger_configurer(q):
    import logging.handlers
    h = logging.handlers.QueueHandler(q)  # 只需要一个处理器
    root = logging.getLogger()
    root.addHandler(h)
    # 发送所有消息，用于演示；未应用其他层级或过滤逻辑。
    root.setLevel(logging.DEBUG)

class WorkerMixin:
    """为使用 ProcessPoolExecutor 的 Worker 进程提供日志配置支持的 Mixin"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # 在主进程中获取logger queue，确保子进程使用同一个实例
        from .config import get_logger_queue
        self._logger_queue = get_logger_queue()
        self._logger_configurer = logger_configurer

    def worker_process(self, *args, **kwargs):
        """Worker 进程入口：配置日志后执行实际工作"""
        self._logger_configurer(self._logger_queue)
        self._do_work(*args, **kwargs)

    def _do_work(self, *args, **kwargs):
        """子类重写：实际的业务逻辑"""
        raise NotImplementedError("Subclasses must implement _do_work()")

def retry_decorator(
    retries:int = 3,
    delay:float = 1.0,
    backoff:float = 1.0,
    exceptions:tuple[type[Exception]] = (Exception,)
    ):
    def decorator(func:Callable[...,T]) -> Callable[...,T]:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            for i in range(1,retries+1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    print(f"Exception {e} occurred, retrying... ({i}/{retries})")
                    if i == retries:
                        raise 
                    sleep_time = delay * (backoff ** (i-1))
                    print(f"Retrying after {sleep_time:.1f} seconds...")
                    time.sleep(sleep_time)
                except Exception as e:
                    raise RetryError(f"Function {func.__name__} raised an exception after {retries} retries") from e
            raise ValueError("Unreachable: retries must be >= 1")
        return wrapper
    return decorator





from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, Session
from sqlalchemy import MetaData, String, BigInteger, Text, UniqueConstraint
from sqlalchemy.exc import OperationalError
from datetime import datetime
from time import time_ns


class DbMixin(object):
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    created_at: Mapped[int] = mapped_column(BigInteger, default=time_ns)
    updated_at: Mapped[int] = mapped_column(BigInteger, onupdate=time_ns,nullable=True)

    @property
    def created_at_localtime(self):
        local_time_sec = self.created_at / 1_000_000_000.0
        return datetime.fromtimestamp(local_time_sec)

    @property
    def updated_at_localtime(self):
        local_time_sec = self.updated_at / 1_000_000_000.0
        return datetime.fromtimestamp(local_time_sec)

class StatusFinishedBase(DeclarativeBase):
    metadata = MetaData()



class StatusFinishedTable(DbMixin,StatusFinishedBase):
    __tablename__ = "status_finished"
    status_name: Mapped[str] = mapped_column(String(30))
    is_finished: Mapped[bool] = mapped_column(default=False, nullable=False)

    __table_args__ = (UniqueConstraint('status_name', name='uix_status_name'),)


class ErrorBase(DeclarativeBase):
    """Base class for other exceptions"""
    pass

class ErrorTable(DbMixin,ErrorBase):
    __tablename__ = "errors"
    service_name: Mapped[str] = mapped_column(String(32))
    error_message: Mapped[str] = mapped_column(Text)

@retry_decorator(retries=3, delay=1.0, backoff=2.0, exceptions=(OperationalError,))
def update_error_table(engine,service_name:str, error_message:str):
    """Update the error table with the given service name and error message."""
    with Session(engine) as session:
        session.add(ErrorTable(service_name=service_name, error_message=error_message))
        session.commit()
