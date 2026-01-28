class UtilsError(Exception):
    """Base class for utils errors"""

class RetryError(UtilsError):
    """Error raised when a function call is retried too many times"""
