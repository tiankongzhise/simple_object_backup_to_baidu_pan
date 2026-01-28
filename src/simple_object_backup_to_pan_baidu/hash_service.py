import hashlib
from pydantic import BaseModel, Field,field_validator
from sqlalchemy.orm import DeclarativeBase, mapped_column, Mapped, Session
from sqlalchemy import Engine, BigInteger, String, Integer, UniqueConstraint, MetaData, JSON
from sqlalchemy import exc

from pathlib import Path
from typing import Literal,Union
from concurrent.futures import ProcessPoolExecutor, as_completed
import logging
import platform
import time

from .domain import ServiceStatus
from .utils import retry_for_class_method, get_service_table,get_auxiliary_table, get_auxiliary_format,logger_configurer
from .utils import ManualReviewFormat, ServiceStatusTable,DbMixin
from .db_service import DbService
from .logger_service import get_logger_queue
from .config import get_config
from .scan_service import ScanRecords

class HashServiceError(Exception):
    """Scan Service Error"""


class HashServiceDbError(HashServiceError):
    """Scan Service Db Error"""


class _FormatData(BaseModel):
    """Scan format data for a single object"""
    host_name: str
    object_path: str
    object_name: str
    object_type: Literal["file", "directory"]
    object_size: int
    object_item_count: int
    scan_id: int
    md5: str = Field(..., min_length=32, max_length=32,
                     description="md5 hash value")
    sha1: str = Field(..., min_length=40, max_length=40,
                      description="sha1 hash value")
    sha256: str = Field(..., min_length=64, max_length=64,
                        description="sha256 hash value")
    status: Literal['waiting', 'processing', 'fail', 'done'] = 'waiting'

    @field_validator("object_path")
    def validate_object_path(cls, v):
        if not Path(v).exists():
            raise ValueError(f"Object path {v} not exist,in hash service ,this case should not be happened")


class _Base(DeclarativeBase):
    metadata = MetaData()


class HashRecords(DbMixin, _Base):
    __tablename__ = "scan_records"
    host_name: Mapped[str] = mapped_column(String(255))
    object_path: Mapped[str] = mapped_column(String(255))
    object_name: Mapped[str] = mapped_column(String(255))
    object_type: Mapped[str] = mapped_column(String(15))
    object_size: Mapped[int] = mapped_column(BigInteger)
    object_item_count: Mapped[int] = mapped_column(Integer)
    scan_id: Mapped[int] = mapped_column(Integer)
    md5: Mapped[str] = mapped_column(String(32), nullable=False)
    sha1: Mapped[str] = mapped_column(String(40), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[Literal['waiting', 'processing', 'fail', 'done']
                   ] = mapped_column(String(15), default='waiting')
    __table_args__ = (
        UniqueConstraint('host_name', 'object_path',
                         name='uix_host_name_object_path'),
        UniqueConstraint('scan_id', name='uix_scan_id'),
        UniqueConstraint('md5', 'sha1', 'sha256', name='uix_md5_sha1_sha256'),
    )



def db_connect_retry(
    retries: int = 3,
    delay: float = 1.0,
    backoff: float = 1.0,
    exceptions: tuple[type[Exception]] = (exc.OperationalError,),
    logger_attr: str = "logger",
    raise_exception: type[Exception] = HashServiceDbError,
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
    def add_hash_record(self, data: _FormatData):
        with Session(self.engine) as session:
            record = self.get_hash_records_by_scan_id(data.scan_id)
            if not record:
                session.add(HashRecords(**data.model_dump()))
                session.commit()
            else:
                self.logger.warning(f"Hash record for {data.object_path},scan_id:{data.scan_id} already exists,compare data")
                self._compare_hash_records(record, data)
            

    @db_connect_retry()
    def get_hash_record_by_id(self, id: int):
        with Session(self.engine) as session:
            return session.get(HashRecords, id)

    @db_connect_retry()
    def get_hash_record_by_unique(self, host_name: str, object_path: str):
        with Session(self.engine) as session:
            return session.query(HashRecords).filter(
                HashRecords.host_name == host_name,
                HashRecords.object_path == object_path
            ).first()

    @db_connect_retry()
    def get_hash_records_by_scan_id(self, scan_id: int):
        with Session(self.engine) as session:
            return session.query(HashRecords).filter(HashRecords.scan_id == scan_id).first()

    @db_connect_retry()
    def get_dependent_services_status(self):
        with Session(self.engine) as session:
            return session.query(ServiceStatusTable).filter(
                ServiceStatusTable.service_name.in_(self.dependent_service_name)
            ).all()
    @db_connect_retry()
    def fetch_waiting_scan_record(self):
        table = get_service_table('scan_service')
        with Session(self.engine) as session:
            return session.query(table).filter(
                table.host_name == self.host_name,
                table.status == 'waiting'
            ).order_by(table.id.asc()).first()

    @db_connect_retry()
    def set_scan_record_status(self, id: int, status: Literal['waiting', 'processing', 'fail', 'done']):
        table = get_service_table('scan_service')
        with Session(self.engine) as session:
            session.query(table).filter(table.id == id).update({table.status: status})
            session.commit()
    @db_connect_retry()
    def add_manual_review_record(self, data: ManualReviewFormat):
        table = get_auxiliary_table('manual_review')
        with Session(self.engine) as session:
            record = session.query(table).filter(
                table.scan_id == data.scan_id,
            ).first()
            if not record:
                session.add(table(**data.model_dump()))
            else:
                for key,value in data.model_dump().items():
                    if key == 'reason':
                        if record.reason != value:
                            self.logger.warning(f"Manual review record for {data.object_path},scan_id:{data.scan_id} already exists with different reason {record.reason} != {value}")
                            record.reason = value
                            self.logger.warning(f"Manual review record for {data.object_path},scan_id:{data.scan_id} updated with different reason {record.reason} to {value}")
                    elif key == 'status':
                        continue
                    else:
                        if getattr(record, key) != value:
                            raise HashServiceError(f"Manual review record for {data.object_path},scan_id:{data.scan_id} already exists with different {key} {getattr(record, key)} != {value}")
            session.commit()

    def _compare_hash_records(self,hash_record: HashRecords,format_data: _FormatData):
        is_equal = True
        for key,value in format_data.model_dump().items():
            if key == 'status':
                continue
            if value != getattr(hash_record, key):
                self.logger.warning(f"Hash record for {format_data.object_path},scan_id:{format_data.scan_id} compare failed,db:{getattr(hash_record, key)} vs format_data:{value}")
                is_equal = False
        return is_equal
class HashCalculator:
    def __init__(self,logger:logging.Logger):
        self.logger = logger
        self.error_count = 0
    
    def fetch_hash_settings(self):
        temp_config = get_config()
        self.algorithm_list = temp_config.algorithm_list
        self.hash_chunk_size_bytes = temp_config.hash_chunk_size_bytes
        self.oversize = temp_config.oversize
        self.directory_overcount = temp_config.directory_overcount

    def run(self, scan_record: ScanRecords):
        check_result = self.pre_check(scan_record)
        if check_result:
            return check_result
        if scan_record.object_type == "file":
            return self.file_hash(scan_record)
        elif scan_record.object_type == "directory":
            return self.directory_hash(scan_record)
        else:
            raise HashServiceError(f"Unknown object type: {scan_record.object_type}")
    def pre_check(self, scan_record: ScanRecords):
        if scan_record.object_size > self.oversize:
            return self._scan_record_to_manual_review_format_data(
                scan_record, "oversize"
            )
        if (
            scan_record.object_type == "directory"
            and scan_record.object_item_count > self.directory_overcount
        ):
            return self._scan_record_to_manual_review_format_data(
                scan_record, "overcount"
            )
        if scan_record.object_size == 0:
            return self._scan_record_to_manual_review_format_data(
                scan_record, "empty"
            )
        if not Path(scan_record.object_path).exists():
            self.error_count += 1
            self.logger.warning(f"File not exists: {scan_record.object_path}, scan_id: {scan_record.id}, this case should not be happened")
            return self._scan_record_to_manual_review_format_data(
                scan_record, "path_not_exists"
            )
        return None

    def _hash_calculate_core(self, file_path: Path, algorithm: str):
        hash_obj = hashlib.new(algorithm)
        with open(file_path, "rb") as f:
            # 大文件分块读取，每块500MB，有效降低内存占用
            # 适用于处理几十GB的大型文件
            for chunk in iter(lambda: f.read(self.hash_chunk_size_bytes), b""):
                hash_obj.update(chunk)
        return hash_obj

    def file_hash(self, scan_record: ScanRecords):
        hash_result = {}
        file_path = Path(scan_record.object_path)
        if not file_path.exists():
            raise HashServiceError(f"File not found: {file_path}")
        for algorithm in self.algorithm_list:
            hash_result[algorithm] = (
                self._hash_calculate_core(file_path, algorithm).hexdigest().upper()
            )
        return self._scan_record_to_format_data(scan_record, hash_result)

    def directory_hash(self, scan_record: ScanRecords):
        hash_result = {}
        directory_path = Path(scan_record.object_path)
        if not directory_path.exists():
            raise HashServiceError(f"Directory not found: {scan_record.object_path}")
        sorted_file_list = sorted(
            [
                object_file
                for object_file in directory_path.rglob("*")
                if object_file.is_file()
            ],
        )
        for algorithm in self.algorithm_list:
            hash_obj = hashlib.new(algorithm)
            self.logger.info(
                f"Start hashing directory {directory_path} with algorithm {algorithm}, total file count: {len(sorted_file_list)}, please wait..."
            )
            for file_path in sorted_file_list:
                hash_obj.update(self._hash_calculate_core(file_path, algorithm).digest())
            hash_result[algorithm] = hash_obj.hexdigest().upper()
            self.logger.info(
                f"Finish hashing directory {directory_path} with algorithm {algorithm}, hash value: {hash_result[algorithm]}"
            )
        return self._scan_record_to_format_data(scan_record, hash_result)
    def _scan_record_to_manual_review_format_data(self, scan_record: ScanRecords, reason: str):
        return ManualReviewFormat(
            host_name=scan_record.host_name,
            object_path=scan_record.object_path,
            object_name=scan_record.object_name,
            object_type=scan_record.object_type,
            object_size=scan_record.object_size,
            object_item_count=scan_record.object_item_count,
            scan_id=scan_record.id,
            reason=reason,
        )
    def _scan_record_to_format_data(self, scan_record: ScanRecords, hash_result: dict):
        
        return _FormatData(
            host_name=scan_record.host_name,
            object_path=scan_record.object_path,
            object_name=scan_record.object_name,
            object_type=scan_record.object_type,
            object_size=scan_record.object_size,
            object_item_count=scan_record.object_item_count,
            scan_id=scan_record.id,
            md5=hash_result["md5"],
            sha1=hash_result["sha1"],
            sha256=hash_result["sha256"],
        )

class HashService:
    def __init__(self, service_name: str = 'hash_service', engine: Engine | None = None, dependent_service_name: list[str]|None = None):

        self.dependent_service_name = dependent_service_name or ['scan_service']
        self.repository = _ServiceRepository(service_name, engine, dependent_service_name)
        self.logger = logging.getLogger(f'service.{service_name}')
        self.service_name = service_name
        self.engine = engine or DbService().get_engine()
        self.status = ServiceStatus.INIT
        logger_queue = get_logger_queue()
        self.executor = ProcessPoolExecutor(4, initializer=logger_configurer, initargs=(logger_queue,))
        self.tasks= []

    def start(self):
        try:
            self.status = ServiceStatus.START
            self.logger.info(f"Starting {self.service_name}...")
            self.process()
            self.analyze()
            self.stop()
        except Exception as e:
            self.logger.error(f"Error occurred in {self.service_name}: {e}")
            self.shutdown()
    
    def process(self):
        self.status = ServiceStatus.PROCESSING
        self.logger.info(f"Processing {self.service_name}...")
        with self.executor as executor:
            while True:
                record = self._get_next_waiting_record()
                dependent_service_finished = self._check_dependent_service_finished()
                if not record and dependent_service_finished:
                    break
                if not record:
                    self.logger.info("No waiting record found, please wait dependent service to create...,will recheck after 1 second")
                    time.sleep(1)
                else:
                    task = executor.submit(self.worker, self.service_name, record)
                    task.add_done_callback(self._process_worker_result)
                    self.tasks.append(task)
        self.status = ServiceStatus.PROCESSED
    @staticmethod
    def worker(service_name:str,record: ScanRecords):
        logger = logging.getLogger(f'service.{service_name}.worker')
        calculator = HashCalculator(logger)
        result = calculator.run(record)
        logger.info(f"scan record {record.id},record name:{record.object_name} hash result: {result}")
        return result
    
    def stop(self):
        self.logger.info(f"Stopping {self.service_name}...")
        self.status = ServiceStatus.DONE

    def shutdown(self):
        self.logger.info(f"Shutting down {self.service_name}...")
        self.status = ServiceStatus.FAIL

    def _check_dependent_service_finished(self) -> bool:
        records = self.repository.get_dependent_services_status()
        if not records:
            raise HashServiceError(f"Dependent service not found: {self.dependent_service_name}")
        for record in records:
            if not record.is_finished:
                return False
        return True
    def _get_next_waiting_record(self):
        return self.repository.fetch_waiting_scan_record()

    def _process_worker_result(self,task_future):
        result = task_future.result()
        match result:
            case _FormatData():
                self.logger.info(f"{self.service_name} processing worker result:{result.scan_id}_{result.object_name} to Hash Records...")
                self.repository.add_hash_record(result)
                self.logger.info(f"{self.service_name} processing worker result:{result.scan_id}_{result.object_name} to Hash Records...done")
            case ManualReviewFormat():
                self.logger.info(f"{self.service_name} processing worker result:{result.scan_id}_{result.object_name} to Manual Review...")
                self.repository.add_manual_review_record(result)
                self.logger.info(f"{self.service_name} processing worker result:{result.scan_id}_{result.object_name} to Manual Review...done")
    def analyze(self):
        self.logger.info(f"Analyzing {self.service_name} result...")
        success = 0
        manual_review = 0
        for task in as_completed(self.tasks):
            result = task.result()
            if isinstance(result, _FormatData):
                success += 1
            elif isinstance(result, ManualReviewFormat):
                manual_review += 1
        self.logger.info(f"{self.service_name} analyze result: success={success}, manual_review={manual_review}")
