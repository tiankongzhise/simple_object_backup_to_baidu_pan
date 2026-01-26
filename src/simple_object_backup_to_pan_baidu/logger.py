from multiprocessing import Queue
import logging
from logging import config
import logging.handlers
import threading
from pathlib import Path
from .config import get_config, get_logger_queue

def _logger_thread(q, listener_configurer):
    listener_configurer(q)
    while True:
        record = q.get()
        if record is None:
            break
        logger = logging.getLogger(record.name)
        logger.handle(record)

def _listener_configurer(q):
    temp_config = get_config()
    for logger_handler in temp_config.logger_setting['handlers'].values():
        if 'filename' in logger_handler:
            temp_path = Path(logger_handler['filename'])
            temp_path.parent.mkdir(parents=True, exist_ok=True)
    config.dictConfig(get_config().logger_setting)

_simple_object_backup_to_pan_baidu_logger_listener: threading.Thread|None = None 

def logger_start():
    global _simple_object_backup_to_pan_baidu_logger_listener
    if _simple_object_backup_to_pan_baidu_logger_listener:
        return _simple_object_backup_to_pan_baidu_logger_listener

    q = get_logger_queue()
    _simple_object_backup_to_pan_baidu_logger_listener = threading.Thread(target=_logger_thread, args=(q, _listener_configurer,))
    _simple_object_backup_to_pan_baidu_logger_listener.start()

def logger_shutdown():
    global _simple_object_backup_to_pan_baidu_logger_listener
    if _simple_object_backup_to_pan_baidu_logger_listener:
        q = get_logger_queue()
        q.put(None)
        _simple_object_backup_to_pan_baidu_logger_listener.join()
        _simple_object_backup_to_pan_baidu_logger_listener = None
