
from src.simple_object_backup_to_pan_baidu.service_manager import ServiceManager
from src.simple_object_backup_to_pan_baidu.hash_service import HashService
from src.simple_object_backup_to_pan_baidu.scan_service import ScanService
from src.simple_object_backup_to_pan_baidu.utils.test_utils import reset_all_records


def simpe_case(service_register_factory:dict):
    print("simpe case")
    # logger_service = LoggerService()
    # print("logger init")
    # logger_service.start()
    # print("logger start")
    sm = ServiceManager()
    print("service manager init")
    for service_name,service_class in service_register_factory.items():
        service = service_class()
        sm.register_service(service_name,service)
    print("service register")
    sm.start_all_service()
    print("service started")
    sm.wait_for_all_service()
    print("service finished")
    # logger_service.shutdown()
    # print("logger shutdown")

if __name__ == "__main__":
    reset_all_records()
    simpe_case({
        "scan_service": ScanService,
        'hash_service': HashService
    })
