from typing import Protocol
from dataclasses import dataclass

@dataclass
class ServiceStatus:
    INIT = 1
    START = 2
    SUBMITTING = 3
    SUBMITTED = 4
    PROCESSING = 5
    PROCESSED = 6
    DONE = 7
    FAIL = 8

class ServiceBase(Protocol):
    def start(self):
        pass
    def process(self):
        pass
    @staticmethod
    def worker(*args,**kwargs):
        pass
    
    def stop(self):
        pass

    def shutdown(self):
        pass