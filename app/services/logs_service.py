# app/services/logs_service.py

import logging
from typing import List, Dict, Any, Optional
from app.core.config import AppEnv, Settings, settings

_CURRENT_CYCLE_ID: Optional[int] = None
_CYCLE_LOGS: List[Dict[str, Any]] = []


def clean_logger_name(record: logging.LogRecord) -> bool:
    if record.name.startswith(("climat_app.", "api_app.")):
        record.name = record.name.split(".")[-1]
    return True


class CycleLogHandler(logging.Handler):
    """Перехватывает сообщения WARNING и ERROR текущего цикла для отображения в UI."""
    def emit(self, record: logging.LogRecord):
        if record.levelno >= logging.WARNING:
            log_entry = {
                "cycle_id": _CURRENT_CYCLE_ID,
                "levelname": record.levelname,
                "name": record.name,
                "message": record.getMessage(),
            }
            _CYCLE_LOGS.append(log_entry)


_cycle_handler = CycleLogHandler()
_cycle_handler.addFilter(clean_logger_name)


def set_current_cycle_id(cycle_id: int) -> None:
    """Устанавливает текущий ID цикла и сбрасывает предупреждения предыдущего цикла."""
    global _CURRENT_CYCLE_ID, _CYCLE_LOGS
    _CURRENT_CYCLE_ID = cycle_id
    _CYCLE_LOGS.clear()


def get_current_cycle_logs() -> Dict[str, Any]:
    """Возвращает статус меню (normal/warning/error) и список предупреждений текущего цикла с уровнями и именами модулей."""
    if not _CYCLE_LOGS:
        return {"status": "normal", "messages": [], "cycle_id": _CURRENT_CYCLE_ID}

    has_error = any(log["levelname"] in ("ERROR", "CRITICAL") for log in _CYCLE_LOGS)
    status = "error" if has_error else "warning"

    messages = [f"{log['levelname']}:{log['name']}:{log['message']}" for log in _CYCLE_LOGS]
    return {
        "status": status,
        "messages": messages,
        "cycle_id": _CURRENT_CYCLE_ID,
    }


def setup_loggers(config: Settings) -> tuple[logging.Logger, logging.Logger]:
    log_level = logging.DEBUG if config.app_env == AppEnv.DEVELOPMENT else logging.INFO

    formatter = logging.Formatter(
        "%(asctime)s:%(levelname)s:%(name)s:%(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    work_handler = logging.FileHandler(config.work_log, mode="a")
    work_handler.setFormatter(formatter)
    work_handler.addFilter(clean_logger_name)

    work_logger = logging.getLogger("climat_app")
    work_logger.setLevel(log_level)
    work_logger.addHandler(work_handler)
    work_logger.addHandler(_cycle_handler)
    work_logger.propagate = False

    api_handler = logging.FileHandler(config.api_log, mode="a")
    api_handler.setFormatter(formatter)
    api_handler.addFilter(clean_logger_name)

    api_logger = logging.getLogger("api_app")
    api_logger.setLevel(log_level)
    api_logger.addHandler(api_handler)
    api_logger.addHandler(_cycle_handler)
    api_logger.propagate = False

    try:
        import uvicorn.config
        uvicorn_config_dict = uvicorn.config.LOGGING_CONFIG
        
        fmt_str = "%(asctime)s:%(levelname)s:%(name)s:%(message)s"
        date_fmt = "%Y-%m-%d %H:%M:%S"

        if "default" in uvicorn_config_dict.get("formatters", {}):
            uvicorn_config_dict["formatters"]["default"]["use_colors"] = False
            uvicorn_config_dict["formatters"]["default"]["fmt"] = fmt_str
            uvicorn_config_dict["formatters"]["default"]["datefmt"] = date_fmt
        if "access" in uvicorn_config_dict.get("formatters", {}):
            uvicorn_config_dict["formatters"]["access"]["use_colors"] = False
            uvicorn_config_dict["formatters"]["access"]["fmt"] = "%(asctime)s:%(levelname)s:%(name)s:%(client_addr)s - \"%(request_line)s\" %(status_code)s"
            uvicorn_config_dict["formatters"]["access"]["datefmt"] = date_fmt

        uvicorn_config_dict["handlers"]["api_file"] = {
            "class": "logging.FileHandler",
            "filename": str(config.api_log),
            "mode": "a",
            "formatter": "default",
        }
        uvicorn_config_dict["handlers"]["api_access_file"] = {
            "class": "logging.FileHandler",
            "filename": str(config.api_log),
            "mode": "a",
            "formatter": "access",
        }
        
        uvicorn_config_dict["loggers"]["uvicorn"]["handlers"] = ["api_file"]
        uvicorn_config_dict["loggers"]["uvicorn.error"]["handlers"] = ["api_file"]
        uvicorn_config_dict["loggers"]["uvicorn.access"]["handlers"] = ["api_access_file"]
    except Exception:
        pass

    for uvicorn_name in ["uvicorn", "uvicorn.error", "uvicorn.access"]:
        u_logger = logging.getLogger(uvicorn_name)
        u_logger.handlers = [api_handler, _cycle_handler]
        u_logger.propagate = False
        u_logger.setLevel(logging.INFO)

    return work_logger, api_logger


setup_loggers(settings)

# # app/services/logs_service.py

# import logging
# from typing import List, Dict, Any, Optional
# from app.core.config import AppEnv, Settings, settings

# _CURRENT_CYCLE_ID: Optional[int] = None
# _CYCLE_LOGS: List[Dict[str, Any]] = []


# class CycleLogHandler(logging.Handler):
#     """Перехватывает сообщения WARNING и ERROR текущего цикла для отображения в UI."""
#     def emit(self, record: logging.LogRecord):
#         if record.levelno >= logging.WARNING:
#             log_entry = {
#                 "cycle_id": _CURRENT_CYCLE_ID,
#                 "levelname": record.levelname,
#                 "name": record.name,
#                 "message": record.getMessage(),
#             }
#             _CYCLE_LOGS.append(log_entry)


# _cycle_handler = CycleLogHandler()


# def set_current_cycle_id(cycle_id: int) -> None:
#     """Устанавливает текущий ID цикла и сбрасывает предупреждения предыдущего цикла."""
#     global _CURRENT_CYCLE_ID, _CYCLE_LOGS
#     _CURRENT_CYCLE_ID = cycle_id
#     _CYCLE_LOGS.clear()


# def get_current_cycle_logs() -> Dict[str, Any]:
#     """Возвращает статус меню (normal/warning/error) и список предупреждений текущего цикла."""
#     if not _CYCLE_LOGS:
#         return {"status": "normal", "messages": [], "cycle_id": _CURRENT_CYCLE_ID}

#     has_error = any(log["levelname"] in ("ERROR", "CRITICAL") for log in _CYCLE_LOGS)
#     status = "error" if has_error else "warning"

#     messages = [f"{log['message']}" for log in _CYCLE_LOGS]
#     return {
#         "status": status,
#         "messages": messages,
#         "cycle_id": _CURRENT_CYCLE_ID,
#     }


# def setup_loggers(config: Settings) -> tuple[logging.Logger, logging.Logger]:
#     def clean_logger_name(record: logging.LogRecord) -> bool:
#         if record.name.startswith(("climat_app.", "api_app.")):
#             record.name = record.name.split(".")[-1]
#         return True

#     log_level = logging.DEBUG if config.app_env == AppEnv.DEVELOPMENT else logging.INFO

#     formatter = logging.Formatter(
#         "%(asctime)s:%(levelname)s:%(name)s:%(message)s",
#         datefmt="%Y-%m-%d %H:%M:%S"
#     )

#     work_handler = logging.FileHandler(config.work_log, mode="a")
#     work_handler.setFormatter(formatter)
#     work_handler.addFilter(clean_logger_name)

#     work_logger = logging.getLogger("climat_app")
#     work_logger.setLevel(log_level)
#     work_logger.addHandler(work_handler)
#     work_logger.addHandler(_cycle_handler)
#     work_logger.propagate = False

#     api_handler = logging.FileHandler(config.api_log, mode="a")
#     api_handler.setFormatter(formatter)
#     api_handler.addFilter(clean_logger_name)

#     api_logger = logging.getLogger("api_app")
#     api_logger.setLevel(log_level)
#     api_logger.addHandler(api_handler)
#     api_logger.addHandler(_cycle_handler)
#     api_logger.propagate = False

#     try:
#         import uvicorn.config
#         uvicorn_config_dict = uvicorn.config.LOGGING_CONFIG
        
#         fmt_str = "%(asctime)s:%(levelname)s:%(name)s:%(message)s"
#         date_fmt = "%Y-%m-%d %H:%M:%S"

#         if "default" in uvicorn_config_dict.get("formatters", {}):
#             uvicorn_config_dict["formatters"]["default"]["use_colors"] = False
#             uvicorn_config_dict["formatters"]["default"]["fmt"] = fmt_str
#             uvicorn_config_dict["formatters"]["default"]["datefmt"] = date_fmt
#         if "access" in uvicorn_config_dict.get("formatters", {}):
#             uvicorn_config_dict["formatters"]["access"]["use_colors"] = False
#             uvicorn_config_dict["formatters"]["access"]["fmt"] = "%(asctime)s:%(levelname)s:%(name)s:%(client_addr)s - \"%(request_line)s\" %(status_code)s"
#             uvicorn_config_dict["formatters"]["access"]["datefmt"] = date_fmt

#         uvicorn_config_dict["handlers"]["api_file"] = {
#             "class": "logging.FileHandler",
#             "filename": str(config.api_log),
#             "mode": "a",
#             "formatter": "default",
#         }
#         uvicorn_config_dict["handlers"]["api_access_file"] = {
#             "class": "logging.FileHandler",
#             "filename": str(config.api_log),
#             "mode": "a",
#             "formatter": "access",
#         }
        
#         uvicorn_config_dict["loggers"]["uvicorn"]["handlers"] = ["api_file"]
#         uvicorn_config_dict["loggers"]["uvicorn.error"]["handlers"] = ["api_file"]
#         uvicorn_config_dict["loggers"]["uvicorn.access"]["handlers"] = ["api_access_file"]
#     except Exception:
#         pass

#     for uvicorn_name in ["uvicorn", "uvicorn.error", "uvicorn.access"]:
#         u_logger = logging.getLogger(uvicorn_name)
#         u_logger.handlers = [api_handler, _cycle_handler]
#         u_logger.propagate = False
#         u_logger.setLevel(logging.INFO)

#     return work_logger, api_logger


# setup_loggers(settings)




