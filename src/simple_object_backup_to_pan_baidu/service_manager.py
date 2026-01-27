import time
from threading import Thread,Lock
from .domain import ServiceBase,ServiceStatus
import logging


class ServiceManager(object):
    def __init__(self):
        self.services = {}
        self.lock = Lock()
        self.running_services = []
        self.service_started = False
        self.threads = {}
        self.logger = logging.getLogger("manager.service_manager")
    
    def register_service(self,service_name:str,service:ServiceBase):
        self.logger.debug(f"register service:{service_name}")
        self.services[service_name] = service
    
    def start_all_service(self):
        """启动所有服务（非阻塞）"""
        with self.lock:
            for name, service in self.services.items():
                try:
                    self.logger.debug(f"start service:{name}")                   
                    service_thread = Thread(target=service.start, 
                                            name=f"service_{name}_thread",
                                            daemon=True)
                    service_thread.start()
                    self.logger.debug(f"start service:{name} success")
                    self.threads[name] = service_thread
                    self.running_services.append(name)
                except Exception as e:
                    self.logger.error(f"error start service:{name}:{e}",exc_info=True) 
                    raise  
            self.service_started = True
            self.logger.debug(f"start all service:{','.join(self.running_services)}")
    
    def wait_for_all_service(self):
        """等待所有服务完成（阻塞）"""
        while True:
            # 等待全部服务启动
            if not self.service_started:
                self.logger.info(f"wait for all service start,started service:{','.join(self.running_services)},after 1 sceond,will check again")
                time.sleep(1)
                continue
            # 检查是否还有服务在运行
            if len(self.running_services) == 0:
                self.logger.info(f"all service finished")
                break

            running_services = self.running_services.copy()
            self.logger.debug(f'check running services:{','.join(running_services)}')
            for name in running_services:
                service = self.services[name]
                if service.status == ServiceStatus.DONE:
                    self.running_services.remove(name)
                    self.logger.info(f"service {name} done")
                elif service.status == ServiceStatus.FAIL:
                    self.running_services.remove(name)
                    self.logger.warning(f"service {name} failed")
            self.logger.debug(f'recheck running services after 1 sceond')
            time.sleep(1)