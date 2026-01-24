import pyzipper
import hashlib
import time
import pathlib
from concurrent.futures import ProcessPoolExecutor, as_completed

def zip_file(file_path, zip_path, password):
    with pyzipper.AESZipFile(zip_path, 'w', compression=pyzipper.ZIP_DEFLATED, compresslevel=0, encryption=pyzipper.WZ_AES) as zf:
        zf.setpassword(password)
        zf.write(file_path, arcname=file_path.name)
    return zip_path

def hash_file(file_path):
    hash_object = hashlib.sha256()
    with open(file_path, 'rb') as f:
        while chunk := f.read(50*1024*1024):
            hash_object.update(chunk)
    return hash_object.hexdigest()

def test_zip_and_hash_file(file_path, zip_path, password):
    print("Starting zip and hash file...")
    print('Zipping file...')
    zip_result = zip_file(file_path, zip_path, password)
    print(f'zip result: {zip_result}')
    print('Hashing file...')
    hash_result = hash_file(file_path)
    print(f'hash result: {hash_result}')
    print("Finished zip and hash file.")



def test_zip_and_hash_file_process(file_path, zip_path, password):
    print("Starting test zip and hash file process...")
    
    with ProcessPoolExecutor(max_workers=2) as executor:
        # 提交任务
        print("Submitting tasks to process pool...")
        future_zip = executor.submit(zip_file, file_path, zip_path, password)
        future_hash = executor.submit(hash_file, file_path)
        
        # 创建future到任务名的映射
        futures_dict = {
            future_zip: "zip",
            future_hash: "hash"
        }
        
        # 存储结果
        results = {}
        
        print("Waiting for tasks to complete...")
        # 按照完成顺序处理结果
        for future in as_completed(futures_dict, timeout=300):
            task_name = futures_dict[future]
            try:
                result = future.result()
                print(f"{task_name.capitalize()} task completed: {result}")
                results[task_name] = result
            except Exception as e:
                print(f"{task_name.capitalize()} task failed: {e}")
                results[task_name] = None
    
    print("Finished test zip and hash file process.")
    return results.get("zip"), results.get("hash")


def test1(file_path, zip_path, password):
    print('test1 is run!')
    sync_start = time.time()
    test_zip_and_hash_file(file_path, zip_path, password)
    sync_end = time.time()
    print(f'no thread_cost: {sync_end - sync_start}')

def test2(file_path, zip_path, password):
    print('test2 is run!')
    async_start = time.time()
    test_zip_and_hash_file_process(file_path, zip_path, password)
    async_end = time.time()
    print(f'thread_cost: {async_end - async_start}')


def main():
    file_path = pathlib.Path(r'e:\\windows\\zh-cn_windows_11_business_editions_version_21h2_updated_aug_2022_x64_dvd_01ab3d1a.iso')
    zip_path1 = pathlib.Path(r'D:\backup_compress\windows1.zip')
    zip_path2 = pathlib.Path(r'D:\backup_compress\windows2.zip')
    password = b'H_x123456789'
    # test1(file_path, zip_path1, password)
    print('-*50')
    test2(file_path, zip_path2, password)
if __name__ == '__main__':
    main()
