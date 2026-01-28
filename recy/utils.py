
import time
from typing import TypeVar,Callable,Any,overload
from functools import wraps
from logging import Logger
from pydantic import BaseModel
T = TypeVar('T')

class UtilsError(Exception):
    """Base class for utils errors"""
class RetryError(UtilsError):
    """Error raised when a function call is retried too many times"""

def logger_configurer(q,logger:Logger|None = None):
    import logging.handlers
    h = logging.handlers.QueueHandler(q)  # 只需要一个处理器
    root = logger or logging.getLogger()
    root.addHandler(h)
    # 发送所有消息，用于演示；未应用其他层级或过滤逻辑。
    root.setLevel(logging.DEBUG)

class WorkerMixin:
    """为使用 ProcessPoolExecutor 的 Worker 进程提供日志配置支持的 Mixin"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # 在主进程中获取logger queue，确保子进程使用同一个实例
        from src.simple_object_backup_to_pan_baidu.config import get_logger_queue
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
    exceptions:tuple[type[Exception]] = (Exception,),
    logger:Logger|None = None,
    raise_exception:type[Exception] = Exception,
    ):
    def decorator(func:Callable[...,T]) -> Callable[...,T]:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            for i in range(1,retries+1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    if logger:
                        logger.error(f"Exception {e} occurred, retrying... ({i}/{retries})", exc_info=True)
                    else:
                        print(f"Exception {e} occurred, retrying... ({i}/{retries})")
                    if i == retries:
                        raise 
                    sleep_time = delay * (backoff ** (i-1))
                    if logger:
                        logger.info(f"Retrying after {sleep_time:.1f} seconds...")
                    else:
                        print(f"Retrying after {sleep_time:.1f} seconds...")
                    time.sleep(sleep_time)
                except Exception as e:
                    raise raise_exception(f"Function {func.__name__} raised an exception after {retries} retries") from e
            raise RetryError("Unreachable: retries must be >= 1")
        return wrapper
    return decorator

import time
from functools import wraps
from typing import Any, Callable, TypeVar, Type
import logging
T = TypeVar('T')
def retry_for_class_method(
    retries: int = 3,
    delay: float = 1.0,
    backoff: float = 1.0,
    exceptions: tuple[Type[Exception]] = (Exception,),
    raise_exception: Type[Exception] = Exception,
    logger_attr: str = "logger"  # 支持自定义logger属性名
):
    """专为类方法设计的重试装饰器"""
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(instance: Any, *args: Any, **kwargs: Any) -> T:
            # 从实例中获取logger
            logger = getattr(instance, logger_attr, None)
            service_name = instance.service_name
            func_name = func.__name__
            
            for i in range(1, retries + 1):
                try:
                    return func(instance, *args, **kwargs)
                except exceptions as e:
                    if logger:
                        logger.error(f"{service_name}.{func_name}Exception {e} occurred, retrying... ({i}/{retries})", exc_info=True)
                    else:
                        print(f"{service_name}.{func_name}Exception {e} occurred, retrying... ({i}/{retries})")
                    
                    if i == retries:
                        if logger:
                            logger.error(f"{service_name}.{func_name}Exception {e} occurred, max retries {retries} reached")
                        else:
                            print(f"{service_name}.{func_name}Exception {e} occurred, max retries {retries} reached")
                        raise raise_exception(f"{service_name}.{func_name} raised an exception after {retries} retries,max retries reached") from e
                    
                    sleep_time = delay * (backoff ** (i - 1))
                    if logger:
                        logger.info(f"Retrying after {sleep_time:.1f} seconds...")
                    else:
                        print(f"Retrying after {sleep_time:.1f} seconds...")
                    time.sleep(sleep_time)
                except Exception as e:
                    if logger:
                        logger.error(f"{service_name}.{func_name}Exception {e} occurred, retrying... ({i}/{retries})", exc_info=True)
                    raise raise_exception(f"Method {func.__name__} raised an exception after {i} retries") from e
            raise Exception("Unreachable: retries must be >= 1")
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



class ServiceStatusTable(DbMixin,StatusFinishedBase):
    __tablename__ = "service_status"
    service_name: Mapped[str] = mapped_column(String(30))
    is_finished: Mapped[bool] = mapped_column(default=False, nullable=False)

    __table_args__ = (UniqueConstraint('service_name', name='uix_service_name'),)


class ServiceStatusFormat(BaseModel):
    service_name: str
    is_finished: bool

class ErrorBase(DeclarativeBase):
    """Base class for other exceptions"""
    pass



class ErrorTable(DbMixin,ErrorBase):
    __tablename__ = "errors"
    service_name: Mapped[str] = mapped_column(String(32))
    error_message: Mapped[str] = mapped_column(Text)

class ErrorFormat(BaseModel):
    service_name: str
    error_message: str

@retry_decorator(retries=3, delay=1.0, backoff=2.0, exceptions=(OperationalError,))
def update_error_table(engine,service_name:str, error_message:str):
    """Update the error table with the given service name and error message."""
    with Session(engine) as session:
        session.add(ErrorTable(service_name=service_name, error_message=error_message))
        session.commit()

def reset_service_status_table(engine):
    """Reset the service status table with the given service name."""
    ServiceStatusTable.metadata.drop_all(bind=engine)
    ServiceStatusTable.metadata.create_all(bind=engine)

def get_service_table(service_name: str):
    from src.simple_object_backup_to_pan_baidu.scan_service import ScanRecords
    from src.simple_object_backup_to_pan_baidu.hash_service import HashRecords
    table_map = {
        "scan_service": ScanRecords,
        "hash_service": HashRecords
    }
    return table_map[service_name]

class ManualReviewBase(DeclarativeBase):
    metadata = MetaData()
from sqlalchemy import Integer
from typing import Literal




class ManualReviewRecords(DbMixin, ManualReviewBase):
    __tablename__ = "manual_review_records"
    host_name: Mapped[str] = mapped_column(String(255))
    object_path: Mapped[str] = mapped_column(String(255))
    object_name: Mapped[str] = mapped_column(String(255))
    object_type: Mapped[str] = mapped_column(String(15))
    object_size: Mapped[int] = mapped_column(BigInteger)
    object_item_count: Mapped[int] = mapped_column(Integer)
    scan_id: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(255))
    status: Mapped[Literal['waiting', 'processing', 'fail', 'done']
                   ] = mapped_column(String(15), default='waiting')

    __table_args__ = (
        UniqueConstraint('host_name', 'object_path', name='uix_host_name_object_path'),
        UniqueConstraint('scan_id', name='uix_scan_id'),
    )

class ManualReviewFormat(BaseModel):
    host_name: str
    object_path: str
    object_name: str
    object_type: str
    object_size: int
    object_item_count: int
    scan_id: int
    reason: str
    status: Literal['waiting', 'processing', 'fail', 'done'] = 'waiting'


@overload
def get_auxiliary_table(table_purpose: Literal['human_review']) -> Type[ManualReviewRecords]:
    ...

@overload
def get_auxiliary_table(table_purpose: Literal['manual_review']) -> Type[ManualReviewRecords]:
    ...

@overload
def get_auxiliary_table(table_purpose: Literal['service_status']) -> Type[ServiceStatusTable]:
    ...

@overload
def get_auxiliary_table(table_purpose: Literal['error_table']) -> Type[ErrorTable]:
    ...

def get_auxiliary_table(table_purpose: Literal['human_review','manual_review','service_status','error_table']):
    auxiliary_tables_map = {
        "human_review": ManualReviewRecords,
        "service_status": ServiceStatusTable,
        "manual_review": ManualReviewRecords,
        "error_table": ErrorTable
        }
    return auxiliary_tables_map[table_purpose]

@overload
def get_auxiliary_format(table_purpose: Literal['human_review']) -> Type[ManualReviewFormat]:
    ...

@overload
def get_auxiliary_format(table_purpose: Literal['manual_review']) -> Type[ManualReviewFormat]:
    ...

@overload
def get_auxiliary_format(table_purpose: Literal['service_status']) -> Type[ServiceStatusFormat]:
    ...

@overload
def get_auxiliary_format(table_purpose: Literal['error_table']) -> Type[ErrorFormat]:
    ...
    
def get_auxiliary_format(table_purpose: Literal['human_review','manual_review','service_status','error_table']):
    auxiliary_formats_map = {
        "human_review": ManualReviewFormat,
        "service_status": ServiceStatusFormat,
        "manual_review": ManualReviewFormat,
        "error_table": ErrorFormat
        }
    return auxiliary_formats_map[table_purpose]
