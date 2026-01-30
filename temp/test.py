from src.simple_object_backup_to_pan_baidu.centralized_fingerprint_service import HashCalculateCore
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor,ProcessPoolExecutor,as_completed
import time
from tqdm import tqdm 

def get_files():
    dir_path = Path(r'E:\迅雷下载')
    return sorted([item for item in dir_path.iterdir()])

def _fingerprint_process_worker(path_str):
    core = HashCalculateCore()
    return core.calculate_fingerprint(Path(path_str))

def _full_hash_process_worker(path_str):
    core = HashCalculateCore()
    return core.calculate_full_hash(Path(path_str))

def calculate_fingerprint_sig_model(file_list):
    beg_time = time.time()
    print("calculate_fingerprint_sig_model beg")
    core = HashCalculateCore()
    for item in tqdm(file_list, desc="Calculating fingerprints", unit="object"):
        core.calculate_fingerprint(item)
    end_time = time.time()
    total_cost = (end_time - beg_time)
    print('calculate_fingerprint_sig_model end')
    # 显示总费时多少秒，保留2位小数
    print(f"\n calculate_fingerprint_sig_model Total time taken: {total_cost:.2f} seconds\n")


def calculate_fingerprint_thread_pool(file_list, max_workers=8):
    beg_time = time.time()
    print("calculate_fingerprint_thread_pool beg")
    core = HashCalculateCore()
    results = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_item = {executor.submit(core.calculate_fingerprint, item): item for item in file_list}
        for future in tqdm(as_completed(future_to_item), total=len(file_list), desc="ThreadPool fingerprints", unit="object"):
            _ = future.result()
    end_time = time.time()
    total_cost = (end_time - beg_time)
    print('calculate_fingerprint_thread_pool end')
    print(f"\n calculate_fingerprint_thread_pool Total time taken: {total_cost:.2f} seconds\n")

def calculate_fingerprint_process_pool(file_list, max_workers=8):
    from multiprocessing import get_context

    beg_time = time.time()
    print("calculate_fingerprint_process_pool beg")
    with get_context("spawn").Pool(processes=max_workers) as pool:
        for _ in tqdm(pool.imap_unordered(_fingerprint_process_worker, [str(p) for p in file_list]), total=len(file_list), desc="ProcessPool fingerprints", unit="object"):
            pass
    end_time = time.time()
    total_cost = (end_time - beg_time)
    print('calculate_fingerprint_process_pool end')
    print(f"\n calculate_fingerprint_process_pool Total time taken: {total_cost:.2f} seconds\n")

def calculate_full_hash_thread_pool(file_list, max_workers=8):
    beg_time = time.time()
    print("calculate_full_hash_thread_pool beg")
    core = HashCalculateCore()
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_item = {executor.submit(core.calculate_full_hash, item): item for item in file_list}
        for future in tqdm(as_completed(future_to_item), total=len(file_list), desc="ThreadPool hash", unit="object"):
            _ = future.result()
    end_time = time.time()
    total_cost = (end_time - beg_time)
    print('calculate_full_hash_thread_pool end')
    print(f"\n calculate_full_hash_thread_pool Total time taken: {total_cost:.2f} seconds\n")

def calculate_full_hash_process_pool(file_list, max_workers=8):
    beg_time = time.time()
    print("calculate_full_hash_process_pool beg")
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        executor.map(_full_hash_process_worker,file_list)
    end_time = time.time()
    total_cost = (end_time - beg_time)
    print('calculate_full_hash_process_pool end')
    print(f"\n calculate_full_hash_process_pool Total time taken: {total_cost:.2f} seconds\n")



def calculate_full_hash_sig_model(file_list):
    beg_time = time.time()
    print("calculate_full_hash_sig_model beg")
    core = HashCalculateCore()
    for item in tqdm(file_list, desc="Calculating hash", unit="object"):
        core.calculate_full_hash(item)
    end_time = time.time()
    total_cost = (end_time - beg_time)
    print('calculate_full_hash_sig_model end')
    # 显示总费时多少秒，保留2位小数
    print(f"\n calculate_full_hash_sig_model Total time taken: {total_cost:.2f} seconds\n")



def compare_fingerprint(file_list):
    calculate_fingerprint_sig_model(file_list)
    calculate_fingerprint_process_pool(file_list)
    calculate_fingerprint_thread_pool(file_list)

def compare_full_hash(file_list):
    # calculate_full_hash_sig_model(file_list)
    # calculate_full_hash_process_pool(file_list,4)
    # calculate_full_hash_thread_pool(file_list,4)

if __name__ == '__main__':
    file_list = get_files()
    # compare_fingerprint(file_list)
    compare_full_hash(file_list)