
from sqlalchemy.orm import Mapped, mapped_column, DeclarativeBase
from sqlalchemy import BigInteger, String, Text, UniqueConstraint, MetaData, Integer
from time import time_ns
from datetime import datetime
from pydantic import BaseModel
from typing import Literal

class DbMixin(object):
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

class StatusFinishedBase(DeclarativeBase):
    metadata = MetaData()



class ServiceStatusTable(DbMixin,StatusFinishedBase):
    __tablename__ = "service_status"
    service_name: Mapped[str] = mapped_column(String(30))
    is_finished: Mapped[bool] = mapped_column(default=False, nullable=False)

    __table_args__ = (UniqueConstraint('service_name', name='uix_service_name'),)


class ServiceStatusFormat(BaseModel):
    service_name: str
    is_finished: bool

class ErrorBase(DeclarativeBase):
    """Base class for other exceptions"""
    pass



class ErrorTable(DbMixin,ErrorBase):
    __tablename__ = "errors"
    service_name: Mapped[str] = mapped_column(String(32))
    error_message: Mapped[str] = mapped_column(Text)

class ErrorFormat(BaseModel):
    service_name: str
    error_message: str

class ManualReviewBase(DeclarativeBase):
    metadata = MetaData()

class ManualReviewRecords(DbMixin, ManualReviewBase):
    __tablename__ = "manual_review_records"
    host_name: Mapped[str] = mapped_column(String(255))
    object_path: Mapped[str] = mapped_column(String(255))
    object_name: Mapped[str] = mapped_column(String(255))
    object_type: Mapped[str] = mapped_column(String(15))
    object_size: Mapped[int] = mapped_column(BigInteger)
    object_item_count: Mapped[int] = mapped_column(Integer)
    scan_id: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(255))
    status: Mapped[Literal['waiting', 'processing', 'fail', 'done']
                   ] = mapped_column(String(15), default='waiting')

    __table_args__ = (
        UniqueConstraint('host_name', 'object_path', name='uix_host_name_object_path'),
        UniqueConstraint('scan_id', name='uix_scan_id'),
    )

class ManualReviewFormat(BaseModel):
    host_name: str
    object_path: str
    object_name: str
    object_type: str
    object_size: int
    object_item_count: int
    scan_id: int
    reason: str
    status: Literal['waiting', 'processing', 'fail', 'done'] = 'waiting'