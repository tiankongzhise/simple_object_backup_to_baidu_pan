import signal
import threading
import time
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from typing import List, Dict
import logging

# 配置日志
logging.basicConfig(level=logging.INFO, 
                   format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class GracefulShutdownManager:
    """优雅关闭管理器"""
    
    def __init__(self):
        # 存储所有需要关闭的资源
        self.services: Dict[str, 'BaseService'] = {}
        self.thread_pools: List[ThreadPoolExecutor] = []
        self.shutdown_event = threading.Event()
        self.shutdown_timeout = 30  # 秒
        
        # 注册信号处理器
        signal.signal(signal.SIGINT, self._signal_handler)   # Ctrl+C
        signal.signal(signal.SIGTERM, self._signal_handler)  # kill命令
        
    def _signal_handler(self, signum, frame):
        """信号处理函数"""
        logger.info(f"收到关闭信号 {signal.Signals(signum).name}")
        self.shutdown_event.set()
        
    def register_service(self, service_name: str, service: 'BaseService'):
        """注册服务"""
        self.services[service_name] = service
        
    def register_thread_pool(self, pool: ThreadPoolExecutor):
        """注册线程池"""
        self.thread_pools.append(pool)
        
    def wait_for_shutdown(self):
        """等待关闭信号"""
        try:
            # 主线程等待关闭信号
            while not self.shutdown_event.wait(timeout=1):
                # 可以在这里添加健康检查
                pass
                
            # 收到关闭信号，开始优雅关闭
            self.graceful_shutdown()
            
        except KeyboardInterrupt:
            # 再次按Ctrl+C
            logger.warning("强制关闭")
            self.force_shutdown()
            
    def graceful_shutdown(self):
        """优雅关闭所有服务"""
        logger.info("开始优雅关闭...")
        
        # 1. 先停止接受新任务
        self._stop_accepting_new_tasks()
        
        # 2. 通知服务准备关闭
        self._notify_services_shutdown()
        
        # 3. 等待进行中的任务完成
        self._wait_for_tasks_completion()
        
        # 4. 关闭所有线程池
        self._shutdown_thread_pools()
        
        # 5. 清理资源
        self._cleanup_resources()
        
        logger.info("优雅关闭完成")
        
    def _stop_accepting_new_tasks(self):
        """停止接受新任务"""
        logger.info("停止接受新任务...")
        for service in self.services.values():
            service.stop_accepting_tasks()
            
    def _notify_services_shutdown(self):
        """通知服务准备关闭"""
        logger.info("通知服务准备关闭...")
        for name, service in self.services.items():
            try:
                service.prepare_shutdown()
                logger.info(f"服务 {name} 已准备关闭")
            except Exception as e:
                logger.error(f"服务 {name} 准备关闭时出错: {e}")
                
    def _wait_for_tasks_completion(self):
        """等待任务完成"""
        logger.info("等待进行中的任务完成...")
        
        start_time = time.time()
        all_futures = []
        
        # 收集所有服务的任务
        for name, service in self.services.items():
            try:
                futures = service.get_pending_futures()
                all_futures.extend(futures)
                logger.info(f"服务 {name} 有 {len(futures)} 个任务进行中")
            except Exception as e:
                logger.error(f"获取服务 {name} 的任务时出错: {e}")
                
        if not all_futures:
            return
            
        # 等待任务完成，但有超时
        try:
            done, not_done = wait(
                all_futures, 
                timeout=self.shutdown_timeout - 5,  # 留5秒给其他清理
                return_when=FIRST_COMPLETED
            )
            
            elapsed = time.time() - start_time
            logger.info(f"等待任务完成，已等待 {elapsed:.1f} 秒")
            logger.info(f"已完成 {len(done)} 个任务，剩余 {len(not_done)} 个")
            
        except Exception as e:
            logger.error(f"等待任务完成时出错: {e}")
            
    def _shutdown_thread_pools(self):
        """关闭所有线程池"""
        logger.info("关闭线程池...")
        
        for i, pool in enumerate(self.thread_pools):
            try:
                logger.info(f"关闭线程池 {i+1}/{len(self.thread_pools)}")
                pool.shutdown(wait=True, timeout=5)
            except Exception as e:
                logger.error(f"关闭线程池 {i} 时出错: {e}")
                
    def _cleanup_resources(self):
        """清理资源"""
        logger.info("清理资源...")
        for name, service in self.services.items():
            try:
                service.cleanup()
                logger.info(f"服务 {name} 资源已清理")
            except Exception as e:
                logger.error(f"清理服务 {name} 资源时出错: {e}")
                
    def force_shutdown(self):
        """强制关闭"""
        logger.warning("开始强制关闭...")
        
        for pool in self.thread_pools:
            try:
                pool.shutdown(wait=False, cancel_futures=True)
            except:
                pass
                
        logger.warning("强制关闭完成")