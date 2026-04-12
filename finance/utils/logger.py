import sys
from loguru import logger

logger.remove()
logger.add(
    sys.stderr,
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
    level="INFO",
)
logger.add(
    "logs/app.log",
    rotation="500 MB",
    retention="10 days",
    level="DEBUG",
    enqueue=True,
)

__all__ = ["logger"]
