from logging import Logger
import logging.handlers


def logger_configurer(q,logger:Logger|None = None):
    
    h = logging.handlers.QueueHandler(q)  # 只需要一个处理器
    root = logger or logging.getLogger()
    root.addHandler(h)
    # 发送所有消息，用于演示；未应用其他层级或过滤逻辑。
    root.setLevel(logging.DEBUG)