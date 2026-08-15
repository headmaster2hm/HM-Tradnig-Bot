"""Poll the owner's Maildir and answer "email myself a fresh admin URL".

Threat model
------------
- The reply (with the URL) is delivered ONLY into the owner's own mailbox,
  so a forged sender never sees the link.
- Rotation is gated by a rotating *access word* that only exists inside the
  reply emails. Without it, an attacker who spoofs ``hm@headmaster.fun`` can
  NOT force rotations (which would burn the owner's URL — a denial of service).
- Every rotation mints a brand-new URL and invalidates the old one, so leaked
  or bookmarked links stop working on their own.
- The bot's own replies carry ``X-HM-Bot-Auto: 1`` and are never re-read.
"""

from __future__ import annotations

import email
import os
import random
import re
import secrets
import subprocess
import threading
import time
from email.message import EmailMessage
from pathlib import Path

from mailadmin.email_template import Kind, build_reply_message
from utils import admin as admin_util
from utils.logger import get_logger

logger = get_logger("mailadmin")

# --- configuration (env-overridable) -----------------------------------
MAIL_DIR = Path(os.environ.get("HMBOT_MAIL_DIR", "/home/hm/mail/headmaster.fun/hm"))
OWNER_ADDR = os.environ.get("HMBOT_OWNER_MAIL", "hm@headmaster.fun")
PUBLIC_BASE = os.environ.get("HMBOT_PUBLIC_BASE", "https://tradebot.headmaster.fun")
SENDMAIL = os.environ.get("HMBOT_SENDMAIL", "/usr/sbin/sendmail")
POLL_SECONDS = float(os.environ.get("HMBOT_MAIL_POLL_SECONDS", "5"))

AUTO_HEADER = "X-HM-Bot-Auto"

_ACCESS_WORDS = [
    "bluejay", "cobalt", "synapse", "moonshot", "cryptid", "neonwave",
    "quantum", "fractal", "aurora", "spectre", "vault", "monorail",
    "sandwich", "sputnik", "halcyon", "ziggurat", "pulsar", "orbital",
    "windsock", "lampshade", "zigzag", "sparkplug", "flamingo", "turbo",
    "xylophone", "gazebo", "hologram", "kaleidoscope", "marmoset", "nebula",
    "octopus", "pipeline", "quasar", "runaway", "satellite", "tangerine",
    "umbrella", "voltage", "wildebeest", "zeppelin", "alembic", "bandwidth",
    "candle", "doomsday", "eclipse", "ferris", "guitar", "hacksaw",
]


def _new_access_word() -> str:
    return secrets.choice(_ACCESS_WORDS)


def _email_addresses(raw: str | None) -> list[str]:
    if not raw:
        return []
    found: list[str] = []
    for addr in email.utils.getaddresses([raw]):
        local = (addr[1] or "").strip().lower()
        if local:
            found.append(local)
    return found


def _body_text(msg: EmailMessage) -> str:
    parts: list[str] = []
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            if ctype in ("text/plain", "text/html"):
                try:
                    payload = part.get_payload(decode=True) or b""
                    charset = part.get_content_charset() or "utf-8"
                    parts.append(payload.decode(charset, errors="replace"))
                except (LookupError, ValueError):
                    continue
    else:
        try:
            payload = msg.get_payload(decode=True) or b""
            charset = msg.get_content_charset() or "utf-8"
            parts.append(payload.decode(charset, errors="replace"))
        except (LookupError, ValueError):
            return ""
    return "\n".join(parts)


def _contains_word(text: str, word: str) -> bool:
    return bool(re.search(rf"\b{re.escape(word)}\b", text, re.IGNORECASE))


def classify(msg: EmailMessage) -> tuple[Kind, bool]:
    """Return (kind, is_owner_request).

    kind is "rotate" when the request is allowed to mint a new URL,
    otherwise "status" (no rotation).
    """
    subject = msg.get("Subject") or ""
    current = admin_util.get_mail_passphrase()
    if not current:
        return "rotate", True  # bootstrap: first email always rotates
    blob = subject + "\n" + _body_text(msg)
    if _contains_word(blob, current):
        return "rotate", True
    return "status", True


def send_reply(to_addr: str, kind: Kind, url: str, access_word: str) -> bool:
    msg = build_reply_message(kind, url, access_word, to_addr)
    try:
        proc = subprocess.run(
            [SENDMAIL, "-t", "-f", OWNER_ADDR],
            input=msg.as_bytes(),
            capture_output=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.error("sendmail failed: %s", exc)
        return False
    if proc.returncode != 0:
        logger.error(
            "sendmail exited %s: %s", proc.returncode, proc.stderr.decode(errors="replace")
        )
        return False
    return True


def process_one(mail_path: Path) -> None:
    try:
        raw = mail_path.read_bytes()
        msg: EmailMessage = email.message_from_bytes(raw)
    except OSError as exc:
        logger.warning("unreadable mail %s: %s", mail_path.name, exc)
        return

    if msg.get(AUTO_HEADER) == "1":
        logger.info("skipping own auto-reply %s", mail_path.name)
        return

    senders = _email_addresses(msg.get("From"))
    recipients = _email_addresses(msg.get("To")) + _email_addresses(msg.get("Cc"))

    if not senders or senders[0] != OWNER_ADDR.lower():
        logger.info("ignoring mail %s (sender %r)", mail_path.name, senders)
        return
    if OWNER_ADDR.lower() not in recipients:
        logger.info("ignoring mail %s (owner not a recipient)", mail_path.name)
        return

    kind, _ok = classify(msg)

    if kind == "rotate":
        token = admin_util.rotate_path_token()
        word = _new_access_word()
        admin_util.set_mail_passphrase(word)
        logger.info("rotated admin token to %s (new access word %s)", token, word)
    else:
        token = admin_util.get_path_token()
        word = admin_util.get_mail_passphrase()
        logger.info("status reply (no rotation), token %s", token)

    url = f"{PUBLIC_BASE.rstrip('/')}/{token}"
    if send_reply(OWNER_ADDR, kind, url, word):
        logger.info("replied %s to %s", kind, OWNER_ADDR)
    else:
        logger.warning("failed to send %s reply", kind)


def _move_to_cur(mail_path: Path) -> None:
    try:
        name = mail_path.name.split(":", 1)[0] + ":2,S"
        target = mail_path.parent.parent / "cur" / name
        os.replace(str(mail_path), str(target))
        logger.info("filed %s to cur/", mail_path.name)
    except OSError as exc:
        logger.warning("could not move %s to cur/: %s", mail_path.name, exc)


def poll_once() -> int:
    new_dir = MAIL_DIR / "new"
    if not new_dir.is_dir():
        return 0
    count = 0
    for entry in sorted(new_dir.iterdir()):
        if not entry.is_file():
            continue
        process_one(entry)
        _move_to_cur(entry)
        count += 1
    return count


def start_watcher() -> threading.Thread:
    thread = threading.Thread(target=_run, name="mailadmin-watcher", daemon=True)
    thread.start()
    return thread


def _run() -> None:
    logger.info(
        "mail watcher started: %s -> owner %s (public base %s)",
        MAIL_DIR,
        OWNER_ADDR,
        PUBLIC_BASE,
    )
    while True:
        try:
            poll_once()
        except Exception as exc:  # noqa: BLE001
            logger.exception("mail poll failed: %s", exc)
        time.sleep(POLL_SECONDS)
