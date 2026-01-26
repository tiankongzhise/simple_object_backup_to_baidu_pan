# from src.simple_object_backup_to_pan_baidu.scan_service import ScanService
from src.simple_object_backup_to_pan_baidu.config import get_config
# from src.simple_object_backup_to_pan_baidu.logger import logger_start, logger_shutdown
# from src.simple_object_backup_to_pan_baidu.utils import reset_service_status_table
from src.simple_object_backup_to_pan_baidu.db_service import DbService


def test_scan_service():
    """Test ScanService"""
    print("\n=== Testing ScanService ===")
    db_service = DbService()
    config1 = get_config()
    config2 = get_config()
    # engine = db_service.get_engine()
    # reset_service_status_table(engine)



if __name__ == "__main__":
    test_scan_service()
