from src.simple_object_backup_to_pan_baidu.hash_service import HashRecords
from src.simple_object_backup_to_pan_baidu.scan_service import ScanRecords
from src.simple_object_backup_to_pan_baidu.service_manager import ServiceStatusTable, ErrorTable, ManualReviewRecords
from src.simple_object_backup_to_pan_baidu.db_service import DbService

def reset_scan_service_records():
    db = DbService()
    engine = db.get_engine()
    print("reset scan service records")
    HashRecords.metadata.drop_all(bind=engine)
    ScanRecords.metadata.create_all(bind=engine)
    print("reset scan service records done")

def reset_hash_service_records():
    db = DbService()
    engine = db.get_engine()
    print("reset hash service records")
    ScanRecords.metadata.drop_all(bind=engine)
    HashRecords.metadata.create_all(bind=engine)
    print("reset hash service records done")

def reset_service_manager_records():
    db = DbService()
    engine = db.get_engine()
    print("reset service manager records")
    ServiceStatusTable.metadata.drop_all(bind=engine)
    ServiceStatusTable.metadata.create_all(bind=engine)
    ErrorTable.metadata.drop_all(bind=engine)
    ErrorTable.metadata.create_all(bind=engine)
    ManualReviewRecords.metadata.drop_all(bind=engine)
    ManualReviewRecords.metadata.create_all(bind=engine)
    print("reset service manager records done")

def reset_all_records():
    try:
        print("reset all records")
        reset_scan_service_records()
        reset_hash_service_records()
        reset_service_manager_records()
        print("reset all records done")
    except Exception as e:
        print(e)
