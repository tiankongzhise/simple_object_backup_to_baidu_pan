import pyzipper
import hashlib
import asyncio
import aiofiles
import time
import pathlib

async def zip_file(file_path, zip_path, password):
    # 将同步的压缩函数封装起来，在线程中执行
    def _sync_zip():
        with pyzipper.AESZipFile(zip_path, 'w', compression=0, encryption=pyzipper.WZ_AES) as zf:
            zf.setpassword(password)
            zf.write(file_path, arcname=file_path.name)
        return zip_path

    # 使用 asyncio.to_thread 来避免阻塞
    return await asyncio.to_thread(_sync_zip)

async def calculate_hash(file_path):
    hash_object = hashlib.sha256()
    # 使用 aiofiles 异步打开文件
    async with aiofiles.open(file_path, 'rb') as f:
        # 异步读取数据块
        while chunk := await f.read(50*1024*1024):
            hash_object.update(chunk)
    return hash_object.hexdigest()

async def test_sync(file_path, zip_path, password):
    print('await zip_file')
    zip_result = await zip_file(file_path, zip_path, password)
    print(f'zip_result: {zip_result}')
    print('await calculate_hash')
    hash_result = await calculate_hash(file_path)
    print(f'hash_result: {hash_result}')


async def test_async(file_path, zip_path, password):
    print('create_task')
    task1 = asyncio.create_task(zip_file(file_path, zip_path, password))
    task2 = asyncio.create_task(calculate_hash(file_path))
    print('await asyncio.gather(task1, task2)')
    result = await asyncio.gather(task1, task2)
    for index, res in enumerate(result):
        print(f'result[{index}]: {res}')
    print('finish')


def test1(file_path, zip_path, password):
    print('test1 is run!')
    sync_start = time.time()
    asyncio.run(test_sync(file_path, zip_path, password))
    sync_end = time.time()
    print(f'sync_cost: {sync_end - sync_start}')

def test2(file_path, zip_path, password):
    print('test2 is run!')
    async_start = time.time()
    asyncio.run(test_async(file_path, zip_path, password))
    async_end = time.time()
    print(f'async_cost: {async_end - async_start}')

def main():
    file_path = pathlib.Path(r'e:\\windows\\zh-cn_windows_11_business_editions_version_21h2_updated_aug_2022_x64_dvd_01ab3d1a.iso')
    zip_path1 = pathlib.Path(r'D:\backup_compress\windows1.zip')
    zip_path2 = pathlib.Path(r'D:\backup_compress\windows2.zip')
    password = b'H_x123456789'
    test1(file_path, zip_path1, password)
    print('-*50')
    test2(file_path, zip_path2, password)
if __name__ == '__main__':
    main()
