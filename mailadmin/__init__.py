"""Email self-service for the owner admin URL.

Send a mail from hm@headmaster.fun to itself and the bot replies with a
dashboard-styled email containing the current (or a freshly rotated) owner
control URL. A rotating "access word" gates rotation.
"""

from __future__ import annotations

from mailadmin.watcher import start_watcher

__all__ = ["start_watcher"]
