from pathlib import Path
from pydantic import BaseModel
from sqlalchemy.orm import DeclarativeBase, mapped_column,Mapped, Session
from sqlalchemy import Engine,BigInteger, String, Integer,UniqueConstraint,MetaData, JSON, update, Boolean
from time import time_ns
from datetime import datetime
import os
from .db_service import get_engine

from sqlalchemy.orm.decl_api import interfaces


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

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    created_at: Mapped[int] = mapped_column(BigInteger, default=time_ns)
    updated_at: Mapped[int] = mapped_column(BigInteger, onupdate=time_ns,nullable=True)

    @property
    def created_at_localtime(self):
        local_time_sec = self.created_at / 1_000_000_000.0
        return datetime.fromtimestamp(local_time_sec)

    @property
    def updated_at_localtime(self):
        local_time_sec = self.updated_at / 1_000_000_000.0
        return datetime.fromtimestamp(local_time_sec)

class ScanTable(ScanBase):
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
    def __init__(self,source_object_paths:list[Path|str],db_engine:Engine):
        self.source_object_paths = [Path(path) for path in source_object_paths]
        self.db_engine = db_engine
        self._current_object_path:Path = None


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
            raise ValueError(f"Object path does not exist: {object_path}")
        self._current_object_path = object_path
        if object_path.is_file():
            return self.scan_file(object_path)
        if object_path.is_dir():
            return self.scan_directory(object_path)
        raise ValueError(f"Invalid object path: {object_path}")
    
    def create_scan_table(self):
        ScanTable.metadata.create_all(self.db_engine)
    def drop_scan_table(self):
        ScanTable.metadata.drop_all(self.db_engine)
    def reset_scan_table(self):
        self.drop_scan_table()
        self.create_scan_table()

    def save_scan_result(self, scan_results: ScanResult):
        with Session(self.db_engine) as session:
            query_result = session.query(ScanTable).filter(ScanTable.host_name == scan_results.host_name, ScanTable.object_path == scan_results.object_path).scalar()
            if query_result is None:
                session.add(ScanTable(**scan_results.model_dump()))
                session.commit()
            else:
                for key, value in scan_results.model_dump().items():
                    if not hasattr(query_result, key):
                        raise KeyError(f"scan_results  key: {key} not in scan table,check scan table schema")
                    if value != getattr(query_result, key):
                        raise ValueError(f"scan_results value: {value} not match scan table value: {getattr(query_result, key)} for key: {key}")


