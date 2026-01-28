from pydantic import BaseModel,field_validator
from sqlalchemy.orm import DeclarativeBase, mapped_column, Mapped, Session
from sqlalchemy import Engine, BigInteger, String, Integer, UniqueConstraint, MetaData, JSON
from sqlalchemy import exc

from pathlib import Path
from typing import Literal
from concurrent.futures import ThreadPoolExecutor, as_completed
import logging
import platform
import sys



from .utils import DbMixin, retry_for_class_method,ServiceStatusTable
from .db_service import DbService
from .config import get_config
from .domain import ServiceStatus

class ScanServiceError(Exception):
    """Scan Service Error"""

class ScanServiceDbError(ScanServiceError):
    """Scan Service Db Error"""

class ScanServiceFileError(ScanServiceError):
    """Scan Service File Error"""


class _FormatData(BaseModel):
    """Scan format data for a single object"""
    host_name: str
    object_path: str
    object_name: str
    object_type: Literal["file", "directory"]
    object_size: int
    object_item_count: int
    object_items: dict[str, int]
    status: Literal['waiting','processing','fail','done'] = 'waiting'

    @field_validator('object_path')
    def validate_object_path(cls, v):
        if not Path(v).exists():
            raise ValueError(f"Scan service Object path {v} not exist, please check")
        return v

class _Base(DeclarativeBase):
    metadata = MetaData()


class ScanRecords(DbMixin, _Base):
    __tablename__ = "scan_records"
    host_name: Mapped[str] = mapped_column(String(255))
    object_path: Mapped[str] = mapped_column(String(255))
    object_name: Mapped[str] = mapped_column(String(255))
    object_type: Mapped[Literal["file", "directory"]] = mapped_column(String(15))
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
            return session.query(ScanRecords).filter(ScanRecords.id == id).first()

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
        self.logger.info("Creating scan records table...")
        print("Creating scan records table...")
        ScanRecords.metadata.create_all(self.engine)
        self.logger.info("Scan records table created.")

    @db_connect_retry()
    def drop_record_table(self):
        self.logger.info("Dropping scan records table...")
        print("Dropping scan records table...")
        ScanRecords.metadata.drop_all(self.engine)
        self.logger.info("Scan records table dropped.")

    def reset_record_table(self):
        self.drop_record_table()
        self.create_record_table()

    @db_connect_retry()
    def set_service_status(self, status: bool):
        self.logger.info(f"Service status set to {status}")
        ServiceStatusTable.metadata.create_all(self.engine)
        with Session(self.engine) as session:
            # Upsert: update if exists, insert if not
            existing = session.query(ServiceStatusTable).filter(
                ServiceStatusTable.service_name == self.service_name
            ).first()
            if existing:
                existing.is_finished = status
                session.commit()
            else:
                session.add(ServiceStatusTable(service_name=self.service_name, is_finished=status))
                session.commit()



def _scan_file(file_path: Path, relative_path: Path, host_name: str, logger:logging.Logger) -> _FormatData:
    """Scan a single file and return its scan result"""
    items_path = file_path.relative_to(relative_path).as_posix()
    str_file_path = file_path.resolve().as_posix()
    logger.debug(f"Scanning file: {file_path}")
    return _FormatData(
        host_name=host_name,
        object_path=str_file_path,
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
    directory_path_str =directory_path.resolve().as_posix()
    for item in directory_path.rglob("*"):
        if item.is_file():
            item_path = item.relative_to(relative_path).as_posix()
            object_item_count += 1
            object_items[item_path] = item.stat().st_size
            object_size += item.stat().st_size

    return _FormatData(
        host_name=host_name,
        object_path=directory_path_str,
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
    def __init__(self, max_worker: int = 10):
        self.service_name = 'scan_service'
        self.repository = _ServiceRepository(self.service_name)
        self.host_name = platform.node()
        self.logger = logging.getLogger(f'service.{self.service_name}')
        temp_config = get_config()
        self.target_paths = [Path(path) for path in temp_config.source_path_list]
        self.executor = ThreadPoolExecutor(max_worker, thread_name_prefix='scan_service_thread')
        self.tasks = []
        self.status = ServiceStatus.INIT
        self.process_result = {
            'success': [],
            'fail': [],
            'target_path_not_exist': []
        }

    def start(self):
        self.status = ServiceStatus.START
        self._set_scan_service_status_unfinished()
        try:
            self.logger.info(f'{self.service_name} started')
            self.process()
            self.logger.info(f'{self.service_name} process finished')
            self.status = ServiceStatus.DONE
        except Exception as e:
            self.logger.error(f'{self.service_name} error: {e}')
            self.status = ServiceStatus.FAIL
        finally:
            self._set_scan_service_status_finished()
 

        
    
    def process(self):
        self.status = ServiceStatus.PROCESSING
        self.logger.info(f'{self.service_name} process_started')
        target_paths_count = len(self.target_paths)
        finished_count = 0
        with self.executor as executor:
            self.status = ServiceStatus.SUBMITTING
            for target_path in self.target_paths:
                if target_path.is_file():
                    self._process_file_target_path(target_path, finished_count, target_paths_count)
                elif target_path.is_dir():
                    self._process_directory_target_path(target_path, finished_count, target_paths_count)
                else:
                    self._process_invalid_target_path(target_path, finished_count, target_paths_count)
                finished_count += 1
            self.status = ServiceStatus.SUBMITTED
            for task in as_completed(self.tasks):
                result = task.result()
                if result['status']:
                    process_result = self._process_success_scan(result)
                else:
                    process_result = self._process_fail_scan(result)
                if process_result:
                    self.process_result['success'].append(result['object'])
                else:
                    self.process_result['fail'].append(result['object'])
        self.status = ServiceStatus.PROCESSED
    @staticmethod
    def worker(object_path: Path, host_name: str, logger:logging.Logger):
        logger.debug(f'Processing object: {object_path}')
        try:
            result = _scan_object(object_path, host_name, logger)
            return {'object':object_path, 'status':True,'result':result}
        except Exception as e:
            logger.error(f"Error scanning object {object_path}: {e}")
            return {'object':object_path, 'status':False,'result':None}

    def stop(self):
        self.logger.warning(f'{self.service_name} stop requested')
        self.executor.shutdown(wait=False, cancel_futures=True)
        sys.exit('scan_service_stop_requested')

        
    def shutdown(self):
        import os
        self.logger.warning(f'{self.service_name} shutdown requested')
        os._exit(1)  # Use os._exit to immediately terminate the process without running any cleanup code

    def _process_file_target_path(self, target_path: Path, finished_count: int, target_paths_count: int):
        self.logger.info(f'process {target_path},Total target paths: {target_paths_count}, finished count: {finished_count}')
        self.tasks.append(self.executor.submit(self.worker, target_path, self.host_name, self.logger))

    def _process_directory_target_path(self, target_path: Path, finished_count: int, target_paths_count: int):
        items = list(target_path.iterdir())
        self.logger.info(f'process {target_path},Total target paths: {target_paths_count}, items count: {len(items)}, finished count: {finished_count}, please waiting to processing...')
        for item in items:
            self.tasks.append(self.executor.submit(self.worker, item, self.host_name, self.logger))
    
    def _process_invalid_target_path(self, target_path: Path, finished_count: int, target_paths_count: int):
        self.logger.warning(f'Invalid target path: {target_path}, total target paths: {target_paths_count}, finished count: {finished_count}, skipped')
        self.process_result['target_path_not_exist'].append(target_path)

    def _process_success_scan(self, result):
        self.logger.debug(f"process scan successful: {result}")
        if not result['status']:
            raise ScanServiceError(f"Scan failed: {result} ,should never reach here")
        record = self.repository.get_scan_record_by_unique(host_name = self.host_name, object_path = result['object'].resolve().as_posix())
        if record:
            self.logger.debug(f"Scan record found: {record}")
            if not self._compare_scan_data(record, result):
                self.logger.critical(f"Scan data mismatch: {record} {result}")
                return False
            self.logger.info(f"scan record matched: scan_id:{record.id}-object_name:{record.object_name}")
            return True
        else:
            self.repository.add_scan_record(result['result'])
            self.logger.debug(f"Scan record added: {result}")
            return True
    def _process_fail_scan(self, result):
        self.logger.error(f"Scan failed: {result}")
        return False

    def _compare_scan_data(self, record, result):
        for key,value in result['result'].model_dump().items():
            if key == 'status':
                continue
            if value != getattr(record, key):
                return False
        return True

    def _set_scan_service_status_unfinished(self):
        self.repository.set_service_status(False)
        self.logger.info(f'{self.service_name} status set to unfinished')

    def _set_scan_service_status_finished(self):
        self.repository.set_service_status(True)
        self.logger.info(f'{self.service_name} status set to finished')

    def reset_scan_service_record(self):
        self.repository.reset_record_table()
