from src.simple_object_backup_to_pan_baidu.scan_service import ScanService
from src.simple_object_backup_to_pan_baidu.config import get_config


def main():
    scan_service = None
    try:
        config = get_config()
        scan_service = ScanService(config.source_path_list)
        scan_service.reset_scan_table()
        scan_service.start()
    except KeyboardInterrupt as e:
        print("KeyboardInterrupt")
        if scan_service:
            scan_service.stop()
    except Exception as e:
        print(f"Error: {e}")
        if scan_service:
            scan_service.stop()
if __name__ == "__main__":
    main()
