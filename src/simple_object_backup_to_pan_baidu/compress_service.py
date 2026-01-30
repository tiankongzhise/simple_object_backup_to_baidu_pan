from pydantic import BaseModel
from sqlalchemy.orm import DeclarativeBase, mapped_column, Mapped, Session
from sqlalchemy import Engine, BigInteger, String, Integer, UniqueConstraint, MetaData, JSON, Boolean
from sqlalchemy import exc

from pathlib import Path
from typing import Literal, Callable, Any
from functools import wraps
from concurrent.futures import ProcessPoolExecutor,as_completed
import logging
import platform

from .utils import retry_for_class_method,logger_configurer
from .utils import DbMixin,ServiceStatusTable
from .db_service import DbService
from .config import get_config,get_logger_queue
from .domain import ServiceStatus

class CompressServiceError(Exception):
    """Scan Service Error"""

class CompressServiceDbError(CompressServiceError):
    """Scan Service Db Error"""

class CompressServiceFileError(CompressServiceError):
    """Scan Service File Error"""


class _FormatData(BaseModel):
    """Scan format data for a single object"""
    host_name: str
    zip_file_path: str
    zip_file_name: str
    source_object_type: Literal["file", "directory"]
    source_object_id:int
    is_source_zip: bool
    status: Literal['waiting','processing','fail','done'] = 'waiting'


class _Base(DeclarativeBase):
    metadata = MetaData()


class CompressServiceRecords(DbMixin, _Base):
    __tablename__ = "compress_service_records"
    host_name: Mapped[str] = mapped_column(String(255))
    zip_file_path: Mapped[str] = mapped_column(String(255))
    zip_file_name: Mapped[str] = mapped_column(String(255))
    source_object_type: Mapped[Literal["file", "directory"]] = mapped_column(String(15))
    source_object_id: Mapped[int] = mapped_column(Integer)
    is_source_zip: Mapped[bool] = mapped_column(Boolean)
    status: Mapped[Literal['waiting','processing','fail','done']] = mapped_column(String(15), default='waiting')
    __table_args__ = (
        UniqueConstraint('host_name', 'zip_file_path', name='uix_host_name_zip_file_path'),
        UniqueConstraint('source_object_id',  name='uix_source_object_id'),)

def db_connect_retry(
    retries:int = 3,
    delay:float = 1.0,
    backoff:float = 1.0,
    exceptions:tuple[type[Exception]] = (exc.OperationalError,),
    logger_attr: str = "logger",
    raise_exception:type[Exception] = CompressServiceDbError,
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
    def add_compress_service_record(self, data: _FormatData):
        with Session(self.engine) as session:
            session.add(CompressServiceRecords(**data.model_dump()))
            session.commit()

    @db_connect_retry()
    def get_compress_service_record_by_id(self, id: int):
        with Session(self.engine) as session:
            return session.get(CompressServiceRecords, id)

    @db_connect_retry()
    def get_compress_service_record_by_unique(self, host_name: str, object_path: str):
        with Session(self.engine) as session:
            return session.query(CompressServiceRecords).filter(
                CompressServiceRecords.host_name == host_name,
                CompressServiceRecords.zip_file_path == object_path
            ).first()
    @db_connect_retry()
    def get_all_compress_service_records(self):
        with Session(self.engine) as session:
            return session.query(CompressServiceRecords).filter(CompressServiceRecords.host_name == self.host_name).all()
    @db_connect_retry()
    def set_service_finish_status(self, status: bool):
        with Session(self.engine) as session:
            record = session.query(ServiceStatusTable).filter(
                ServiceStatusTable.service_name == self.service_name
            ).first()
            if not record:
                record = ServiceStatusTable(service_name=self.service_name, is_finished=status)
                session.add(record)
            else:
                record.is_finished = status
            session.commit()
class CompressService:
    def __init__(self, max_worker: int = 2, service_name: str = "compress_service", engine: Engine | None = None, dependent_service_name: list[str]|None = None):
        self.service_orm_items = [CompressServiceRecords]
        self.dependent_service_name = dependent_service_name or ['hash_service']
        self.service_name = service_name
        self.logger = logging.getLogger(f'service.{self.service_name}')
        self.engine = engine or DbService().get_engine()
        self.repository = _ServiceRepository(self.service_name, self.engine, self.dependent_service_name)
        self.logger_queue = get_logger_queue()
        self.executor = ProcessPoolExecutor(max_worker, initializer=logger_configurer, initargs=(self.logger_queue,))
        self.status = ServiceStatus.INIT
        self._config = get_config()
        self.compress_desk_size = self._config.compress_desk_size
        self.reserve_size = 0
        
    

    def start(self):
        self.logger.info("Starting Compress Service")
        self.status = ServiceStatus.START
        try:
            self.clean_up()
            self.set_service_finish_status(False)
            self.process()
            self.analyze()
            self.set_service_finish_status(True)
            self.stop()
        except Exception as e:
            self.logger.error(f"Error occurred in {self.service_name}: {e}")
            self.shutdown()
        finally:
            self.set_service_finish_status(True)
    def process(self):
        ...
    
    def stop(self):
        self.logger.info("Stopping Compress Service")
        self.status = ServiceStatus.DONE

    
    def shutdown(self):
        self.logger.info("Shutting down Compress Service")
        self.status = ServiceStatus.FAIL

    
    def set_service_finish_status(self, status: bool):
        self.logger.info(f"Setting {self.service_name} service finish status to {status}")
        self.repository.set_service_finish_status(status)
    
    def set_dependent_service_record_status(self, status: Literal['waiting','processing','fail','done']):
        ...
    

    @staticmethod
    def worker():
        ...

    def check_dependent_service_finished(self) -> bool:
        ...

    def get_next_waiting_record(self):
        ...
    
    def reserve_space(self):
        ...
    
    def analyze(self):
        ...
    def clean_up(self):
        self.logger.info("Cleaning up unfinished zipfiles beacuse of the last time the service was not success end")
        qualified_path_list = [record.zip_file_path for record in self.repository.get_all_compress_service_records()]
        compress_temp_dir = Path(self._config.compress_temp_dir)
        local_file = [file.resolve().as_posix() for file in compress_temp_dir.iterdir()]
        need_clean_file = [file for file in local_file if file not in qualified_path_list]
        if not need_clean_file:
            self.logger.info("temp compress dir no need to clean")
        else:
            for file in need_clean_file:
                self.logger.info(f"temp compress dir file: {file} is not in qualified_path_list, deleting")
                Path(file).unlink()

class CompressServiceUtils:
    def campare_item(self, a, b):
        ...
    def trans_records_to_format_data(self, records):
        ...
    def trans_format_data_to_records(self, format_data):
        ...
    