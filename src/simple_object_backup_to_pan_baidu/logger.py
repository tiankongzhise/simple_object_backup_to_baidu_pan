from sqlalchemy.util import NoneType
from .config import get_config
from logging import config
import logging
from multiprocessing import Queue
from threading import Thread
from pathlib import Path


class LoggerService:
    __instance = None
    _is_initialized = False
    _is_started = False
    _is_stopped = False

    def __new__(cls):
        if cls.__instance is None:
            cls.__instance = super().__new__(cls)
        return cls.__instance
    def __init__(self):
        if self._is_initialized:
            return
        self._is_initialized = True
        self.logger_setting = get_config().logger_setting
        self.queue = Queue()

    def load_logger_setting(self):
        for handler in self.logger_setting['handlers'].values():
            if 'filename' in handler:
                temp_path = Path(handler['filename'])
                temp_path.parent.mkdir(parents=True, exist_ok=True)
        config.dictConfig(self.logger_setting)

    def start(self):
        self.load_logger_setting()
        self.logger_thread = Thread(target=self.worker)
        self.logger_thread.start()
        self._is_started = True

    def worker(self):
        while True:
            record = self.queue.get()
            if record is None:
                break
            logger = logging.getLogger(record.name)
            logger.handle(record)

    def stop(self):
        self.queue.put(None)
        self.logger_thread.join(timeout=5)
        self.queue.close()
        self._is_stopped = True
    
    def get_logger(self, name):
        return logging.getLogger(name)

    def __del__(self):
        if not self._is_stopped:
            self.stop()


def get_logger(name:str|None = None):
    logger = LoggerService()
    if not logger._is_started:
        logger.start()
    return logger.get_logger(name)

def stop_logger():
    logger = LoggerService()
    if logger._is_started and (not logger._is_stopped):
        logger.stop()



if __name__ == '__main__':
    get_logger()