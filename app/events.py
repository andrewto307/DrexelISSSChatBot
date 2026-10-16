import json
import logging

logger = logging.getLogger("isss_bot.app")
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False


def log_event(event: str, **fields) -> None:
    logger.info(json.dumps({"event": event, **fields}, default=str))
