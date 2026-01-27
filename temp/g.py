from src.simple_object_backup_to_pan_baidu.domain import ServiceStatus
from src.simple_object_backup_to_pan_baidu.config import get_logger_queue
from concurrent.futures import ProcessPoolExecutor, as_completed
import logging
import time
import random
import logging.handlers




class ServiceProcessCase(object):
    def __init__(self):
        self.exector = ProcessPoolExecutor(2, initializer=self._init_worker, initargs=(get_logger_queue(),))
        self.status = ServiceStatus.INIT
        self.tasks = []
        self.result = {'success': [], 'fail': []}
        self.logger = logging.getLogger("service.process_case")

    @staticmethod
    def _init_worker(queue):
        """每个子进程启动时调用，配置日志队列"""
        h = logging.handlers.QueueHandler(queue)
        root = logging.getLogger()
        root.addHandler(h)
        root.setLevel(logging.DEBUG)

    @staticmethod
    def worker(service_name, task_num):
        work_logger = logging.getLogger("service.process_case.worker")
        work_logger.debug(f'Service {service_name}:task {task_num} begin')
        time.sleep(random.randint(1, 10))
        work_logger.debug(f'Service {service_name}:task {task_num} end')
        return {'task_name': f'{service_name}:task_{task_num}', 'task_result': random.choice([True, False])}

    def process(self):
        self.logger.info('ServiceProcessCase submit')
        self.status = ServiceStatus.SUBMITTING
        with self.exector as executor:
            self.tasks = [executor.submit(self.worker,'service_process_case',i) for i in range(1,4)]
            self.status = ServiceStatus.SUBMITTED
            self.logger.info('ServiceProcessCase process')
            self.status = ServiceStatus.PROCESSING
            for task in as_completed(self.tasks):
                result = task.result()
                self.logger.info(result)
                if result['task_result']:
                    self.result['success'].append(result['task_name'])
                else:
                    self.result['fail'].append(result['task_name'])
            self.status = ServiceStatus.PROCESSED
    def analyze(self):
        self.logger.info('ServiceProcessCase analyze')
        self.logger.info(f'total tasks:{len(self.tasks)},success:{len(self.result["success"])},fail:{len(self.result["fail"])}')
        self.logger.info(f'success:{self.result["success"]}')
        self.logger.info(f'fail:{self.result["fail"]}')
        self.status = ServiceStatus.DONE

    def start(self):
        self.logger.info('ServiceProcessCase start')
        self.status = ServiceStatus.START
        self.process()
        self.analyze()
    
    def stop(self):
        self.logger.info('ServiceProcessCase stop')
    
    def shutdown(self):
        self.logger.info('ServiceProcessCase shutdown')