from .config import get_config,Config
from sqlalchemy import create_engine
import os

class DbServiceError(Exception):
    """DbService 错误类"""

class DbEngineConnectionError(DbServiceError):
    """DbEngine 连接错误类"""

class DbService:
    _instance = None
    is_initialized = False
    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, config: Config|None = None):
        if self.is_initialized:
            return
        self.config = config or get_config()
    
    def create_engine(self):
        host = os.getenv("DB_HOST", "localhost")
        port = os.getenv("DB_PORT", 3306)
        user = os.getenv("DB_USER", "root")
        password = os.getenv("DB_PASSWORD", "")
        database = os.getenv("DB_DATABASE", "test")
        engine_params = {
            "pool_size": self.config.pool_size,
            "max_overflow": self.config.max_overflow,
            "pool_timeout": self.config.pool_timeout,
            "pool_recycle": self.config.pool_recycle,
            "echo": self.config.echo,
            "pool_pre_ping": self.config.pool_pre_ping,
        }
        return create_engine(f"mysql+pymysql://{user}:{password}@{host}:{port}/{database}", **engine_params)


    def get_engine(self):
        try:
            engine = self.create_engine()
            engine.connect()
            return engine
        except DbEngineConnectionError as e:
            raise e

if __name__ == "__main__":
    db_service = DbService()
    engine = db_service.get_engine()
    print(engine)