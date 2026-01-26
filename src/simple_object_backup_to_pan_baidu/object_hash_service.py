from typing import Literal
from sqlalchemy.orm import Session, DeclarativeBase, mapped_column, Mapped
from sqlalchemy import (
    Integer,
    String,
    MetaData,
    BigInteger,
    Engine,
    exc,
    UniqueConstraint,
    Index,
    Boolean,
)
from concurrent.futures import ProcessPoolExecutor
from pydantic import BaseModel, Field
import logging
from pathlib import Path
import hashlib
import platform
import os
import time
from .db_service import DbService
from .scan_service import ScanTable
from .utils import DbMixin, retry_decorator, ServiceStatusTable, logger_configurer
from .config import get_config, get_logger_queue


class ObjectHashServiceError(Exception):
    """Base class for Object Hash Service errors."""


class ObjectHashError(ObjectHashServiceError):
    """Base class for Object Hash errors."""


class ObjectHashRepositoryError(ObjectHashServiceError):
    """Base class for Object Hash Repository errors."""


class ObjectHashDbOperationlError(ObjectHashRepositoryError):
    """Base class for Object Hash Database Operation errors."""


class ObjectHashDbIntegrityError(ObjectHashDbOperationlError):
    """Base class for Object Hash Database Integrity errors."""


class HashResult(BaseModel):
    host_name: str
    object_path: str
    object_type: Literal["file", "directory"]
    object_size: int
    object_item_count: int
    scan_id: int
    md5: str = Field(..., min_length=32, max_length=32, description="md5 hash value")
    sha1: str = Field(..., min_length=40, max_length=40, description="sha1 hash value")
    sha256: str = Field(
        ..., min_length=64, max_length=64, description="sha256 hash value"
    )


class ManualReviewObject(BaseModel):
    host_name: str
    object_path: str
    object_type: Literal["file", "directory"]
    object_size: int
    object_item_count: int
    scan_id: int
    reason: Literal["oversize", "overcount", "empty"] = Field(
        ..., description="manual review reason"
    )


class HashBase(DeclarativeBase):
    metadata = MetaData()


class ObjectHashTable(DbMixin, HashBase):
    __tablename__ = "object_hash"
    host_name: Mapped[str] = mapped_column(String(255), nullable=False)
    object_path: Mapped[str] = mapped_column(String(255), nullable=False)
    object_type: Mapped[Literal["file", "directory"]] = mapped_column(
        String(10), nullable=False
    )
    object_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    object_item_count: Mapped[int] = mapped_column(Integer, nullable=False)
    scan_id: Mapped[int] = mapped_column(Integer, nullable=False)
    md5: Mapped[str] = mapped_column(String(32), nullable=False)
    sha1: Mapped[str] = mapped_column(String(40), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    is_processed: Mapped[bool] = mapped_column(Boolean, default=False)

    __table_args__ = (
        UniqueConstraint("host_name", "object_path", name="uix_host_name_object_path"),
        UniqueConstraint("scan_id", name="uix_scan_id"),
        Index(
            "idx_md5_sha1_sha256", "md5", "sha1", "sha256",
        ),
    )


class ManualReviewObjectTable(DbMixin, HashBase):
    __tablename__ = "manual_review_object"
    host_name: Mapped[str] = mapped_column(String(255), nullable=False)
    object_path: Mapped[str] = mapped_column(String(255), nullable=False)
    object_type: Mapped[Literal["file", "directory"]] = mapped_column(
        String(10), nullable=False
    )
    object_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    object_item_count: Mapped[int] = mapped_column(Integer, nullable=False)
    scan_id: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[Literal["oversize", "overcount", "empty"]] = mapped_column(
        String(10), nullable=False
    )
    __table_args__ = (
        UniqueConstraint("host_name", "object_path", name="uix_host_name_object_path"),
        UniqueConstraint("scan_id", name="uix_scan_id"),
    )


class FormatTransformer:
    @staticmethod
    def scan_record_to_manual_review_object(scan_record: ScanTable, reason: str):
        return ManualReviewObject(
            host_name=scan_record.host_name,
            object_path=scan_record.object_path,
            object_type=scan_record.object_type,
            object_size=scan_record.object_size,
            object_item_count=scan_record.object_item_count,
            scan_id=scan_record.id,
            reason=reason,
        )

    @staticmethod
    def scan_record_to_hash_result(scan_record: ScanTable, hash_dict: dict):
        return HashResult(
            host_name=scan_record.host_name,
            object_path=scan_record.object_path,
            object_type=scan_record.object_type,
            object_size=scan_record.object_size,
            object_item_count=scan_record.object_item_count,
            scan_id=scan_record.id,
            md5=hash_dict["md5"],
            sha1=hash_dict["sha1"],
            sha256=hash_dict["sha256"],
        )

    @staticmethod
    def hash_result_to_db_record(hash_result: HashResult):
        return ObjectHashTable(
            host_name=hash_result.host_name,
            object_path=hash_result.object_path,
            object_type=hash_result.object_type,
            object_size=hash_result.object_size,
            object_item_count=hash_result.object_item_count,
            scan_id=hash_result.scan_id,
            md5=hash_result.md5,
            sha1=hash_result.sha1,
            sha256=hash_result.sha256,
        )

    @staticmethod
    def manual_review_object_to_db_record(manual_review_object: ManualReviewObject):
        return ManualReviewObjectTable(
            host_name=manual_review_object.host_name,
            object_path=manual_review_object.object_path,
            object_type=manual_review_object.object_type,
            object_size=manual_review_object.object_size,
            object_item_count=manual_review_object.object_item_count,
            scan_id=manual_review_object.scan_id,
            reason=manual_review_object.reason,
        )


class ObjectHash:
    def __init__(self, host_name: str, logger: logging.Logger):
        self._host_name = host_name
        self._logger = logger
        self._config = get_config()
        self._algorithm_list = self._config.algorithm_list
        self._hash_chunk_size_bytes = self._config.hash_chunk_size_bytes

    def pre_check(self, scan_record: ScanTable):
        if scan_record.object_size > self._config.oversize:
            return FormatTransformer.scan_record_to_manual_review_object(
                scan_record, "oversize"
            )
        if (
            scan_record.object_type == "directory"
            and scan_record.object_item_count > self._config.directory_overcount
        ):
            return FormatTransformer.scan_record_to_manual_review_object(
                scan_record, "overcount"
            )
        if scan_record.object_size == 0:
            return FormatTransformer.scan_record_to_manual_review_object(
                scan_record, "empty"
            )
        return None

    def hash_file(self, scan_record: ScanTable) -> HashResult:
        hash_result = {}
        file_path = Path(scan_record.object_path)
        if not file_path.exists():
            raise ObjectHashError(f"File not found: {scan_record.object_path}")
        for algorithm in self._algorithm_list:
            hash_result[algorithm] = (
                self._hash_core(file_path, algorithm).hexdigest().upper()
            )
        return FormatTransformer.scan_record_to_hash_result(scan_record, hash_result)

    def hash_directory(self, scan_record: ScanTable) -> HashResult:
        hash_result = {}
        directory_path = Path(scan_record.object_path)
        if not directory_path.exists():
            raise ObjectHashError(f"Directory not found: {scan_record.object_path}")
        sorted_file_list = sorted(
            [
                object_file
                for object_file in directory_path.rglob("*")
                if object_file.is_file()
            ],
        )
        for algorithm in self._algorithm_list:
            hash_obj = hashlib.new(algorithm)
            self._logger.info(
                f"Start hashing directory {directory_path} with algorithm {algorithm}, total file count: {len(sorted_file_list)}, please wait..."
            )
            for file_path in sorted_file_list:
                hash_obj.update(self._hash_core(file_path, algorithm).digest())
            hash_result[algorithm] = hash_obj.hexdigest().upper()
            self._logger.info(
                f"Finish hashing directory {directory_path} with algorithm {algorithm}, hash value: {hash_result[algorithm]}"
            )
        return FormatTransformer.scan_record_to_hash_result(scan_record, hash_result)

    def _hash_core(self, file_path: Path, algorithm: str):
        hash_obj = hashlib.new(algorithm)
        with open(file_path, "rb") as f:
            # 大文件分块读取，每块500MB，有效降低内存占用
            # 适用于处理几十GB的大型文件
            for chunk in iter(lambda: f.read(self._hash_chunk_size_bytes), b""):
                hash_obj.update(chunk)
        return hash_obj

    def hash_object(self, scan_record: ScanTable):
        check_result = self.pre_check(scan_record)
        if check_result:
            return check_result
        if scan_record.object_type == "file":
            return self.hash_file(scan_record)
        elif scan_record.object_type == "directory":
            return self.hash_directory(scan_record)
        else:
            raise ObjectHashError(f"Unknown object type: {scan_record.object_type}")


class HashRepository:
    def __init__(self, db_engine: Engine, logger: logging.Logger):
        self._db_engine = db_engine
        self._logger = logger

    @retry_decorator(
        retries=3, delay=1, backoff=2, exceptions=(ObjectHashDbOperationlError,)
    )
    def create_table(self):
        """Create table ObjectHashTable if not exists."""
        self._logger.debug("Create table ObjectHashTable if not exists")
        try:
            ObjectHashTable.metadata.create_all(bind=self._db_engine)
        except exc.OperationalError as e:
            self._logger.error(f"Create table ObjectHashTable failed: {e}")
            raise ObjectHashDbOperationlError(
                f"Create table ObjectHashTable failed: {e}"
            ) from e
        except Exception as e:
            self._logger.error(f"Create table ObjectHashTable failed: {e}")
            raise ObjectHashRepositoryError(
                f"Create table ObjectHashTable failed: {e}"
            ) from e
        self._logger.debug("Create table ObjectHashTable success")

    @retry_decorator(
        retries=3, delay=1, backoff=2, exceptions=(ObjectHashDbOperationlError,)
    )
    def drop_table(self):
        """Drop table ObjectHashTable if exists."""
        self._logger.debug("Drop table ObjectHashTable if exists")
        try:
            ObjectHashTable.metadata.drop_all(bind=self._db_engine)
        except exc.OperationalError as e:
            self._logger.error(f"Drop table ObjectHashTable failed: {e}")
            raise ObjectHashDbOperationlError(
                f"Drop table ObjectHashTable failed: {e}"
            ) from e
        except Exception as e:
            self._logger.error(f"Drop table ObjectHashTable failed: {e}")
            raise ObjectHashRepositoryError(
                f"Drop table ObjectHashTable failed: {e}"
            ) from e
        self._logger.debug("Drop table ObjectHashTable success")

    def reset_table(self):
        """Reset table ObjectHashTable, drop and create."""
        self._logger.debug("Reset table ObjectHashTable")
        self.drop_table()
        self.create_table()
        self._logger.debug("Reset table ObjectHashTable success")

    @retry_decorator(
        retries=3, delay=1, backoff=2, exceptions=(ObjectHashDbOperationlError,)
    )
    def query_scan_record(self):
        """Query scan record by id."""
        self._logger.debug("Query scan record")
        try:
            with Session(self._db_engine) as session:
                scan_record = (
                    session.query(ScanTable)
                    .filter_by(is_hashed=False)
                    .order_by(ScanTable.id.asc())
                    .first()
                )
                return scan_record
        except exc.OperationalError as e:
            self._logger.error(f"Query scan record failed: {e}")
            raise ObjectHashDbOperationlError(f"Query scan record failed: {e}") from e
        except Exception as e:
            self._logger.error(f"Query scan record failed: {e}")
            raise ObjectHashRepositoryError(f"Query scan record failed: {e}") from e
    @retry_decorator(
        retries=3, delay=1, backoff=2, exceptions=(ObjectHashDbOperationlError,)
    )
    def query_scan_service_status(self):
        """Query scan service status."""
        self._logger.debug("Query scan service status")
        try:
            with Session(self._db_engine) as session:
                scan_service_status = (
                    session.query(ServiceStatusTable)
                    .filter_by(service_name="scan_service")
                    .first()
                )
                return scan_service_status
        except exc.OperationalError as e:
            self._logger.error(f"Query scan service status failed: {e}")
            raise ObjectHashDbOperationlError(f"Query scan service status failed: {e}") from e
        except Exception as e:
            self._logger.error(f"Query scan service status failed: {e}")
            raise ObjectHashRepositoryError(f"Query scan service status failed: {e}") from e

    @retry_decorator(
        retries=3, delay=1, backoff=2, exceptions=(ObjectHashDbOperationlError,)
    )
    def query_hash_record_by_path(self, host_name: str, object_path: str):
        """Query hash record by host name and object path."""
        self._logger.debug(
            f"Query hash record by host name: {host_name}, object path: {object_path}"
        )
        try:
            with Session(self._db_engine) as session:
                hash_record = (
                    session.query(ObjectHashTable)
                    .filter_by(host_name=host_name, object_path=object_path)
                    .first()
                )
                return hash_record
        except exc.OperationalError as e:
            self._logger.error(f"Query hash record failed: {e}")
            raise ObjectHashDbOperationlError(f"Query hash record failed: {e}") from e
        except Exception as e:
            self._logger.error(f"Query hash record failed: {e}")
            raise ObjectHashRepositoryError(f"Query hash record failed: {e}") from e

    @retry_decorator(
        retries=3, delay=1, backoff=2, exceptions=(ObjectHashDbOperationlError,)
    )
    def query_hash_record_by_scan_id(self, scan_id: int):
        """Query hash record by scan id."""
        self._logger.debug(f"Query hash record by scan id: {scan_id}")
        try:
            with Session(self._db_engine) as session:
                hash_record = (
                    session.query(ObjectHashTable).filter_by(scan_id=scan_id).first()
                )
                return hash_record
        except exc.OperationalError as e:
            self._logger.error(f"Query hash record failed: {e}")
            raise ObjectHashDbOperationlError(f"Query hash record failed: {e}") from e
        except Exception as e:
            self._logger.error(f"Query hash record failed: {e}")
            raise ObjectHashRepositoryError(f"Query hash record failed: {e}") from e

    @retry_decorator(
        retries=3, delay=1, backoff=2, exceptions=(ObjectHashDbOperationlError,)
    )
    def insert_hash_record(self, hash_record: ObjectHashTable):
        """Insert hash record."""
        self._logger.debug(f"Insert hash record: {hash_record}")
        try:
            with Session(self._db_engine) as session:
                session.add(hash_record)
                session.commit()
        except exc.OperationalError as e:
            self._logger.error(f"Insert hash record failed: {e}")
            raise ObjectHashDbOperationlError(f"Insert hash record failed: {e}") from e
        except exc.IntegrityError as e:
            db_record = self.query_hash_record_by_scan_id(hash_record.scan_id)
            if db_record:
                for key, value in db_record.__table__.columns.items():
                    if key == "id" or key == "is_processed":
                        continue
                    if getattr(hash_record, key) != value:
                        self._logger.error(
                            f"Hash record {key} value is not equal db: {value},hash_record: {hash_record},db_record: {db_record}"
                        )
                        raise ObjectHashRepositoryError(
                            f"Hash record {key} value is not equal db: {value},hash_record: {hash_record},db_record: {db_record}"
                        )
                self._logger.info(f"Hash record already exists: {db_record}")
            else:
                self._logger.error(f"Insert hash record failed: {e}")
                raise ObjectHashRepositoryError(
                    f"Insert hash record failed: {e}"
                ) from e
        except Exception as e:
            self._logger.error(f"Insert hash record failed: {e}")
            raise ObjectHashRepositoryError(f"Insert hash record failed: {e}") from e

    @retry_decorator(
        retries=3, delay=1, backoff=2, exceptions=(ObjectHashDbOperationlError,)
    )
    def query_manual_review_record_by_scan_id(self, scan_id: int):
        """Query manual review record by scan id."""
        self._logger.debug(f"Query manual review record by scan id: {scan_id}")
        try:
            with Session(self._db_engine) as session:
                manual_review_record = (
                    session.query(ManualReviewObjectTable)
                    .filter_by(scan_id=scan_id)
                    .first()
                )
                return manual_review_record
        except exc.OperationalError as e:
            self._logger.error(
                f"Query manual review record failed: {e} beause db is not connected"
            )
            raise ObjectHashDbOperationlError(
                f"Query manual review record failed: {e}"
            ) from e
        except Exception as e:
            self._logger.error(f"Query manual review record failed: {e}")
            raise ObjectHashRepositoryError(
                f"Query manual review record failed: {e}"
            ) from e

    @retry_decorator(
        retries=3, delay=1, backoff=2, exceptions=(ObjectHashDbOperationlError,)
    )
    def insert_manual_review_record(
        self, manual_review_record: ManualReviewObjectTable
    ):
        """Insert manual review record."""
        self._logger.debug(f"Insert manual review record: {manual_review_record}")
        try:
            with Session(self._db_engine) as session:
                session.add(manual_review_record)
                session.commit()
        except exc.OperationalError as e:
            self._logger.error(f"Insert manual review record failed: {e}")
            raise ObjectHashDbOperationlError(
                f"Insert manual review record failed: {e}"
            ) from e
        except exc.IntegrityError as e:
            db_record = self.query_manual_review_record_by_scan_id(
                manual_review_record.scan_id
            )
            if db_record:
                for key, value in db_record.__table__.columns.items():
                    if key == "id" or key == "is_processed":
                        continue
                    if getattr(manual_review_record, key) != value:
                        self._logger.error(
                            f"Manual review record {key} value is not equal db: {value},manual_review_record: {manual_review_record},db_record: {db_record}"
                        )
                        raise ObjectHashDbIntegrityError(
                            f"Manual review record {key} value is not equal db: {value},manual_review_record: {manual_review_record},db_record: {db_record}"
                        )
        except Exception as e:
            self._logger.error(f"Insert manual review record failed: {e}")
            raise ObjectHashRepositoryError(
                f"Insert manual review record failed: {e}"
            ) from e


class HashStatusManger:
    def __init__(self, db_engine: Engine, logger: logging.Logger):
        self._db_engine = db_engine
        self._logger = logger

    @retry_decorator(
        retries=3, delay=1, backoff=2, exceptions=(ObjectHashDbOperationlError,)
    )
    def query_finish_status(self) -> ServiceStatusTable|None:
        """Query finish status by scan id."""
        self._logger.debug("Query object hash service finish status")
        try:
            with Session(self._db_engine) as session:
                return (
                    session.query(ServiceStatusTable)
                    .filter_by(service_name="object_hash_service")
                    .first()
                )
        except exc.OperationalError as e:
            self._logger.error(
                f"Query object hash service finish status failed: {e} beause db is not connected"
            )
            raise ObjectHashDbOperationlError(
                f"Query object hash service finish status failed: {e}"
            ) from e
        except Exception as e:
            self._logger.error(f"Query object hash service finish status failed: {e}")
            raise ObjectHashRepositoryError(
                f"Query object hash service finish status failed: {e}"
            ) from e

    def set_finish_status(self, finish_status: bool):
        """Set finish status by scan id."""
        self._logger.debug(f"Set object hash service finish status: {finish_status}")
        try:
            with Session(self._db_engine) as session:
                status_finished = self.query_finish_status()
                if status_finished:
                    status_finished.is_finished = finish_status
                else:
                    status_finished = ServiceStatusTable(
                        service_name="object_hash_service", is_finished=finish_status
                    )
                    session.add(status_finished)
                session.commit()
        except exc.OperationalError as e:
            self._logger.error(
                f"Set object hash service finish status failed: {e} beause db is not connected"
            )
            raise ObjectHashDbOperationlError(
                f"Set object hash service finish status failed: {e}"
            ) from e
        except Exception as e:
            self._logger.error(f"Set object hash service finish status failed: {e}")
            raise ObjectHashRepositoryError(
                f"Set object hash service finish status failed: {e}"
            ) from e


class ObjectHashService:
    def __init__(self):
        self.set_logger()
        self._db_engine = DbService().get_engine()
        self._hash_status_manger = HashStatusManger(self._db_engine, self._logger)
        self._object_hash_repository = HashRepository(self._db_engine, self._logger)
        self._host_name = platform.node()
        self._hash_core = ObjectHash(self._host_name, self._logger)
        self._executor = ProcessPoolExecutor(max_workers=2)
    def set_logger(self):
        self._logger = logging.getLogger("object_hash_service")
        self._logger_queue = get_logger_queue()
        self._logger_configurer = logger_configurer
        self._logger_configurer(self._logger_queue)



    def work(self,scan_record:ScanTable):
        """Work object hash service."""
        try:
            self._logger.debug("Start object hash service")
            self._logger_configurer(self._logger_queue)
            self._logger.debug("Query scan record")
            self._logger.debug(f"Query scan record: {scan_record}")
            self._logger.debug("Start hash object")
            result = self._hash_core.hash_object(scan_record)
            self._logger.debug(f"Hash object result: {result}")
            if isinstance(result, ManualReviewObject):
                self._logger.debug(f"insert Manual review object: {result}")
                db_data = FormatTransformer.manual_review_object_to_db_record(result)
                self._object_hash_repository.insert_manual_review_record(db_data)
                self._logger.debug(f"insert {result} success")
            elif isinstance(result, HashResult):
                self._logger.debug(f"insert HashResult object: {result}")
                db_data = FormatTransformer.hash_result_to_db_record(result)
                self._object_hash_repository.insert_hash_record(db_data)
                self._logger.debug(f"insert {result} success")
            else:
                self._logger.error(f"Unknown hash result type: {result}")
                raise ObjectHashServiceError(f"Unknown hash result type: {result}")
        except ObjectHashDbOperationlError as e:
            self._logger.error(f"Object hash service work failed: {e}",exc_info=True)
            return False
        except Exception as e:
            self._logger.error(f"Object hash service work failed: {e}",exc_info=True)
            os._exit(1)
        else:
            return True
    

    def run(self):
        """Submit task to object hash service."""
        futures = []
        total_wait_time = 0
        with self._executor as executor:
            self._hash_status_manger.set_finish_status(False)
            self._object_hash_repository.create_table()
            while True:
                scan_record = self._object_hash_repository.query_scan_record()
                scan_service_status = self._object_hash_repository.query_scan_service_status()
                if not scan_record and scan_service_status.is_finished:
                    self._logger.info("all scan record submit done")
                    break
                if not scan_record and not scan_service_status.is_finished:
                    self._logger.info("No scan record found and scan service is not finished")
                    total_wait_time += 1
                    time.sleep(1)
                    continue
                if total_wait_time > 60:
                    self._logger.error("No scan record found and scan service is not finished for 60 seconds")
                    os._exit(1)
                self._logger.debug(f"Submit scan record to object hash service: {scan_record}")
                futures.append(executor.submit(self.work, scan_record))
            for future in futures:
                future.result()
            self._hash_status_manger.set_finish_status(True)

    def stop(self):
        """Stop object hash service."""
        self._executor.shutdown(wait=True, cancel_futures=True)
        self._logger.info("Object hash service stop")

    def reset_table(self):
        """Reset object hash service table."""
        self._object_hash_repository.reset_table()
        self._hash_status_manger.set_finish_status(False)