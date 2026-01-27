from pathlib import Path
from logging import config
import logging
import threading
from .config import get_config,get_logger_queue
from .domain import ServiceStatus

class LoggerService:
    _instance = None
    _init = False

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if self._init:
            return
        self._init = True
        self.queue = get_logger_queue()
        self.config = get_config().logger_setting
        self.status = ServiceStatus.INIT
    
    def set_logger_handler(self):
        for logger_handler in self.config['handlers'].values():
            if 'filename' in logger_handler:
                temp_path = Path(logger_handler['filename'])
                temp_path.parent.mkdir(parents=True, exist_ok=True)
        config.dictConfig(self.config)

    @staticmethod
    def worker(q):
        while True:
            record = q.get()
            if record is None:
                break
            logger = logging.getLogger(record.name)
            logger.handle(record)

    def process(self):
        self.status = ServiceStatus.PROCESSING
        thread = threading.Thread(target=self.worker,args=(self.queue,),daemon=True)
        thread.start()
        self.status = ServiceStatus.PROCESSED
        return thread

    def start(self):
        self.status = ServiceStatus.START
        self.set_logger_handler()
        self.thread = self.process()



    def stop(self):
        self.queue.put(None)
        self.thread.join()
    
    def shutdown(self):
        self.queue.put_nowait(None)
        self.thread.join()
