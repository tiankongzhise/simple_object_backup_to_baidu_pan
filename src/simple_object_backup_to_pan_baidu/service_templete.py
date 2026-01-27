from pydantic import BaseModel
from sqlalchemy.orm import DeclarativeBase, mapped_column, Mapped, Session
from sqlalchemy import Engine, BigInteger, String, Integer, UniqueConstraint, MetaData, JSON, Boolean
from sqlalchemy import exc

from pathlib import Path
from typing import Literal
import logging
import platform

from .utils import DbMixin
from .db_service import DbService

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


class _ServiceRepository:
    def __init__(self,service_name:str, engine: Engine|None = None):
        self.engine = engine or DbService().get_engine()
        self.logger = logging.getLogger(f'service.{service_name}.repository')
        self.host_name = platform.node()

