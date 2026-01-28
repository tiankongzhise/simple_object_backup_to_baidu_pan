from src.simple_object_backup_to_pan_baidu.db_service import DbService
from sqlalchemy import text

engine = DbService().get_engine()
with engine.connect() as conn:
    print("=== hash_records (all columns) ===")
    result = conn.execute(text('SELECT * FROM hash_records'))
    for row in result:
        row_dict = dict(row._mapping)
        print(f"id={row_dict.get('id')}, object_path={repr(row_dict.get('object_path'))}")
        if row_dict.get('object_path') is None:
            print("  ^^^ FOUND NULL object_path!")

    print("\n=== scan_records (check for null) ===")
    result2 = conn.execute(text('SELECT id, object_path FROM scan_records WHERE object_path IS NULL'))
    null_count = 0
    for row in result2:
        null_count += 1
        print(f"Found null object_path: id={row.id}")
    print(f"Total null object_path in scan_records: {null_count}")
