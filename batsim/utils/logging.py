import logging

def get_logger(name: str = "batsim") -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        h = logging.StreamHandler()
        h.setFormatter(logging.Formatter("[%(levelname)s] %(name)s: %(message)s"))
        logger.addHandler(h)
        logger.setLevel(logging.INFO)
    return logger
