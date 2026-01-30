from pydantic import BaseModel
from sqlalchemy.orm import DeclarativeBase, mapped_column, Mapped, Session
from sqlalchemy import Engine, BigInteger, String, Integer, UniqueConstraint, MetaData, JSON
from sqlalchemy import exc

from pathlib import Path
from typing import Literal, Callable, Any
from functools import wraps
import logging
import platform

from .utils import DbMixin, retry_for_class_method, ServiceStatusTable, get_service_table, get_auxiliary_table, get_auxiliary_format
from .db_service import DbService

class ?ServiceError(Exception):
    """Scan Service Error"""

class ?ServiceDbError(?ServiceError):
    """Scan Service Db Error"""

class ?ServiceFileError(?ServiceError):
    """Scan Service File Error"""


class _FormatData(BaseModel):
    """Scan format data for a single object"""
    host_name: str
    object_path: Path
    object_name: str
    object_type: Literal["file", "directory"]
    object_size: int
    object_item_count: int
    object_items: dict[str, int]
    status: Literal['waiting','processing','fail','done'] = 'waiting'


class _Base(DeclarativeBase):
    metadata = MetaData()


class ?Records(DbMixin, _Base):
    __tablename__ = "scan_records"
    host_name: Mapped[str] = mapped_column(String(255))
    object_path: Mapped[str] = mapped_column(String(255))
    object_name: Mapped[str] = mapped_column(String(255))
    object_type: Mapped[str] = mapped_column(String(15))
    object_size: Mapped[int] = mapped_column(BigInteger)
    object_item_count: Mapped[int] = mapped_column(Integer)
    object_items: Mapped[dict] = mapped_column(JSON)
    status: Mapped[Literal['waiting','processing','fail','done']] = mapped_column(String(15), default='waiting')
    __table_args__ = (UniqueConstraint('host_name', 'object_path', name='uix_host_name_object_path'),)

def db_connect_retry(
    retries:int = 3,
    delay:float = 1.0,
    backoff:float = 1.0,
    exceptions:tuple[type[Exception]] = (exc.OperationalError,),
    logger_attr: str = "logger",
    raise_exception:type[Exception] = ?ServiceDbError,
):
    return retry_for_class_method(retries=retries, delay=delay, backoff=backoff, exceptions=exceptions, logger_attr=logger_attr, raise_exception=raise_exception)




class _ServiceRepository:
    def __init__(self, service_name: str, engine: Engine | None = None, dependent_service_name: list[str]|None = None):
        self.engine = engine or DbService().get_engine()
        self.logger = logging.getLogger(f'service.{service_name}.repository')
        self.host_name = platform.node()
        self.service_name = service_name
        self.dependent_service_name = dependent_service_name or []

    @db_connect_retry()
    def add_?_record(self, data: _FormatData):
        with Session(self.engine) as session:
            session.add(?Records(**data.model_dump()))
            session.commit()

    @db_connect_retry()
    def get_?_record_by_id(self, id: int):
        with Session(self.engine) as session:
            return session.get(ScanRecords, id)

    @db_connect_retry()
    def get_?_record_by_unique(self, host_name: str, object_path: str):
        with Session(self.engine) as session:
            return session.query(ScanRecords).filter(
                ScanRecords.host_name == host_name,
                ScanRecords.object_path == object_path
            ).first()


class ?Service:
    def __init__(self, service_name: str, engine: Engine | None = None, dependent_service_name: list[str]|None = None):
        self.service_orm_items = [?orm_items]
        self.dependent_service_name = dependent_service_name or [?dependent_service_name]
        self.service_name = service_name
        self.logger = logging.getLogger(f'service.{self.service_name}')
        self.engine = engine or DbService().get_engine()
        self.repository = ?Repository(self.service_name, self.engine, self.dependent_service_name)
        self.executor = ?
        self.logger_queue = ?
        self.status = ?
    
    def start(self):
        ...
    
    def process(self):
        ...
    
    def stop(self):
        ...
    
    def shutdown(self):
        ...
    
    def set_service_finish_status(self, status: bool):
        ...
    
    def set_dependent_service_record_status(self, status: Literal['waiting','processing','fail','done']):
        ...
    
    @staticmethod
    def worker():
        ...

    def check_dependent_service_finished(self) -> bool:
        ...

    def get_next_waiting_record(self):
        ...
    

class ?ServiceUtils:
    def campare_item(self, a, b):
        ...
    def trans_records_to_format_data(self, records):
        ...
    def trans_format_data_to_records(self, format_data):
        ...
    