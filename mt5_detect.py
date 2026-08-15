"""Find a local MetaTrader 5 terminal without asking the user.

Windows-only helpers. On Linux this module imports but every function
returns an empty list / None (used by tests and harmless elsewhere).

Detection order:
  1. A running ``terminal64.exe`` process (most reliable).
  2. Uninstall registry entries (broker installs under custom names/paths).
  3. Common install directories.
  4. MetaQuotes AppData terminals (e.g. after an in-place update).
"""

from __future__ import annotations

import glob
import os
import subprocess
import sys
from typing import Iterable


def _is_windows() -> bool:
    return sys.platform == "win32"


def _runs_powershell() -> list[str]:
    try:
        proc = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                "Get-Process -Name terminal64 -ErrorAction SilentlyContinue "
                "| Select-Object -ExpandProperty Path",
            ],
            capture_output=True,
            text=True,
            timeout=20,
        )
    except Exception:  # noqa: BLE001
        return []
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def _read_registry_keys(root: str, subkey: str) -> Iterable[str]:
    try:
        import winreg  # type: ignore[import-untyped]
    except ImportError:  # pragma: no cover
        return []
    try:
        base = getattr(winreg, root)
        with winreg.OpenKey(base, subkey) as key:
            index = 0
            while True:
                try:
                    yield winreg.EnumKey(key, index)
                    index += 1
                except OSError:
                    return
    except OSError:
        return


def _registry_terminals() -> list[str]:
    uninst_roots = [
        ("HKEY_LOCAL_MACHINE", r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        (
            "HKEY_LOCAL_MACHINE",
            r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall",
        ),
        ("HKEY_CURRENT_USER", r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
    ]
    found: list[str] = []
    for root, subkey in uninst_roots:
        for name in _read_registry_keys(root, subkey):
            try:
                import winreg  # type: ignore[import-untyped]
            except ImportError:  # pragma: no cover
                return found
            base = getattr(winreg, root)
            try:
                with winreg.OpenKey(base, subkey + "\\" + name) as key:
                    display = ""
                    location = ""
                    icon = ""
                    for _i in range(winreg.QueryInfoKey(key)[1]):
                        try:
                            value_name, value_data, _ = winreg.EnumValue(key, _i)
                        except OSError:
                            break
                        if value_name == "DisplayName":
                            display = str(value_data)
                        elif value_name == "InstallLocation":
                            location = str(value_data)
                        elif value_name == "DisplayIcon":
                            icon = str(value_data)
                haystack = " ".join([display, location, icon]).lower()
                if "metatrader" not in haystack and "mt5" not in haystack:
                    continue
                candidates = [location, icon]
                for candidate in candidates:
                    if not candidate:
                        continue
                    candidate = candidate.replace('"', "")
                    if candidate.lower().endswith("terminal64.exe"):
                        found.append(candidate)
                    elif candidate.lower().endswith(".exe"):
                        folder = os.path.dirname(candidate)
                        exe = os.path.join(folder, "terminal64.exe")
                        if os.path.exists(exe):
                            found.append(exe)
                    elif os.path.isdir(candidate):
                        exe = os.path.join(candidate, "terminal64.exe")
                        if os.path.exists(exe):
                            found.append(exe)
            except OSError:
                continue
    return found


def _common_path_terminals() -> list[str]:
    patterns = [
        r"C:\Program Files\MetaTrader 5\terminal64.exe",
        r"C:\Program Files (x86)\MetaTrader 5\terminal64.exe",
        r"C:\Program Files\MetaTrader 5*\terminal64.exe",
        r"C:\Program Files (x86)\MetaTrader 5*\terminal64.exe",
        r"C:\Program Files\*\MetaTrader 5*\terminal64.exe",
        r"C:\Program Files\*\*MT5*\terminal64.exe",
        r"C:\Program Files\*\*MetaTrader*\terminal64.exe",
        r"C:\Program Files (x86)\*\*MetaTrader*\terminal64.exe",
    ]
    found: list[str] = []
    for pattern in patterns:
        found.extend(p for p in glob.glob(pattern) if p not in found)
    return found


def _appdata_terminals() -> list[str]:
    root = os.environ.get("APPDATA", "")
    if not root:
        return []
    pattern = os.path.join(root, "MetaQuotes", "Terminal", "*", "terminal64.exe")
    return list(glob.glob(pattern))


def detect_terminals() -> list[str]:
    """Return absolute paths to every terminal64.exe found (deduped)."""
    found: list[str] = []
    for batch in (
        _runs_powershell() if _is_windows() else [],
        _registry_terminals(),
        _common_path_terminals(),
        _appdata_terminals(),
    ):
        for path in batch:
            if path and path not in found and os.path.exists(path):
                found.append(path)
    return found


def detect_primary() -> str:
    """Best candidate or empty string."""
    terminals = detect_terminals()
    return terminals[0] if terminals else ""


if __name__ == "__main__":  # pragma: no cover
    found = detect_terminals()
    if found:
        print("\n".join(found))
    else:
        print("No MetaTrader 5 terminal found.")
