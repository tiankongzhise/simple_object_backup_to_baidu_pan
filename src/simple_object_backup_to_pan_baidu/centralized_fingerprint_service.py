import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import String, BigInteger, Integer, MetaData, UniqueConstraint, Index
import platform
from typing import Literal
import hashlib
from .config import get_config
from .domain import ServiceStatus
from .db_service import DbService
from .utils import DbMixin,ManualReviewRecords,ManReviewFormat

class CentralizedFingerprintServiceError(Exception):
    pass

class _Base(DeclarativeBase):
    metadata = MetaData()

class CentralizedFingerprintRecords(DbMixin, _Base):
    __tablename__ = "centralized_fingerprint_records"
    host_name: Mapped[str] = mapped_column(String(255))
    object_path: Mapped[str] = mapped_column(String(255))
    object_name: Mapped[str] = mapped_column(String(255))
    object_type: Mapped[Literal["file", "directory"]] = mapped_column(String(15))
    object_size: Mapped[int] = mapped_column(BigInteger)
    object_item_count: Mapped[int] = mapped_column(Integer)
    fingerprint: Mapped[str] = mapped_column(String(255))
    md5: Mapped[str] = mapped_column(String(32))
    sha1: Mapped[str] = mapped_column(String(40))
    sha256: Mapped[str] = mapped_column(String(64))
    status: Mapped[Literal['waiting','processing','fail','done']] = mapped_column(String(15), default='waiting')
    __table_args__ = (
        UniqueConstraint('host_name', 'object_path', name='uix_host_name_object_path'),
        Index('idx_fingerprint', 'fingerprint'),
        UniqueConstraint('md5', 'sha1', 'sha256', name='uix_md5_sha1_sha256'),
    )

class FingerprintCacheRecords(DbMixin,_Base):
    __tablename__ = 'fingerprint_cache_records'
    fingerprint: Mapped[str] = mapped_column(String(255))
    __table_args__ = (
        UniqueConstraint('fingerprint', name='uix_fingerprint'),
    )

class DuplicateFingerprintRecords(DbMixin, _Base):
    __tablename__ = "duplicate_fingerprint_records"
    host_name: Mapped[str] = mapped_column(String(255))
    object_path: Mapped[str] = mapped_column(String(255))
    object_name: Mapped[str] = mapped_column(String(255))
    object_type: Mapped[Literal["file", "directory"]] = mapped_column(String(15))
    object_size: Mapped[int] = mapped_column(BigInteger)
    object_item_count: Mapped[int] = mapped_column(Integer)
    fingerprint_id: Mapped[int] = mapped_column(Integer)
    md5: Mapped[str] = mapped_column(String(32))
    sha1: Mapped[str] = mapped_column(String(40))
    sha256: Mapped[str] = mapped_column(String(64))
    status: Mapped[Literal['waiting','processing','fail','done']] = mapped_column(String(15), default='waiting')
    __table_args__ = (UniqueConstraint('host_name', 'object_path', name='uix_host_name_object_path'),)



class HashCalculateCore(object):
    def __init__(self):
        self.host_name = platform.node()    
        self.logger = logging.getLogger(f'service.centralized_fingerprint_service.hash_calculate_core')
        self._config = get_config()
        self.algorithm_list = self._config.algorithm_list
        self.hash_chunk_size_bytes = self._config.hash_chunk_size_bytes
        self.fingerprint_check_size = self._config.fingerprint_check_size
        self.fingerprint_check_algorithm = self._config.fingerprint_check_algorithm
    
    def calculate_fingerprint(self, file_path: Path|str):
        if isinstance(file_path, str):
            file_path = Path(file_path)
        if file_path.is_file():
            return self._calculate_file_fingerprint(file_path)
        elif file_path.is_dir():
            return self._calculate_directory_fingerprint(file_path)
        else:
            raise CentralizedFingerprintServiceError(f'Invalid file path: {file_path}')
    def _calculate_file_fingerprint(self, file_path: Path):
        return self._caculate_fingerprint_core(file_path).hexdigest().upper()

    def _calculate_directory_fingerprint(self, directory_path: Path):
        hash_obj = hashlib.new(self.fingerprint_check_algorithm)
        file_list = sorted([file_path for file_path in directory_path.rglob('*') if file_path.is_file()])
        for file_path in file_list:
            hash_obj.update(self._caculate_fingerprint_core(file_path).digest())
        return hash_obj.hexdigest().upper()

    def _caculate_fingerprint_core(self, file_path: Path):
        hash_obj = hashlib.new(self.fingerprint_check_algorithm)
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(self.fingerprint_check_size), b''):
                hash_obj.update(chunk)
        return hash_obj
    def _calculate_full_hash_pre_check(self, file_path: Path|str):
        if isinstance(file_path, str):
            file_path = Path(file_path)
        if not file_path.exists():
            raise CentralizedFingerprintServiceError(f'File not exists: {file_path}')
        if file_path.stat().st_size == 0:
            return ManReviewFormat(
                host_name=self.host_name,
                object_path=file_path.resolve().as_posix(),
                object_name=file_path.name,
                object_type='file' if file_path.is_file() else 'directory',
                object_size=0,
                object_item_count=0,
                reason='empty'
            )
        if file_path.is_file():
            file_size = file_path.stat().st_size
            if file_size > self._config.oversize:
                return ManReviewFormat(
                    host_name=self.host_name,
                    object_path=file_path.resolve().as_posix(),
                    object_name=file_path.name,
                    object_type='file',
                    object_size=file_size,
                    object_item_count=1,
                    reason='oversize'
                )
                
        elif file_path.is_dir():
            file_list = [file_path.stat().st_size for file_path in file_path.rglob('*') if file_path.is_file()]
            file_item_count = len(file_list)
            if file_item_count > self._config.directory_overcount:
                return ManReviewFormat(
                    host_name=self.host_name,
                    object_path=file_path.resolve().as_posix(),
                    object_name=file_path.name,
                    object_type='directory',
                    object_size=sum(file_list),
                    object_item_count=file_item_count,
                    reason='overcount'
                )
            if sum(file_list) > self._config.oversize:
                return ManReviewFormat(
                    host_name=self.host_name,
                    object_path=file_path.resolve().as_posix(),
                    object_name=file_path.name,
                    object_type='directory',
                    object_size=sum(file_list),
                    object_item_count=file_item_count,
                    reason='oversize'
                )
        return True
    def _calculate_full_hash_core(self, file_path: Path,algorithm: str):
        hash_obj = hashlib.new(algorithm)
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(self.hash_chunk_size_bytes), b''):
                hash_obj.update(chunk)
        return hash_obj
    def _calculate_file_full_hash(self, file_path: Path|str):
        hash_result = {}
        for algorithm in self.algorithm_list:
            hash_result[algorithm] = self._calculate_full_hash_core(file_path, algorithm).hexdigest().upper()
        return hash_result
    def _calculate_directory_full_hash(self, directory_path: Path|str):
        hash_result = {}
        file_list = sorted([file_path for file_path in directory_path.rglob('*') if file_path.is_file()])   
        for algorithm in self.algorithm_list:
            hash_obj = hashlib.new(algorithm)
            for file_path in file_list:
                hash_obj.update(self._calculate_full_hash_core(file_path, algorithm).digest())
            hash_result[algorithm] = hash_obj.hexdigest().upper()
        return hash_result

    def calculate_full_hash(self, file_path: Path|str):
        if isinstance(file_path, str):
            file_path = Path(file_path)
        pre_check_result = self._calculate_full_hash_pre_check(file_path)
        if pre_check_result is not True:
            return pre_check_result
        if file_path.is_file():
            return self._calculate_file_full_hash(file_path)
        else: # file_path.is_dir()
            return self._calculate_directory_full_hash(file_path)
 
        

class CentralizedFingerprintService(object):
    def __init__(self):
        self.service_name = 'centralized_fingerprint_service'
        self.logger = logging.getLogger(f'service.{self.service_name}')
        self.status = ServiceStatus.INIT
        self.engine = DbService().get_engine()
        self._config = get_config()
        self._executor = ThreadPoolExecutor(max_workers=10)
        self._tasks = []
        self._service_orm_items = [CentralizedFingerprintRecords]


    def process(self):
        self.status = ServiceStatus.PROCESSING
        self.logger.info(f'Processing {self.service_name}...')
        
    
    def start(self):
        self.status = ServiceStatus.START
        self.logger.info(f'Starting {self.service_name}...')
        self.process()
        self.analyze()
        self.stop()
    
    def stop(self):
        self.status = ServiceStatus.STOP
        self.logger.info(f'Stopping {self.service_name}...')
    
    def analyze(self):
        ...
