from pydantic import BaseModel
from sqlalchemy.orm import DeclarativeBase, mapped_column, Mapped, Session
from sqlalchemy import Engine, BigInteger, String, Integer, UniqueConstraint, MetaData, JSON
from sqlalchemy import exc

from pathlib import Path
from typing import Literal
from concurrent.futures import ThreadPoolExecutor
import logging
import platform
import sys

from .utils import DbMixin, retry_for_class_method,ServiceStatusTable
from .db_service import DbService
from .config import get_config

class ScanServiceError(Exception):
    """Scan Service Error"""

class ScanServiceDbError(ScanServiceError):
    """Scan Service Db Error"""

class ScanServiceFileError(ScanServiceError):
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


class ScanRecords(DbMixin, _Base):
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
    raise_exception:type[Exception] = ScanServiceDbError,
):
    return retry_for_class_method(retries=retries, delay=delay, backoff=backoff, exceptions=exceptions, logger_attr=logger_attr, raise_exception=raise_exception)




class _ServiceRepository:
    def __init__(self, service_name: str, engine: Engine | None = None):
        self.engine = engine or DbService().get_engine()
        self.logger = logging.getLogger(f'service.{service_name}.repository')
        self.service_name = service_name

    @db_connect_retry()
    def add_scan_record(self, data: _FormatData):
        with Session(self.engine) as session:
            session.add(ScanRecords(**data.model_dump()))
            session.commit()

    @db_connect_retry()
    def get_scan_record_by_id(self, id: int):
        with Session(self.engine) as session:
            return session.get(ScanRecords, id)

    @db_connect_retry()
    def get_scan_record_by_unique(self, host_name: str, object_path: str):
        with Session(self.engine) as session:
            return session.query(ScanRecords).filter(
                ScanRecords.host_name == host_name,
                ScanRecords.object_path == object_path
            ).first()

    @db_connect_retry()
    def update_scan_record(self, data: ScanRecords):
        with Session(self.engine) as session:
            session.merge(data)
            session.commit()
    @db_connect_retry()
    def create_record_table(self):
        ScanRecords.metadata.create_all(self.engine)

    @db_connect_retry()
    def drop_record_table(self):
        ScanRecords.metadata.drop_all(self.engine)

    def reset_record_table(self):
        self.drop_record_table()
        self.create_record_table()

    @db_connect_retry()
    def set_service_status(self, status: str):
        self.logger.info(f"Service status set to {status}")
        ServiceStatusTable.metadata.create_all(self.engine)
        with Session(self.engine) as session:
            session.merge(ServiceStatusTable(service_name=self.service_name, status=status))
            session.commit()


def _scan_file(file_path: Path, relative_path: Path, host_name: str, logger:logging.Logger) -> _FormatData:
    """Scan a single file and return its scan result"""
    items_path = file_path.relative_to(relative_path).as_posix()
    logger.debug(f"Scanning file: {file_path}")
    return _FormatData(
        host_name=host_name,
        object_path=file_path,
        object_name=file_path.name,
        object_type="file",
        object_size=file_path.stat().st_size,
        object_item_count=1,
        object_items={items_path: file_path.stat().st_size}
    )

def _scan_directory(directory_path: Path, relative_path: Path, host_name: str, logger:logging.Logger) -> _FormatData:
    """Scan a directory recursively and return its scan result"""
    logger.debug(f"Scanning directory: {directory_path}")
    object_item_count = 0
    object_items = {}
    object_size = 0

    for item in directory_path.rglob("*"):
        if item.is_file():
            item_path = item.relative_to(relative_path).as_posix()
            object_item_count += 1
            object_items[item_path] = item.stat().st_size
            object_size += item.stat().st_size

    return _FormatData(
        host_name=host_name,
        object_path=directory_path,
        object_name=directory_path.name,
        object_type="directory",
        object_size=object_size,
        object_item_count=object_item_count,
        object_items=object_items
    )

def _scan_object(object_path: Path, host_name: str, logger:logging.Logger) -> _FormatData:
    """Scan an object (file or directory) and return its scan result"""
    if not object_path.exists():
        raise ScanServiceFileError(f"Object path does not exist: {object_path}")

    if object_path.is_file():
        return _scan_file(object_path, relative_path=object_path.parent, host_name=host_name, logger=logger)

    if object_path.is_dir():
        return _scan_directory(object_path, relative_path=object_path.parent, host_name=host_name, logger=logger)

    raise ScanServiceError(f"Invalid object path: {object_path}")


class ScanService:
    def __init__(self, max_worker: int):
        self.repository = _ServiceRepository('scan_service')
        self.host_name = platform.node()
        self.logger = logging.getLogger('service.scan_service')
        temp_config = get_config()
        self.target_paths = [Path(path) for path in temp_config.source_path_list]
        self.executor = ThreadPoolExecutor(max_worker, thread_name_prefix='scan_service_thread')
        self.tasks = []

    def start(self):
        ...
    
    def process(self):
        with self.executor as executor:
            for path in self.target_paths:
                self.tasks.append(executor.submit(self.worker, path, self.host_name, self.logger))
    @staticmethod
    def worker(object_path: Path, host_name: str, logger:logging.Logger):
        try:
            result = _scan_object(object_path, host_name, logger)
            return {'object':object_path, 'status':True,'result':result}
        except Exception as e:
            logger.error(f"Error scanning object {object_path}: {e}")
            return {'object':object_path, 'status':False,'result':None}

    def stop(self):
        self.logger.warning('scan_service_stop_requested')
        self.executor.shutdown(wait=False, cancel_futures=True)
        sys.exit('scan_service_stop_requested')

        
    def shutdown(self):
        import os
        self.logger.warning('scan_service_shutdown_requested')
        os._exit(1)  # Use os._exit to immediately terminate the process without running any cleanup code
