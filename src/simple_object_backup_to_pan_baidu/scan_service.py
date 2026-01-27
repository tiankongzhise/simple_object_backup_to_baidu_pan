from pydantic import BaseModel
from sqlalchemy.orm import DeclarativeBase, mapped_column, Mapped, Session
from sqlalchemy import Engine, BigInteger, String, Integer, UniqueConstraint, MetaData, JSON, Boolean
from sqlalchemy import exc

from contextlib import contextmanager
from pathlib import Path
from typing import Literal
from functools import wraps
import logging
import platform

from .utils import DbMixin,retry_decorator
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
        self.service_name = service_name
        self._service_repository_error = ScanServiceDbError

    
    @retry_decorator(retries=3, delay=1.0, backoff=2.0, exceptions=(exc.OperationalError,))
    def add_scan_record(self, data: _FormatData):
        try:
            with Session(self.engine) as session:
                session.add(ScanRecords(**data.model_dump()))
                session.commit()
        except exc.OperationalError as e:
            self.logger.error(f'{self.service_name}添加记录失败，因为数据库连接异常，具体错误信息为：{e}', exc_info=True)
            raise e
        except Exception as e:
            self.logger.error(f'{self.service_name}添加记录失败，因为数据库异常，具体错误信息为：{e}', exc_info=True)
            raise ScanServiceDbError from e

    @retry_decorator(retries=3, delay=1.0, backoff=2.0, exceptions=(exc.OperationalError,))
    def get_scan_record_by_id(self, id: int):
        try:
            with Session(self.engine) as session:
                record = session.get(ScanRecords, id)
                return record
        except exc.OperationalError as e:
            self.logger.error(f'{self.service_name}获取记录失败，因为数据库连接异常，具体错误信息为：{e}', exc_info=True)
            raise e
        except Exception as e:
            self.logger.error(f'{self.service_name}获取记录失败，因为数据库异常，具体错误信息为：{e}', exc_info=True)
            raise ScanServiceDbError from e

    @retry_decorator(retries=3, delay=1.0, backoff=2.0, exceptions=(exc.OperationalError,))
    def get_scan_record_by_unique(self, host_name: str, object_path: str):
        try:
            with Session(self.engine) as session:
                record = session.query(ScanRecords).filter(ScanRecords.host_name == host_name, ScanRecords.object_path == object_path).first()
                return record
        except exc.OperationalError as e:
            self.logger.error(f'{self.service_name}获取记录失败，因为数据库连接异常，具体错误信息为：{e}', exc_info=True)
            raise e
        except Exception as e:
            self.logger.error(f'{self.service_name}获取记录失败，因为数据库异常，具体错误信息为：{e}', exc_info=True)
            raise ScanServiceDbError from e
