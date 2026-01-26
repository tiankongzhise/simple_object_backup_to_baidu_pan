from sqlalchemy.orm import Session
from sqlalchemy import Integer, String, Text, create_engine, Column, MetaData, Table, select, insert, update, delete
from concurrent.futures import ProcessPoolExecutor
from .db_service import DbService
from .logger_backup import get_logger

class ObjectHashServiceError(Exception):
    """Base class for Object Hash Service errors."""


class ObjectHashService:
    def __init__(self):
        self.logger = get_logger(__name__)
        self.db_engine = DbService().get_engine()
