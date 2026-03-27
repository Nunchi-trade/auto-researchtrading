import logging
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional
import os


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        extra_data = getattr(record, "extra_data", None)
        if extra_data is not None:
            log_data["data"] = extra_data

        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_data)


class ExtraLogAdapter(logging.LoggerAdapter):
    def process(self, msg, kwargs):
        extra_data = kwargs.pop("extra", {})
        if self.extra:
            extra_data.update(self.extra)

        if extra_data:
            kwargs["extra"] = {"extra_data": extra_data}

        return msg, kwargs


_loggers: dict = {}
_log_dir: Optional[Path] = None


def setup_logger(
    log_level: str = "INFO", log_path: Optional[str] = None, json_format: bool = True
):
    global _log_dir

    level = getattr(logging, log_level.upper(), logging.INFO)

    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    root_logger.handlers.clear()

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)

    if json_format:
        console_handler.setFormatter(JSONFormatter())
    else:
        console_handler.setFormatter(
            logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        )

    root_logger.addHandler(console_handler)

    if log_path:
        _log_dir = Path(log_path).parent
        _log_dir.mkdir(parents=True, exist_ok=True)

        file_handler = logging.FileHandler(log_path)
        file_handler.setLevel(level)
        file_handler.setFormatter(JSONFormatter())
        root_logger.addHandler(file_handler)


def get_logger(name: str) -> ExtraLogAdapter:
    if name in _loggers:
        return _loggers[name]

    logger = logging.getLogger(name)
    adapter = ExtraLogAdapter(logger, {})
    _loggers[name] = adapter
    return adapter
