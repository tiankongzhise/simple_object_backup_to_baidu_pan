from src.simple_object_backup_to_pan_baidu.object_hash_service import ObjectHashService
from src.simple_object_backup_to_pan_baidu.config import get_config
from src.simple_object_backup_to_pan_baidu.logger import logger_start, logger_shutdown
import os


def test_scan_service():
    try:
        """Test ScanService"""
        print("\n=== Testing ScanService ===")
        print("开启日志")
        logger_start()
        service = ObjectHashService()
        print("重置对象哈希表")
        service.reset_table()
        print("开始计算对象哈希值")
        service.run()
        print("对象哈希值计算完成")
        print("关闭日志")
        print("测试完成")
    except KeyboardInterrupt:
        print("测试中断")
        os._exit(0)
    except Exception as e:
        print(f"测试失败: {e}")
    finally:
        logger_shutdown()


if __name__ == "__main__":
    test_scan_service()
