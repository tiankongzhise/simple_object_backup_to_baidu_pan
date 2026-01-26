from pathlib import Path
from typing import TypeVar
from pydantic import BaseModel, DirectoryPath,Field
from multiprocessing import Manager
from multiprocessing.queues import Queue
from threading import Lock
import logging

class ConfigServiceError(Exception):
    """Config service error"""
class ConfigInitError(ConfigServiceError):
    """Config init error"""
class ConfigValueError(ConfigServiceError):
    """Config value error"""
class ConfigRuntimeError(ConfigServiceError):
    """Config runtime error"""


def _load_toml(toml_path:str):
    import tomllib
    from copy import deepcopy
    if toml_path is None:
        print('用户未自定义配置，使用默认配置')
        return None
    temp_path = Path(toml_path)
    if not temp_path.exists():
        print(f'用户自定义配置文件{temp_path.resolve().as_posix()}不存在，使用默认配置')
        return None
    print(f'发现用户自定义配置文件，正在加载配置文件: {toml_path}')
    with open(toml_path, "rb") as f:
        toml_data = tomllib.load(f)
    result = deepcopy(toml_data)
    for key,value in toml_data.items():
        if key not in Config.model_fields:
            raise ConfigInitError(f"Config key {key} not defined")
        if key == 'chunk_size_bytes':
            if isinstance(value, str):
                result[key] = eval(value, {'__builtins__': None}, {})
                continue
        if isinstance(value, str):
            if value == 'true':
                result[key] = True
                continue
            if value == 'false':
                result[key] = False
                continue
            if value.lower() == 'none':
                if key != 'password':
                    raise ConfigInitError(f"Config value can not be None except password, {key} is None,is not expected")
                result[key] = None
                continue
        result[key] = value
    print('配置文件加载完成,等待校验...')
    return result

def _load_env(sql_env_path:str, upload_env_path:str,*args,**kwargs):
    from dotenv import load_dotenv
    if not Path(sql_env_path).exists():
        raise ConfigInitError(f"SQL env file does not exist: {sql_env_path}")
    if not Path(upload_env_path).exists():
        raise ConfigInitError(f"Upload env file does not exist: {upload_env_path}")
    load_dotenv(sql_env_path)
    load_dotenv(upload_env_path)
    for arg_env in args:
        print(f'正在加载环境变量: {arg_env}')
        if not Path(arg_env).exists():
            raise ConfigInitError(f"Env file does not exist: {arg_env}")
        load_dotenv(arg_env)
    for kwarg_env,kwargs_env_path in kwargs.items():
        print(f'正在加载环境变量: {kwarg_env}')
        if not Path(kwargs_env_path).exists():
            raise ConfigInitError(f"Env file does not exist: {kwargs_env_path}")
        load_dotenv(kwargs_env_path)
    print('所有环境变量加载完成')

class DebugOnlyFilter(logging.Filter):
    def filter(self, record):
        return record.levelno == logging.DEBUG

class Config(BaseModel):

    # 数据库配置项
    pool_size: int = Field(default=5, description="连接池大小") # 连接池大小
    max_overflow: int = Field(default=10, description="最大溢出连接数") # 最大溢出连接数
    pool_timeout: int = Field(default=30, description="连接超时时间（秒）") # 连接超时时间（秒）
    pool_recycle: int = Field(default=3600, description="连接回收时间（秒），0表示不回收") # 连接回收时间（秒），0表示不回收
    echo: bool = Field(default=False, description="是否打印SQL语句（仅调试时使用）") # 是否打印SQL语句（仅调试时使用）
    pool_pre_ping: bool = Field(default=True, description="避免数据库连接不稳定带来的失败") # 避免数据库连接不稳定带来的失败

    # scanf 配置项
    source_path_list: list[str] = Field(default=[], description="源路径列表") # 源路径列表
    zipped_suffix: list[str] = Field(default=[
        ".zip",
        ".rar",
        ".7z",
        ".tar.gz",
        ".gz",
        ".tar.bz2",
        ".tar.xz",
        ".tgz",
        ".tar",
        ".bz2",
    ], description="压缩文件后缀列表") # 压缩文件后缀列表

    # hash计算 配置项
    directory_overcount:int = 200
    oversize:int = 20 * 1024 * 1024 # 20MB
    hash_chunk_size_bytes: int = Field(default=500 * 1024 * 1024, description="哈希计算分片大小（字节）") # 哈希计算分片大小（字节）
    algorithm_list: list[str] = Field(default=['md5', 'sha1', 'sha256'], description="哈希算法列表") # 哈希算法列表


    # 文件压缩 配置项
    compress_temp_dir: str = Field(default='./temp_compress', description="备份临时目录") # 备份临时目录
    password: str|None = Field(default=None, description="压缩密码") # 压缩密码
    compress_level: int = Field(default=0, description="压缩格式") # 压缩格式
    extract_temp_dir: str = Field(default='./temp_extract', description="解压临时目录") # 解压临时目录
    salt:dict[int, bytes] = Field(default={
        8: b"\xaa%\xec\xec[\x94\xbex",
        12: b"}y\xd5\x19A\xa2\xf6\x1b\xce\x86\x7f\x85",
        16: b"\xd1\x12_\xd7\xd7\n\x92\xfdC\x84\re\xcdxD\x0b",
    }, description="压缩使用定制化盐值,但是固定,不会随机生成,使得压缩后文件hash稳定")

    # 文件上传配置
    chunk_size_bytes: int = Field(default=20*1024*1024, description="分片大小（字节）") # 分片大小（字节）
    retry_times: int = Field(default=5, description="上传失败重试次数") # 上传失败重试次数

    # 环境变量位置
    db_env_path: str = Field(default='mysql.env', description="数据库环境变量文件路径") # 数据库环境变量文件路径
    upload_env_path: str = Field(default='baidupan.env', description="上传环境变量文件路径") # 上传环境变量文件路径

    # 用户定制化配置文件路径
    toml_path: str = Field(default='config.toml', description="用户定制化配置文件路径") # 用户定制化配置文件路径
    logger_setting: dict = Field(default={
        'version': 1,
        'disable_existing_loggers': False,
        'filters': {
            'debug_only_filter': {
                '()': DebugOnlyFilter
            }
        },
        'formatters': {
            'service': {
                'class': 'logging.Formatter',
                'format': '%(asctime)s %(name)-15s %(levelname)-8s %(processName)-10s %(threadName)-10s %(message)s'
            },
            'debug': {
                'class': 'logging.Formatter',
                'format': '%(asctime)s %(name)-15s %(pathname)s %(filename)s %(funcName)s %(lineno)s %(levelname)-8s %(processName)-10s %(threadName)-10s %(message)s'
            },
            'main': {
                'class': 'logging.Formatter',
                'format': '%(asctime)s %(name)-15s %(levelname)-8s %(message)s'
            },
        },
        'handlers': {
            'console_debug': {
                'class': 'logging.StreamHandler',
                'level': 'INFO',
                'formatter': 'debug',
            },
            'console_service': {
                'class': 'logging.StreamHandler',
                'level': 'INFO',
                'formatter': 'service',
            },
            'console_main': {
                'class': 'logging.StreamHandler',
                'level': 'INFO',
                'formatter': 'main',
            },
            'size_rotate_debug': {
                'class': 'logging.handlers.RotatingFileHandler',
                'filename': './log/logger_rotate_debug.log',
                'maxBytes': 5 * 1024 * 1024,  # 5MB
                'backupCount': 10,
                'formatter': 'debug',
                'encoding': 'utf-8',
            },
            'size_rotate_service': {
                'class': 'logging.handlers.RotatingFileHandler',
                'filename': './log/logger_rotate_service.log',
                'maxBytes': 5 * 1024 * 1024,  # 5MB
                'backupCount': 10,
                'formatter': 'service',
                'encoding': 'utf-8',
            },
            'size_rotate_main': {
                'class': 'logging.handlers.RotatingFileHandler',
                'filename': './log/logger_rotate_main.log',
                'maxBytes': 5 * 1024 * 1024,  # 5MB
                'backupCount': 10,
                'formatter': 'main',
                'encoding': 'utf-8',
            },
            # 按时间轮转的处理器
            'time_rotate_debug': {
                'class': 'logging.handlers.TimedRotatingFileHandler',
                'filename': './log/logger_rotate_debug_time.log',
                'when': 'midnight',
                'interval': 1,
                'backupCount': 30,
                'formatter': 'debug',
                'encoding': 'utf-8',
            },
            'time_rotate_service': {
                'class': 'logging.handlers.TimedRotatingFileHandler',
                'filename': './log/logger_rotate_service_time.log',
                'when': 'midnight',
                'interval': 1,
                'backupCount': 30,
                'formatter': 'service',
                'encoding': 'utf-8',
            },
            'time_rotate_main': {
                'class': 'logging.handlers.TimedRotatingFileHandler',
                'filename': './log/logger_rotate_main_time.log',
                'when': 'midnight',
                'interval': 1,
                'backupCount': 30,
                'formatter': 'main',
                'encoding': 'utf-8',
            },
            'errors': {
                'class': 'logging.FileHandler',
                'filename': './log/errors.log',
                'mode': 'a',
                'level': 'ERROR',
                'formatter': 'debug',
            },
            'debug_only_console': {
                'class': 'logging.StreamHandler',
                'level': 'DEBUG',
                'formatter': 'debug',
                'filters': ['debug_only_filter']
            },
            'debug_only_file': {
                'class': 'logging.FileHandler',
                'filename': './log/debug.log',
                'mode': 'a',
                'level': 'DEBUG',
                'formatter': 'debug',
                'filters': ['debug_only_filter']
            },
        },
        'loggers': {
            'main': {
                'handlers': ['console_main','time_rotate_main','errors','debug_only_file'],
                'level': 'DEBUG',
                # 'propagate': False,
            },
        },
        'root': {
                'handlers': ['console_service','time_rotate_service','errors','debug_only_file'],
                'level': 'DEBUG',
                # 'propagate': False,
            },
    }, description="日志配置") # 日志配置


__config_instance: Config = None # type: ignore
__logger_queue_instance: Queue = None # type: ignore
__config_lock = Lock() # 配置锁，确保线程安全

def get_logger_queue() -> Queue:
    """获取日志队列实例，延迟初始化以避免在模块导入时创建进程"""
    global __logger_queue_instance
    if __logger_queue_instance is None:
        __logger_queue_instance = Manager().Queue()
    return __logger_queue_instance

def get_config():

    global __config_instance, __config_lock
    with __config_lock: # 加锁确保线程安全
        if __config_instance is None:
            temp_config = Config()
            config_data = _load_toml(temp_config.toml_path)
            if config_data:
                __config_instance = Config(**config_data)
            else:
                __config_instance = temp_config
            _load_env(temp_config.db_env_path, temp_config.upload_env_path)
    return __config_instance

if __name__ == "__main__":
    config = get_config()
    print(config.pool_size)
    # print(hasattr(Config, 'source_path_list'))

