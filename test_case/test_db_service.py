from src.simple_object_backup_to_pan_baidu.db_service import DbService


if __name__ == "__main__":
    db_service = DbService()
    engine = db_service.get_engine()
    print(engine)
