from typing import Literal, Optional, Union
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
from concurrent.futures import ThreadPoolExecutor
from pydantic import BaseModel, Field, model_validator
import logging
import queue
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

    @model_validator(mode="before")
    @classmethod
    def convert_path_to_str(cls, data):
        if isinstance(data, dict) and "object_path" in data:
            obj_path = data["object_path"]
            if isinstance(obj_path, Path):
                data["object_path"] = str(obj_path)
        return data


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
    status: Mapped[Literal["waiting", "processing", "fail", "done"]] = mapped_column(
        String(15), default="waiting"
    )

    __table_args__ = (
        UniqueConstraint("host_name", "object_path", name="uix_host_name_object_path"),
        UniqueConstraint("scan_id", name="uix_scan_id"),
        Index(
            "idx_md5_sha1_sha256",
            "md5",
            "sha1",
            "sha256",
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
    status: Mapped[Literal["waiting", "processing", "fail", "done"]] = mapped_column(
        String(15), default="waiting"
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


class WorkerObjectHash:
    """Worker-safe ObjectHash that uses pre-extracted config data (no get_config)"""

    def __init__(
        self,
        host_name: str,
        logger: logging.Logger,
        config_data: dict,
    ) -> None:
        self._host_name = host_name
        self._logger = logger
        self._algorithm_list = config_data["algorithm_list"]
        self._hash_chunk_size_bytes = config_data["hash_chunk_size_bytes"]
        self._oversize = config_data["oversize"]
        self._directory_overcount = config_data["directory_overcount"]

    def pre_check(self, scan_record):
        if scan_record.object_size > self._oversize:
            return FormatTransformer.scan_record_to_manual_review_object(
                scan_record, "oversize"
            )
        if (
            scan_record.object_type == "directory"
            and scan_record.object_item_count > self._directory_overcount
        ):
            return FormatTransformer.scan_record_to_manual_review_object(
                scan_record, "overcount"
            )
        if scan_record.object_size == 0:
            return FormatTransformer.scan_record_to_manual_review_object(
                scan_record, "empty"
            )
        return None

    def hash_file(self, scan_record):
        hash_result = {}
        file_path = Path(scan_record.object_path)
        if not file_path.exists():
            raise ObjectHashError(f"File not found: {scan_record.object_path}")
        for algorithm in self._algorithm_list:
            hash_result[algorithm] = (
                self._hash_core(file_path, algorithm).hexdigest().upper()
            )
        return FormatTransformer.scan_record_to_hash_result(scan_record, hash_result)

    def hash_directory(self, scan_record):
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
            for chunk in iter(lambda: f.read(self._hash_chunk_size_bytes), b""):
                hash_obj.update(chunk)
        return hash_obj

    def hash_object(self, scan_record):
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
    """Handles database operations for hash results"""

    def __init__(self, db_engine: Engine, logger: logging.Logger) -> None:
        self._db_engine = db_engine
        self._logger = logger

    def create_hash_table(self) -> None:
        """Create the object_hash table in the database"""
        self._logger.debug("Creating object_hash table...")
        try:
            ObjectHashTable.metadata.create_all(self._db_engine)
        except exc.OperationalError as e:
            raise ObjectHashDbOperationlError(f"Error creating object_hash table: {e}") from e
        self._logger.debug("object_hash table created.")

    def create_manual_review_table(self) -> None:
        """Create the manual_review_object table in the database"""
        self._logger.debug("Creating manual_review_object table...")
        try:
            ManualReviewObjectTable.metadata.create_all(self._db_engine)
        except exc.OperationalError as e:
            raise ObjectHashDbOperationlError(f"Error creating manual_review_object table: {e}") from e
        self._logger.debug("manual_review_object table created.")

    def drop_hash_table(self) -> None:
        """Drop the object_hash table from the database"""
        self._logger.debug("Dropping object_hash table...")
        try:
            ObjectHashTable.metadata.drop_all(self._db_engine)
        except exc.OperationalError as e:
            raise ObjectHashDbOperationlError(f"Error dropping object_hash table: {e}") from e
        self._logger.debug("object_hash table dropped.")

    def drop_manual_review_table(self) -> None:
        """Drop the manual_review_object table from the database"""
        self._logger.debug("Dropping manual_review_object table...")
        try:
            ManualReviewObjectTable.metadata.drop_all(self._db_engine)
        except exc.OperationalError as e:
            raise ObjectHashDbOperationlError(f"Error dropping manual_review_object table: {e}") from e
        self._logger.debug("manual_review_object table dropped.")

    def reset_table(self) -> None:
        """Reset the hash tables by dropping and recreating them"""
        self._logger.debug("Resetting hash tables...")
        self.drop_hash_table()
        self.drop_manual_review_table()
        self.create_hash_table()
        self.create_manual_review_table()
        self._logger.debug("Hash tables reset.")

    @retry_decorator(retries=3, delay=1.0, backoff=2.0, exceptions=(ObjectHashDbOperationlError,))
    def save_hash_result(self, hash_result: HashResult) -> None:
        """Save a hash result to the database with status=waiting (for upload service)"""
        self._logger.debug(f"Saving hash result..., scan_id: {hash_result.scan_id}")
        try:
            with Session(self._db_engine) as session:
                db_record = ObjectHashTable(
                    host_name=hash_result.host_name,
                    object_path=hash_result.object_path,
                    object_type=hash_result.object_type,
                    object_size=hash_result.object_size,
                    object_item_count=hash_result.object_item_count,
                    scan_id=hash_result.scan_id,
                    md5=hash_result.md5,
                    sha1=hash_result.sha1,
                    sha256=hash_result.sha256,
                    status="waiting",  # 初始状态为 waiting，等待后续上传服务处理
                )
                session.add(db_record)
                session.commit()
            self._logger.debug("Hash result saved.")
        except exc.OperationalError as e:
            raise ObjectHashDbOperationlError(f"Error saving hash result: {e}") from e
        except exc.IntegrityError as e:
            raise ObjectHashDbIntegrityError(f"Error saving hash result (integrity): {e}") from e

    @retry_decorator(retries=3, delay=1.0, backoff=2.0, exceptions=(ObjectHashDbOperationlError,))
    def save_manual_review_object(self, manual_review: ManualReviewObject) -> None:
        """Save a manual review object to the database with status=waiting"""
        self._logger.debug(f"Saving manual review object..., scan_id: {manual_review.scan_id}")
        try:
            with Session(self._db_engine) as session:
                db_record = ManualReviewObjectTable(
                    host_name=manual_review.host_name,
                    object_path=manual_review.object_path,
                    object_type=manual_review.object_type,
                    object_size=manual_review.object_size,
                    object_item_count=manual_review.object_item_count,
                    scan_id=manual_review.scan_id,
                    reason=manual_review.reason,
                    status="waiting",  # 初始状态为 waiting，等待人工审核
                )
                session.add(db_record)
                session.commit()
            self._logger.debug("Manual review object saved.")
        except exc.OperationalError as e:
            raise ObjectHashDbOperationlError(f"Error saving manual review object: {e}") from e
        except exc.IntegrityError as e:
            raise ObjectHashDbIntegrityError(f"Error saving manual review object (integrity): {e}") from e


class HashStatusManager:
    """Manages hash service status in the database"""

    def __init__(self, db_engine: Engine, logger: logging.Logger) -> None:
        self._db_engine = db_engine
        self._logger = logger

    def query_finish_status(self, service_name: str = "hash_service") -> Optional[ServiceStatusTable]:
        """Query the hash service finish status from database"""
        self._logger.debug(f"Querying {service_name} finish status...")
        try:
            with Session(self._db_engine) as session:
                return session.query(ServiceStatusTable).filter(
                    ServiceStatusTable.service_name == service_name
                ).scalar()
        except exc.OperationalError as e:
            raise ObjectHashDbOperationlError(f"Error querying {service_name} finish status: {e}") from e

    def add_finish_status(self, service_name: str = "hash_service") -> None:
        """Add hash service finish status to database"""
        self._logger.debug(f"Adding {service_name} finish status...")
        with Session(self._db_engine) as session:
            try:
                session.add(ServiceStatusTable(service_name=service_name, is_finished=False))
                session.commit()
            except exc.OperationalError as e:
                session.rollback()
                raise ObjectHashDbOperationlError(f"Error adding {service_name} finish status: {e}") from e
            except exc.IntegrityError as e:
                session.rollback()
                raise ObjectHashDbIntegrityError(f"Error adding {service_name} finish status (integrity): {e}") from e
        self._logger.debug(f"{service_name} finish status added.")

    def change_finish_status(
        self, status: bool, service_name: str = "hash_service"
    ) -> None:
        """Change the hash service finish status in database"""
        self._logger.debug(f"Changing {service_name} finish status to {status}...")
        with Session(self._db_engine) as session:
            query_result = session.query(ServiceStatusTable).filter(
                ServiceStatusTable.service_name == service_name
            ).scalar()
            if query_result is None:
                try:
                    session.add(ServiceStatusTable(service_name=service_name, is_finished=status))
                    session.commit()
                except exc.OperationalError as e:
                    session.rollback()
                    raise ObjectHashDbOperationlError(f"Error changing {service_name} finish status: {e}") from e
                except exc.IntegrityError as e:
                    session.rollback()
                    raise ObjectHashDbIntegrityError(f"Error changing {service_name} finish status (integrity): {e}") from e
            else:
                query_result.is_finished = status
                session.commit()
        self._logger.info(f"{service_name} finish status changed to {status}.")


class HashService:
    """Main service for hashing files and directories"""

    def __init__(
        self,
        db_engine: Optional[Engine] = None,
        max_workers: int = 2,
    ) -> None:
        self.logger: logging.Logger = logging.getLogger(__name__)
        self.logger.debug("Hash service initializing...")
        self.db_engine: Engine = db_engine if db_engine is not None else self._get_db_engine()
        # Note: Using ThreadPoolExecutor instead of ProcessPoolExecutor due to SQLAlchemy
        # engine pickle issues. ThreadPoolExecutor works well for I/O-bound hash computation.
        self._executor: ThreadPoolExecutor = ThreadPoolExecutor(max_workers=max_workers)
        self._host_name: str = platform.node()
        self._object_hash: ObjectHash = ObjectHash(self._host_name, self.logger)
        self._repository: HashRepository = HashRepository(self.db_engine, self.logger)
        self._status_manager: HashStatusManager = HashStatusManager(self.db_engine, self.logger)
        self._host_name = platform.node()
        self._pending_futures: list = []
        self.logger.debug(f"Hash service init finished. Host name: {self._host_name}")

    def _get_db_engine(self) -> Engine:
        """Get database engine from DbService"""
        return DbService().get_engine()

    def create_hash_table(self) -> None:
        """Create the hash tables in the database"""
        self._repository.create_hash_table()
        self._repository.create_manual_review_table()

    def drop_hash_table(self) -> None:
        """Drop the hash tables from the database"""
        self._repository.drop_hash_table()
        self._repository.drop_manual_review_table()

    def reset_table(self) -> None:
        """Reset the hash tables by dropping and recreating them"""
        self._repository.reset_table()

    def _get_next_waiting_record(self) -> Optional[ScanTable]:
        """Get the next waiting record from scan_results table"""
        self.logger.debug("Fetching next waiting record...")
        try:
            with Session(self.db_engine) as session:
                record = session.query(ScanTable).filter(
                    ScanTable.status == "waiting"
                ).order_by(ScanTable.id).first()
                return record
        except exc.OperationalError as e:
            self.logger.error(f"Error fetching waiting record: {e}")
            return None

    def _update_scan_status(
        self, scan_id: int, status: Literal["waiting", "processing", "fail", "done"]
    ) -> None:
        """Update the status of a scan record"""
        self.logger.debug(f"Updating scan record {scan_id} status to {status}")
        try:
            with Session(self.db_engine) as session:
                record = session.query(ScanTable).filter(ScanTable.id == scan_id).first()
                if record:
                    record.status = status
                    session.commit()
                    self.logger.debug(f"Scan record {scan_id} status updated to {status}")
        except exc.OperationalError as e:
            self.logger.error(f"Error updating scan record {scan_id} status: {e}")
            raise ObjectHashDbOperationlError(f"Error updating scan record status: {e}") from e

    def _is_scan_service_finished(self) -> bool:
        """Check if the scan service has finished"""
        self.logger.debug("Checking if scan service is finished...")
        try:
            with Session(self.db_engine) as session:
                status = session.query(ServiceStatusTable).filter(
                    ServiceStatusTable.service_name == "scan_service"
                ).scalar()
                if status:
                    return status.is_finished
                return False
        except exc.OperationalError as e:
            self.logger.error(f"Error checking scan service status: {e}")
            return False

    def _submit_hash_task(self, scan_record: ScanTable) -> None:
        """Submit a hash task to the process pool"""
        scan_id = scan_record.id
        self.logger.info(f"Submitting hash task for scan_id: {scan_id}")
        # Update status to processing
        self._update_scan_status(scan_id, "processing")
        # Extract data from SQLAlchemy model for pickling (all paths as strings)
        scan_data = {
            "id": scan_id,
            "host_name": scan_record.host_name,
            "object_path": str(scan_record.object_path),
            "object_name": scan_record.object_name,
            "object_type": scan_record.object_type,
            "object_size": scan_record.object_size,
            "object_item_count": scan_record.object_item_count,
            "object_items": scan_record.object_items,
        }
        # Get config values as primitives for pickling (deep copy to avoid references)
        config_data = {
            "algorithm_list": list(self._object_hash._algorithm_list),
            "hash_chunk_size_bytes": int(self._object_hash._hash_chunk_size_bytes),
            "oversize": int(self._object_hash._config.oversize),
            "directory_overcount": int(self._object_hash._config.directory_overcount),
        }
        future = self._executor.submit(
            self._process_hash, scan_id, scan_data, self._host_name, config_data
        )
        self._pending_futures.append((scan_id, future))

    def _process_hash(
        self, scan_id: int, scan_data: dict, host_name: str, config_data: dict
    ) -> dict:
        """Process hash for a single record (runs in worker process)"""
        from .hash_worker import process_hash_task
        return process_hash_task(scan_id, scan_data, host_name, config_data)

    def _handle_hash_result(self, scan_id: int, result: dict) -> None:
        """Handle the hash result dict, save to database and update status"""
        self.logger.info(f"Handling hash result for scan_id: {scan_id}")
        try:
            result_type = result.get("type")
            result_data = result.get("data", {})

            if result_type == "hash":
                hash_result = HashResult(**result_data)
                self._repository.save_hash_result(hash_result)
            elif result_type == "manual_review":
                manual_review = ManualReviewObject(**result_data)
                self._repository.save_manual_review_object(manual_review)
            else:
                raise ObjectHashError(f"Unknown result type: {result_type}")
            # Update status to done
            self._update_scan_status(scan_id, "done")
            self.logger.info(f"Scan record {scan_id} hash completed and saved.")
        except (ObjectHashDbOperationlError, ObjectHashDbIntegrityError) as e:
            self.logger.error(f"Failed to save hash result for scan_id {scan_id}: {e}")
            # Update status to fail
            self._update_scan_status(scan_id, "fail")

    def _cancel_all_tasks(self) -> None:
        """Cancel all pending tasks and set processing records back to waiting"""
        self.logger.info("Cancelling all pending tasks...")
        for scan_id, future in self._pending_futures:
            if not future.done():
                future.cancel()
        self.logger.info("All pending tasks cancelled.")
        # Reset processing records to waiting
        self.logger.info("Resetting processing records to waiting...")
        try:
            with Session(self.db_engine) as session:
                processing_records = session.query(ScanTable).filter(
                    ScanTable.status == "processing"
                ).all()
                for record in processing_records:
                    record.status = "waiting"
                session.commit()
                self.logger.info(f"Reset {len(processing_records)} processing records to waiting.")
        except exc.OperationalError as e:
            self.logger.error(f"Error resetting processing records: {e}")

    def run(self) -> None:
        """Main loop: fetch waiting records and process them until all done"""
        self.logger.info("Hash service starting...")
        try:
            # Set hash_service status to not finished
            self._status_manager.change_finish_status(False, "hash_service")
            # Create tables if not exist
            self.create_hash_table()

            while True:
                # Check if scan service is finished
                if not self._is_scan_service_finished():
                    self.logger.debug("Scan service not finished yet, waiting...")
                    time.sleep(1)
                    continue

                # Get next waiting record
                scan_record = self._get_next_waiting_record()
                if scan_record is None:
                    self.logger.info("No more waiting records. Hash service finished.")
                    break

                # Submit hash task
                self._submit_hash_task(scan_record)

                # Check for completed futures and handle results
                completed_indices = []
                for idx, (scan_id, future) in enumerate(self._pending_futures):
                    if future.done():
                        try:
                            result = future.result()
                            self._handle_hash_result(scan_id, result)
                            completed_indices.append(idx)
                        except Exception as e:
                            self.logger.error(f"Error processing hash result for scan_id {scan_id}: {e}", exc_info=True)
                            self._update_scan_status(scan_id, "fail")
                            completed_indices.append(idx)

                # Remove completed futures
                for idx in sorted(completed_indices, reverse=True):
                    self._pending_futures.pop(idx)

            # Wait for all pending futures to complete
            self.logger.info("Waiting for all pending hash tasks to complete...")
            for scan_id, future in self._pending_futures:
                try:
                    result = future.result()
                    self._handle_hash_result(scan_id, result)
                except Exception as e:
                    self.logger.error(f"Error processing hash result for scan_id {scan_id}: {e}", exc_info=True)
                    self._update_scan_status(scan_id, "fail")

            self._pending_futures.clear()

            # Set hash_service status to finished
            self._status_manager.change_finish_status(True, "hash_service")

        except KeyboardInterrupt:
            self.logger.warning("Hash service interrupted by user.")
            self._cancel_all_tasks()
            self._status_manager.change_finish_status(True, "hash_service")
            raise
        except Exception as e:
            self.logger.error(f"Hash service error: {e}", exc_info=True)
            self._cancel_all_tasks()
            self._status_manager.change_finish_status(True, "hash_service")
            raise
        finally:
            self.logger.debug("Hash service shutting down...")
            self._executor.shutdown(wait=False)
            self.logger.info("Hash service stopped.")

    def stop(self) -> None:
        """Stop the hash service"""
        self.logger.info("Hash service stopping...")
        self._cancel_all_tasks()
        self._executor.shutdown(wait=False)
        self.logger.info("Hash service stopped.")
