from concurrent.futures import ProcessPoolExecutor, as_completed
from src.simple_object_backup_to_pan_baidu.utils import WorkerMixin
from src.simple_object_backup_to_pan_baidu.logger import logger_start, logger_shutdown
import logging
import random


class ServiceA(WorkerMixin):
    def __init__(self):
        super().__init__()
        self.logger = logging.getLogger('service_a')

    def _do_work(self):
        levels = [logging.DEBUG, logging.INFO, logging.WARNING, logging.ERROR,
                  logging.CRITICAL]

        for i in range(100):
            lvl = random.choice(levels)
            self.logger.log(lvl, f'ServiceA Message no. {i}')

    def start(self):
        logger_start()
        self.logger.info('ServiceA started')
        with ProcessPoolExecutor(max_workers=10) as executor:
            workers = [executor.submit(self.worker_process) for _ in range(5)]
            for wp in as_completed(workers):
                wp.result()
        logger_shutdown()


class ServiceB(WorkerMixin):
    def __init__(self):
        super().__init__()
        self.logger = logging.getLogger('service_b')

    def _do_work(self):
        levels = [logging.DEBUG, logging.INFO, logging.WARNING, logging.ERROR,
                  logging.CRITICAL]

        for i in range(100):
            lvl = random.choice(levels)
            self.logger.log(lvl, f'ServiceB Message no. {i}')

    def start(self):
        logger_start()
        self.logger.info('ServiceB started')
        with ProcessPoolExecutor(max_workers=10) as executor:
            workers = [executor.submit(self.worker_process) for _ in range(5)]
            for wp in as_completed(workers):
                wp.result()
        logger_shutdown()


def test2():
    sa = ServiceA()
    sb = ServiceB()
    sa.start()
    sb.start()


if __name__ == '__main__':
    test2()
