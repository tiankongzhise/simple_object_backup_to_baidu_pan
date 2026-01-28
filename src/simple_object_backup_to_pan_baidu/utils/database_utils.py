
from typing import TypeVar,Callable,Any,Type,Literal, overload,TYPE_CHECKING
from logging import Logger
from functools import wraps
import time

T = TypeVar('T')

from .exception import RetryError
from .models import ServiceStatusTable, ErrorTable, ManualReviewRecords, ManualReviewFormat, ServiceStatusFormat, ErrorFormat
if TYPE_CHECKING:
    from simple_object_backup_to_pan_baidu.scan_service import ScanRecords
    from simple_object_backup_to_pan_baidu.hash_service import HashRecords

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



def reset_service_status_table(engine):
    """Reset the service status table with the given service name."""
    ServiceStatusTable.metadata.drop_all(bind=engine)
    ServiceStatusTable.metadata.create_all(bind=engine)


@overload
def get_service_table(service_name: Literal['scan_service']) -> Type["ScanRecords"]:
    ...
@overload
def get_service_table(service_name: Literal['hash_service']) -> Type["HashRecords"]:
    ...

def get_service_table(service_name: Literal['scan_service', 'hash_service']):
    # """Get the service table class for the given service name."""
    from src.simple_object_backup_to_pan_baidu.scan_service import ScanRecords
    from src.simple_object_backup_to_pan_baidu.hash_service import HashRecords
    table_map = {
        "scan_service": ScanRecords,
        "hash_service": HashRecords
    }
    return table_map[service_name]



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


