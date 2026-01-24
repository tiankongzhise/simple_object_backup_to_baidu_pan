from .config import Config


class DbService:
    def __init__(self, config: Config):
        self.config = config
