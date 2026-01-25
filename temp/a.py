from src.simple_object_backup_to_pan_baidu.logger import get_logger, shutdown_logger_service


if __name__ == '__main__':
    logger1 = get_logger(__name__)
    logger2 = get_logger()
    logger3 = get_logger("logger3")

    logger1.info("This is an info message")
    logger2.info("This is an info message")
    logger3.info("This is an info message")

    logger1.debug("This is a debug message")
    logger2.debug("This is a debug message")
    logger3.debug("This is a debug message")

    logger1.error("This is an error message")
    logger2.error("This is an error message")
    logger3.error("This is an error message")

    logger1.stop()
    logger2.stop()
    logger3.stop()

    logger1.info("This is an info message after stop logger1")
    logger2.info("This is an info message after stop logger2")
    logger3.info("This is an info message after stop logger3")

    shutdown_logger_service()
