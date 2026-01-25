from pathlib import Path
from pydantic import BaseModel
from sqlalchemy.orm import DeclarativeBase, mapped_column,Mapped, Session
from sqlalchemy import Engine,BigInteger, String, Integer,UniqueConstraint,MetaData, JSON, Boolean
from sqlalchemy import exc
from time import time_ns
from datetime import datetime
import os

from .db_service import DbService
from .utils import retry_decorator,DbMixin,StatusFinishedTable

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
    object_size: int
    object_item_count: int
    object_items:dict[str,int]

class ScanBase(DeclarativeBase):
    metadata = MetaData()

class ScanTable(DbMixin,ScanBase):
    __tablename__ = "scan_results"
    host_name: Mapped[str] = mapped_column(String(255))
    object_name: Mapped[str] = mapped_column(String(255))
    object_path: Mapped[str] = mapped_column(String(255))
    object_size: Mapped[int] = mapped_column(BigInteger)
    object_item_count: Mapped[int] = mapped_column(Integer)
    object_items: Mapped[dict] = mapped_column(JSON)
    is_hashed: Mapped[bool] = mapped_column(Boolean, default=False)
    __table_args__ = (UniqueConstraint('host_name', 'object_path', name='uix_host_name_object_path'),)


class ScanService:
    def __init__(self,source_object_paths:list[Path|str],db_engine:Engine|None = None):
        self.source_object_paths = [Path(path) for path in source_object_paths]
        self.db_engine = db_engine or DbService().get_engine()
        self._current_object_path:Path = None  # type: ignore


    def scan_file(self,file_path:Path):
        items_path = file_path.relative_to(self._current_object_path.parent).as_posix()
        return ScanResult(
        host_name=os.uname().nodename,
        object_path=file_path,
        object_name=file_path.name,
        object_size=file_path.stat().st_size,
        object_item_count=1,
        object_items={items_path:file_path.stat().st_size}
    )



    def scan_directory(self,directory_path:Path):
        object_item_count = 0
        object_items = {}
        object_size = 0
        for item in directory_path.rglob("*"):
            if item.is_file():
                item_path = item.relative_to(self._current_object_path.parent).as_posix()
                object_item_count += 1
                object_items[item_path] = item.stat().st_size
                object_size += item.stat().st_size
        return ScanResult(
        host_name=os.uname().nodename,
        object_path=directory_path,
        object_name=directory_path.name,
        object_size=object_size,
        object_item_count=object_item_count,
        object_items=object_items
    )

    def scan_object(self,object_path:Path):
        if not object_path.exists():
            raise ScanServiceValueError(f"Object path does not exist: {object_path}")
        self._current_object_path = object_path
        if object_path.is_file():
            return self.scan_file(object_path)
        if object_path.is_dir():
            return self.scan_directory(object_path)
        raise ScanServiceError(f"Invalid object path: {object_path}")
    
    @retry_decorator(retries=3, delay=1.0, backoff=2.0, exceptions=(ScanDbOperationalError,))
    def create_scan_table(self):
        """Create the scan table in the database"""
        try:
            ScanTable.metadata.create_all(self.db_engine)
        except exc.OperationalError as e:
            raise ScanDbOperationalError(f"Error creating scan table: {e}") from e
        except Exception as e:
            raise ScanDbError(f"Error creating scan table: {e}") from e
    
    @retry_decorator(retries=3, delay=1.0, backoff=2.0, exceptions=(ScanDbOperationalError,))
    def drop_scan_table(self):
        """Drop the scan table from the database"""
        try:
            ScanTable.metadata.drop_all(self.db_engine)
        except exc.OperationalError as e:
            raise ScanDbOperationalError(f"Error dropping scan table: {e}") from e
        except Exception as e:
            raise ScanDbError(f"Error dropping scan table: {e}") from e
    
    def reset_scan_table(self):
        """Reset the scan table by dropping and recreating it"""
        self.drop_scan_table()
        self.create_scan_table()

    @retry_decorator(retries=3, delay=1.0, backoff=2.0, exceptions=(ScanDbOperationalError,))
    def query_scan_table(self,scan_results: ScanResult):
        """Query the scan table for a given host name and object path"""
        try:
            with Session(self.db_engine) as session:
                return session.query(ScanTable).filter(ScanTable.host_name == scan_results.host_name, ScanTable.object_path == scan_results.object_path).scalar()
        except exc.OperationalError as e:
            raise ScanDbOperationalError(f"Error querying scan table: {e}") from e
        except Exception as e:
            raise ScanDbError(f"Error querying scan table: {e}") from e

    @retry_decorator(retries=3, delay=1.0, backoff=2.0, exceptions=(ScanDbOperationalError,))
    def save_scan_result(self, scan_results: ScanResult):
        with Session(self.db_engine) as session:
            query_result = self.query_scan_table(scan_results)
            if query_result is None:
                try:
                    session.add(ScanTable(**scan_results.model_dump()))
                    session.commit()
                except exc.OperationalError as e:
                    session.rollback()
                    raise ScanDbOperationalError(f"Error inserting scan result: {e}") from e
                except exc.IntegrityError as e:
                    session.rollback()
                    raise ScanDbIntegrityError(f"Error inserting scan result: {e}") from e
                except Exception as e:
                    session.rollback()
                    raise ScanDbError(f"Error inserting scan result: {e}") from e
            else:
                for key, value in scan_results.model_dump().items():
                    if not hasattr(query_result, key):
                        raise ScanServiceKeyError(f"scan_results  key: {key} not in scan table,check scan table schema")
                    if value != getattr(query_result, key):
                        raise ScanServiceValueError(f"scan_results value: {value} not match scan table value: {getattr(query_result, key)} for key: {key}")


    def start(self):
        """Start the scan service"""
        self.create_scan_table()
        for object_path in self.source_object_paths:
            scan_result = self.scan_object(object_path)
            self.save_scan_result(scan_result)
