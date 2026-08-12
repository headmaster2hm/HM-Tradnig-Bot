from .logger import get_logger, setup_logging

__all__ = ["get_logger", "setup_logging", "NotificationHub"]


def __getattr__(name: str):
    if name == "NotificationHub":
        from .notifications import NotificationHub

        return NotificationHub
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
