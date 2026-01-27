from pathlib import Path
from pydantic import BaseModel
from sqlalchemy.orm import DeclarativeBase, mapped_column, Mapped, Session
from sqlalchemy import Engine, BigInteger, String, Integer, UniqueConstraint, MetaData, JSON, Boolean
from sqlalchemy import exc
from datetime import datetime
import os
import platform
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError, CancelledError, Future
from typing import TYPE_CHECKING, Literal, Sequence, Optional
import logging

if TYPE_CHECKING:
    from .db_service import DbService
from .utils import retry_decorator, DbMixin, ServiceStatusTable


class ScanServiceError(Exception):
    """Base class for scan service errors"""


class ScanServiceKeyError(ScanServiceError):
    """Error raised when a key is not found in the scan service schema"""


class ScanServiceValueError(ScanServiceError):
    """Error raised when a value is not valid for the scan service"""


class ScanDbError(ScanServiceError):
    """Base class for scan database errors"""


class ScanDbIntegrityError(ScanServiceError):
    """Error raised when there is an integrity error inserting a scan result"""


class ScanDbOperationalError(ScanServiceError):
    """Error raised when there is an error inserting a scan result"""


class ScanResult(BaseModel):
    """Scan result for a single object"""
    host_name: str
    object_path: Path
    object_name: str
    object_type: Literal["file", "directory"]
    object_size: int
    object_item_count: int
    object_items: dict[str, int]


class ScanBase(DeclarativeBase):
    metadata = MetaData()


class ScanTable(DbMixin, ScanBase):
    __tablename__ = "scan_results"
    host_name: Mapped[str] = mapped_column(String(255))
    object_path: Mapped[str] = mapped_column(String(255))
    object_name: Mapped[str] = mapped_column(String(255))
    object_type: Mapped[str] = mapped_column(String(15))
    object_size: Mapped[int] = mapped_column(BigInteger)
    object_item_count: Mapped[int] = mapped_column(Integer)
    object_items: Mapped[dict] = mapped_column(JSON)
    status: Mapped[Literal['waiting','processing','fail','done']] = mapped_column(String(15), default='waiting')
    __table_args__ = (UniqueConstraint('host_name', 'object_path', name='uix_host_name_object_path'),)


class Scanner:
    """Handles file and directory scanning operations"""

    def __init__(self, host_name: str, logger: logging.Logger) -> None:
        self._host_name: str = host_name
        self._logger: logging.Logger = logger

    def scan_file(self, file_path: Path, relative_path: Path) -> ScanResult:
        """Scan a single file and return its scan result"""
        items_path = file_path.relative_to(relative_path).as_posix()
        self._logger.debug(f"Scanning file: {file_path}")
        return ScanResult(
            host_name=self._host_name,
            object_path=file_path,
            object_name=file_path.name,
            object_type="file",
            object_size=file_path.stat().st_size,
            object_item_count=1,
            object_items={items_path: file_path.stat().st_size}
        )

    def scan_directory(self, directory_path: Path, relative_path: Path) -> ScanResult:
        """Scan a directory recursively and return its scan result"""
        self._logger.debug(f"Scanning directory: {directory_path}")
        object_item_count = 0
        object_items = {}
        object_size = 0

        for item in directory_path.rglob("*"):
            if item.is_file():
                item_path = item.relative_to(relative_path).as_posix()
                object_item_count += 1
                object_items[item_path] = item.stat().st_size
                object_size += item.stat().st_size

        return ScanResult(
            host_name=self._host_name,
            object_path=directory_path,
            object_name=directory_path.name,
            object_type="directory",
            object_size=object_size,
            object_item_count=object_item_count,
            object_items=object_items
        )

    def scan_object(self, object_path: Path) -> ScanResult:
        """Scan an object (file or directory) and return its scan result"""
        if not object_path.exists():
            raise ScanServiceValueError(f"Object path does not exist: {object_path}")

        if object_path.is_file():
            return self.scan_file(object_path, relative_path=object_path.parent)

        if object_path.is_dir():
            return self.scan_directory(object_path, relative_path=object_path.parent)

        raise ScanServiceError(f"Invalid object path: {object_path}")


class ScanRepository:
    """Handles database operations for scan results"""

    def __init__(self, db_engine: Engine, logger: logging.Logger) -> None:
        self._db_engine: Engine = db_engine
        self._logger: logging.Logger = logger

    @retry_decorator(retries=3, delay=1.0, backoff=2.0, exceptions=(ScanDbOperationalError,))
    def create_table(self) -> None:
        """Create the scan table in the database"""
        self._logger.debug("Creating scan table...")
        try:
            ScanTable.metadata.create_all(self._db_engine)
        except exc.OperationalError as e:
            raise ScanDbOperationalError(f"Error creating scan table: {e}") from e
        except Exception as e:
            raise ScanDbError(f"Error creating scan table: {e}") from e
        self._logger.debug("Scan table created.")

    @retry_decorator(retries=3, delay=1.0, backoff=2.0, exceptions=(ScanDbOperationalError,))
    def drop_table(self) -> None:
        """Drop the scan table from the database"""
        self._logger.debug("Dropping scan table...")
        try:
            ScanTable.metadata.drop_all(self._db_engine)
        except exc.OperationalError as e:
            raise ScanDbOperationalError(f"Error dropping scan table: {e}") from e
        except Exception as e:
            raise ScanDbError(f"Error dropping scan table: {e}") from e
        self._logger.debug("Scan table dropped.")

    def reset_table(self) -> None:
        """Reset the scan table by dropping and recreating it"""
        self._logger.debug("Resetting scan table...")
        self.drop_table()
        self.create_table()
        self._logger.debug("Scan table reset.")

    @retry_decorator(retries=3, delay=1.0, backoff=2.0, exceptions=(ScanDbOperationalError,))
    def query_scan_result(self, scan_result: ScanResult) -> Optional[ScanTable]:
        """Query the scan table for a given host name and object path"""
        self._logger.debug(f"Querying scan table..., host_name: {scan_result.host_name}, object_path: {scan_result.object_path}")
        try:
            with Session(self._db_engine) as session:
                return session.query(ScanTable).filter(
                    ScanTable.host_name == scan_result.host_name,
                    ScanTable.object_path == scan_result.object_path
                ).scalar()
        except exc.OperationalError as e:
            raise ScanDbOperationalError(f"Error querying scan table: {e}") from e
        except Exception as e:
            raise ScanDbError(f"Error querying scan table: {e}") from e

    @retry_decorator(retries=3, delay=1.0, backoff=2.0, exceptions=(ScanDbOperationalError,))
    def save_scan_result(self, scan_result: ScanResult) -> None:
        """Save a scan result to the database"""
        self._logger.debug(f"Saving scan result..., host_name: {scan_result.host_name}, object_path: {scan_result.object_path}")
        with Session(self._db_engine) as session:
            query_result = self.query_scan_result(scan_result)
            if query_result is None:
                try:
                    session.add(ScanTable(**scan_result.model_dump()))
                    session.commit()
                except exc.OperationalError as e:
                    session.rollback()
                    self._logger.error("Scan result insert failed because of an operational error.")
                    raise ScanDbOperationalError(f"Error inserting scan result: {e}") from e
                except exc.IntegrityError as e:
                    session.rollback()
                    self._logger.error("Scan result insert failed because of an integrity error.")
                    raise ScanDbIntegrityError(f"Error inserting scan result: {e}") from e
                except Exception as e:
                    session.rollback()
                    self._logger.error(f"Scan result insert failed because of an error.{e}")
                    raise ScanDbError(f"Error inserting scan result: {e}") from e
            else:
                for key, value in scan_result.model_dump().items():
                    if not hasattr(query_result, key):
                        self._logger.error(f"scan_results  key: {key} not in scan table,check scan table schema")
                        raise ScanServiceKeyError(f"scan_results  key: {key} not in scan table,check scan table schema")
                    if key == 'is_hashed':
                        continue
                    if value != getattr(query_result, key):
                        self._logger.error(f"scan_results value: {value} not match scan table value: {getattr(query_result, key)} for key: {key}")
                        raise ScanServiceValueError(f"scan_results value: {value} not match scan table value: {getattr(query_result, key)} for key: {key}")
        self._logger.debug("Scan result saved.")


class ScanStatusManager:
    """Manages scan service status in the database"""

    def __init__(self, db_engine: Engine, logger: logging.Logger) -> None:
        self._db_engine: Engine = db_engine
        self._logger: logging.Logger = logger

    def query_finish_status(self) -> Optional[ServiceStatusTable]:
        """Query the scan service finish status from database"""
        self._logger.debug("Querying scan service finish status...")
        try:
            with Session(self._db_engine) as session:
                return session.query(ServiceStatusTable).filter(
                    ServiceStatusTable.service_name == "scan_service"
                ).scalar()
        except exc.OperationalError as e:
            self._logger.error(f"Error querying scan service finish status: {e}")
            raise ScanDbOperationalError(f"Error querying scan service finish status: {e}") from e
        except Exception as e:
            self._logger.error(f"Error querying scan service finish status: {e}")
            raise ScanDbError(f"Error querying scan service finish status: {e}") from e

    @retry_decorator(retries=3, delay=1.0, backoff=2.0, exceptions=(ScanDbOperationalError,))
    def add_finish_status(self) -> None:
        """Add scan service finish status to database"""
        self._logger.debug("Adding scan service finish status...")
        with Session(self._db_engine) as session:
            try:
                session.add(ServiceStatusTable(service_name="scan_service", is_finished=False))
                session.commit()
            except exc.OperationalError as e:
                self._logger.error("Scan service finish status insert failed because of an operational error.")
                session.rollback()
                raise ScanDbOperationalError(f"Error sending scan service finish status: {e}") from e
            except exc.IntegrityError as e:
                self._logger.error("Scan service finish status insert failed because of an integrity error.")
                session.rollback()
                raise ScanDbIntegrityError(f"Error sending scan service finish status: {e}") from e
            except Exception as e:
                session.rollback()
                self._logger.error("Scan service finish status insert failed because of an error.")
                raise ScanDbError(f"Error sending scan service finish status: {e}") from e
        self._logger.debug("Scan service finish status sent.")

    @retry_decorator(retries=3, delay=1.0, backoff=2.0, exceptions=(ScanDbOperationalError,))
    def change_finish_status(self, status: Literal[True, False]) -> None:
        """Change the scan service finish status in database"""
        self._logger.debug("Changing scan service finish status...")
        with Session(self._db_engine) as session:
            query_result = session.query(ServiceStatusTable).filter(
                ServiceStatusTable.service_name == "scan_service"
            ).scalar()
            if query_result is None:
                try:
                    session.add(ServiceStatusTable(service_name="scan_service", is_finished=status))
                    session.commit()
                except exc.OperationalError as e:
                    self._logger.error("Scan service finish status insert failed because of an operational error.")
                    session.rollback()
                    raise ScanDbOperationalError(f"Error sending scan service finish status: {e}") from e
                except exc.IntegrityError as e:
                    self._logger.error("Scan service finish status insert failed because of an integrity error.")
                    session.rollback()
                    raise ScanDbIntegrityError(f"Error sending scan service finish status: {e}") from e
                except Exception as e:
                    session.rollback()
                    self._logger.error("Scan service finish status insert failed because of an error.")
                    raise ScanDbError(f"Error sending scan service finish status: {e}") from e
            else:
                query_result.is_finished = status
                session.commit()
        self._logger.info(f"Scan service finish status changed to {status}.")


class ScanService:
    """Main service for scanning files and directories"""

    def __init__(
        self,
        source_object_paths: Sequence[Path | str],
        db_engine: Optional[Engine] = None,
        max_workers: int = 3
    ) -> None:
        self.logger: logging.Logger = logging.getLogger(__name__)
        self.logger.debug("Scan service initializing...")
        self.source_object_paths: list[Path] = [Path(path) for path in source_object_paths]
        self.db_engine: Engine = db_engine if db_engine is not None else self._get_db_engine()
        self._executor: ThreadPoolExecutor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="ScanServiceThread_")
        self._host_name: str = platform.node()
        self._scanner: Scanner = Scanner(self._host_name, self.logger)
        self._repository: ScanRepository = ScanRepository(self.db_engine, self.logger)
        self._status_manager: ScanStatusManager = ScanStatusManager(self.db_engine, self.logger)
        self.logger.debug(f"Scan service init finished. Host name: {self._host_name}")

    def _get_db_engine(self) -> Engine:
        """Get database engine from DbService"""
        from .db_service import DbService
        return DbService().get_engine()

    def scan_object(self, object_path: Path) -> ScanResult:
        """Scan an object and return the result"""
        return self._scanner.scan_object(object_path)

    def create_scan_table(self) -> None:
        """Create the scan table in the database"""
        self._repository.create_table()

    def drop_scan_table(self) -> None:
        """Drop the scan table from the database"""
        self._repository.drop_table()

    def reset_scan_table(self) -> None:
        """Reset the scan table by dropping and recreating it"""
        self._repository.reset_table()

    def query_scan_table(self, scan_results: ScanResult) -> Optional[ScanTable]:
        """Query the scan table for a given scan result"""
        return self._repository.query_scan_result(scan_results)

    def save_scan_result(self, scan_results: ScanResult) -> None:
        """Save a scan result to the database"""
        self._repository.save_scan_result(scan_results)

    def query_scan_service_finish_status(self) -> Optional[ServiceStatusTable]:
        """Query the scan service finish status from database"""
        return self._status_manager.query_finish_status()

    def add_scan_service_finish_status(self) -> None:
        """Add scan service finish status to database"""
        self._status_manager.add_finish_status()

    def change_scan_service_finish_status(self, status: Literal[True, False]) -> None:
        """Change the scan service finish status in database"""
        self._status_manager.change_finish_status(status)

    def start(self) -> None:
        """Start the scan service"""
        self.logger.info("Scan service starting...")
        self.create_scan_table()
        futures: list[Future[ScanResult]] = []
        total_object_paths = len(self.source_object_paths) if self.source_object_paths else 0
        self.logger.info(f"Total object paths: {total_object_paths}")
        try:
            for object_path in self.source_object_paths:
                self.logger.debug(f"submitting object path: {object_path}")
                if object_path.is_file():
                    futures.append(self._executor.submit(self.scan_object, object_path))
                    continue
                if object_path.is_dir():
                    items = list(object_path.iterdir())
                    self.logger.info(f"Total {len(items)} items in directory: {object_path}")
                    temp_scan_count = 0
                    for object in items:
                        futures.append(self._executor.submit(self.scan_object, object))
                        temp_scan_count += 1
                        self.logger.info(f"submitting {object_path}: {object},submitted {temp_scan_count} items ,submitperse {temp_scan_count/len(items)*100:.2f}%")
            all_items = len(futures)
            finished_items = 0
            self.logger.info(f"Scan result received, total: {all_items}")

            if all_items:
                self.change_scan_service_finish_status(False)
            for result in as_completed(futures):
                try:
                    self.logger.debug(f"Scan result received, finished: {finished_items}/{all_items}")
                    self.save_scan_result(result.result())
                    finished_items += 1
                    self.logger.info(f"Scan result saved, finished: {finished_items}/{all_items}")
                except Exception as e:
                    self.logger.error(f"Scan Service Error: {e}", exc_info=True)
                    self.graceful_shutdown(futures)
                    raise ScanServiceError(f"Error saving scan result: {e}") from e
            try:
                self.change_scan_service_finish_status(True)
            except Exception as e:
                self.logger.error(f"Scan Service Error: {e}", exc_info=True)
                self.graceful_shutdown(futures)
                raise ScanServiceError(f"Error sending scan service finish status: {e}") from e
        finally:
            self.logger.debug("Scan service start finally...")
            self._executor.shutdown(wait=True)
            self.logger.info("Scan service stopped.")

    def graceful_shutdown(self, futures: list[Future[ScanResult]]) -> None:
        """Gracefully shutdown the scan service"""
        self.logger.info("Scan service graceful shutdown starting...,stopping executor")
        self._executor.shutdown(wait=False)
        self.logger.info("Scan service graceful shutdown, canceling pending futures")
        for future in futures:
            if not future.done() and not future.running():
                future.cancel()
        self.logger.info("Scan service graceful shutdown waitting for running futures to complete")
        try:
            self.logger.debug("Scan service graceful shutdown, timeout set 0.1")
            for future in futures:
                if not future.done():
                    try:
                        future.result(timeout=0.1)
                    except (TimeoutError, CancelledError) as e:
                        pass
        except KeyboardInterrupt as e:
            self.logger.warning("\nScan service graceful shutdown,收到第二次中断信号，立即终止！")
            os._exit(1)
        self.logger.info("Scan service graceful shutdown completed.")

    def stop(self) -> None:
        """Stop the scan service"""
        self.logger.info("Scan service stopping...")
        os._exit(1)
