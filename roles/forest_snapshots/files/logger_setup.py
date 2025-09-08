import logging
import os
import sys


def setup_logger(name: str) -> logging.Logger:
    """Create and configure a logger with consistent settings."""
    log_level = getattr(
        logging,
        os.getenv("LOG_LEVEL", "INFO").upper(),
        logging.INFO
    )
    logger = logging.getLogger(name)
    logger.setLevel(log_level)

    # Avoid duplicate handlers if setup_logger is called multiple times
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(log_level)
        formatter = logging.Formatter(
            fmt="%(asctime)s %(levelname)s %(name)s:%(lineno)d %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S"
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    return logger
