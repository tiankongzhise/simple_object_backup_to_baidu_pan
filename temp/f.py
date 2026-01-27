from src.simple_object_backup_to_pan_baidu.domain import ServiceStatus
from concurrent.futures import ThreadPoolExecutor,as_completed
import logging
import time
import random

class ServiceThreadCase(object):
    def __init__(self):
        self.exector = ThreadPoolExecutor(10)
        self.status = ServiceStatus.INIT
        self.tasks = []
        self.result = {'success':[],'fail':[]}
        self.logger = logging.getLogger("service.thread_case")


    @staticmethod
    def worker(service_name,task_num,logger):
        logger.info(f'Service {service_name}:task {task_num} begin')
        time.sleep(random.randint(1,10))
        logger.info(f'Service {service_name}:task {task_num} end')
        return {'task_name': f'{service_name}:task_{task_num}', 'task_result': random.choice([True,False])}

    def process(self):
        self.logger.info('ServiceThreadCase submit')
        self.status = ServiceStatus.SUBMITTING
        with self.exector as executor:
            self.tasks = [executor.submit(self.worker,'service_thread_case',i,self.logger) for i in range(1,11)]
            self.status = ServiceStatus.SUBMITTED
            self.logger.info('ServiceThreadCase process')
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
        self.logger.info('ServiceThreadCase analyze')
        self.logger.info(f'total tasks:{len(self.tasks)},success:{len(self.result["success"])},fail:{len(self.result["fail"])}')
        self.logger.info(f'success:{self.result["success"]}')
        self.logger.info(f'fail:{self.result["fail"]}')
        self.status = ServiceStatus.DONE

    def start(self):
        self.logger.info('ServiceThreadCase start')
        self.status = ServiceStatus.START
        self.process()
        self.analyze()
    
    def stop(self):
        self.logger.info('ServiceThreadCase stop')
    
    def shutdown(self):
        self.logger.info('ServiceThreadCase shutdown')