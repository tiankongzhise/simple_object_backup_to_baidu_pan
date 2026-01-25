import time
from typing import TypeVar,Callable,Any
from functools import wraps
T = TypeVar('T')

class UtilsError(Exception):
    """Base class for utils errors"""
class RetryError(UtilsError):
    """Error raised when a function call is retried too many times"""

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





from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import MetaData, String, BigInteger, UniqueConstraint
from datetime import datetime
from time import time_ns

class StatusFinishedBase(DeclarativeBase):
    metadata = MetaData()

class StatusFinishedTable(StatusFinishedBase):
    __tablename__ = "status_finished"
    status_name: Mapped[str] = mapped_column(String(30))
    is_finished: Mapped[bool] = mapped_column(default=False, nullable=False)

    __table_args__ = (UniqueConstraint('status_name', name='uix_status_name'),)


class DbMixin(DeclarativeBase):
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