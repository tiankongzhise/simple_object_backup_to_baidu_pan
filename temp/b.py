from src.simple_object_backup_to_pan_baidu.scan_service import ScanService
from src.simple_object_backup_to_pan_baidu.config import get_config
from src.simple_object_backup_to_pan_baidu.logger import logger_start,logger_shutdown
from src.simple_object_backup_to_pan_baidu.utils import reset_service_status_table
from src.simple_object_backup_to_pan_baidu.db_service import DbService

def test_scan_service():
    """Test ScanService"""
    print("\n=== Testing ScanService ===")
    print('开启日志')
    logger_start()
    db_service = DbService()
    engine = db_service.get_engine()
    reset_service_status_table(engine)
    config = get_config()
    source_object_paths = config.source_path_list
    scan_service = ScanService(source_object_paths)
    print(f'source_object_paths: {source_object_paths}')
    print('重置扫描表')
    scan_service.reset_scan_table()
    print('开始扫描')
    scan_service.start()
    print('扫描完成')
    print('关闭日志')
    logger_shutdown()
    print('测试完成')  

if __name__ == '__main__':
    test_scan_service()