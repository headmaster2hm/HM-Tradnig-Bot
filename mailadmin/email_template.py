"""Dashboard-styled HTML email replies for the mail-admin feature.

Mirrors the HMLINE design tokens from ``dashboard/web/styles.css``:

- paper   #0e0f13   card #16181e   line #252833
- accent  #5b66ff   accent-ink #4651e8
- ink     #eef0f4   muted #7d818d   mono code style
- sharp, flat, editorial — no roundy dribble
"""

from __future__ import annotations

import html
from datetime import datetime
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid
from typing import Literal

PAPER = "#0e0f13"
CARD = "#16181e"
LINE = "#252833"
ACCENT = "#5b66ff"
ACCENT_INK = "#4651e8"
INK = "#eef0f4"
MUTED = "#7d818d"
UP = "#2fbf71"
DOWN = "#ff5c61"

Kind = Literal["rotate", "status"]

_SUBJECT_ROTATE = "HM BOT // access handshake accepted"
_SUBJECT_STATUS = "HM BOT // access link (no rotation)"


def _logo() -> str:
    return (
        '<span style="font-family:Arial,sans-serif;font-size:22px;'
        "font-weight:700;letter-spacing:1px;color:#eef0f4;"
        '">HM<span style="color:#5b66ff">&#9616;</span></span>'
    )


def _code_box(text: str) -> str:
    escaped = html.escape(text)
    return (
        f'<div style="background:#0a0b0e;border:1px solid #252833;'
        f'padding:14px 16px;border-radius:2px;">'
        f'<span style="font-family:Courier New,Consolas,monospace;'
        f'font-size:14px;color:#eef0f4;word-break:break-all;">{escaped}</span></div>'
    )


def _badge(text: str, color: str, bg: str) -> str:
    return (
        f'<span style="display:inline-block;font-family:Arial,sans-serif;'
        f'font-size:11px;font-weight:700;letter-spacing:1px;text-transform:uppercase;'
        f'color:{color};background:{bg};padding:4px 8px;border-radius:2px;">{text}</span>'
    )


def render_reply(kind: Kind, url: str, access_word: str) -> tuple[str, str]:
    """Build (subject, html_body) for the reply email."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if kind == "rotate":
        title = "New owner link is ready"
        lead = (
            "Your old link has been burned. Only the link in this email "
            "can open the owner control panel."
        )
        word_intro = "MEMORIZE THIS. Your next email must contain it in the subject."
        word_badge = _badge("next access word", "#0a0b0e", "#2fbf71")
        status_badge = _badge("rotated · fresh link", "#0a0b0e", "#5b66ff")
    else:
        title = "Your link (unchanged)"
        lead = (
            "No access word found in your email, so nothing was rotated. "
            "This is your current link."
        )
        word_intro = (
            "To generate a NEW link, reply with this word in the subject."
        )
        word_badge = _badge("current access word", "#0a0b0e", "#e0a83c")
        status_badge = _badge("status · no rotation", "#0a0b0e", "#e0a83c")

    body = f"""\
<div style="background:{PAPER};margin:0;padding:0;">

  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background:{PAPER};">
    <tr><td align="center" style="padding:32px 16px;">

      <table role="presentation" width="560" cellpadding="0" cellspacing="0" border="0" style="max-width:560px;width:100%;">
        <!-- header -->
        <tr>
          <td align="center" style="padding:0 0 24px 0;">
            {_logo()}
            <div style="font-family:Arial,sans-serif;font-size:11px;color:#7d818d;letter-spacing:3px;margin-top:6px;">HM BOT TRADER · OWNER MAIL</div>
          </td>
        </tr>

        <!-- card -->
        <tr>
          <td style="background:{CARD};border:1px solid {LINE};border-radius:2px;padding:28px 28px 8px 28px;">
            <div style="font-family:Arial,sans-serif;">
              <div style="margin-bottom:14px;">{status_badge}</div>
              <div style="font-size:22px;font-weight:700;color:{INK};margin:0 0 8px 0;">{title}</div>
              <div style="font-size:14px;line-height:20px;color:{MUTED};margin:0 0 20px 0;">{lead}</div>
            </div>
          </td>
        </tr>

        <!-- url block -->
        <tr>
          <td style="background:{CARD};border:1px solid {LINE};border-top:0;border-radius:0;padding:0 28px 24px 28px;">
            <div style="font-family:Arial,sans-serif;font-size:11px;color:#7d818d;letter-spacing:1px;text-transform:uppercase;margin-bottom:8px;">Your owner link</div>
            {_code_box(url)}
            <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="margin-top:18px;">
              <tr>
                <td align="center">
                  <a href="{html.escape(url)}" target="_blank" style="display:inline-block;font-family:Arial,sans-serif;font-size:14px;font-weight:700;color:#ffffff;background:{ACCENT};text-decoration:none;padding:12px 26px;border-radius:2px;letter-spacing:.5px;">Open admin panel</a>
                </td>
              </tr>
            </table>
            <div style="font-family:Arial,sans-serif;font-size:12px;color:#7d818d;text-align:center;margin-top:10px;">or paste the link above into a fresh, private window</div>
          </td>
        </tr>

        <!-- access word block -->
        <tr>
          <td style="background:#0a0b0e;border:1px solid {LINE};border-radius:2px;padding:20px 28px;margin-top:14px;">
            <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
              <tr>
                <td>
                  <div style="font-family:Arial,sans-serif;font-size:11px;color:#7d818d;letter-spacing:1px;text-transform:uppercase;margin-bottom:10px;">{word_badge}</div>
                  <div style="font-family:Courier New,Consolas,monospace;font-size:24px;font-weight:700;color:{INK};letter-spacing:2px;margin:10px 0 10px 0;">{html.escape(access_word)}</div>
                  <div style="font-family:Arial,sans-serif;font-size:12px;line-height:18px;color:{MUTED};">{word_intro}</div>
                </td>
              </tr>
            </table>
          </td>
        </tr>

        <!-- footer -->
        <tr>
          <td align="center" style="padding:24px 16px 0 16px;">
            <div style="font-family:Courier New,Consolas,monospace;font-size:11px;color:#363a46;line-height:18px;">
              HM &gt; _access handshake complete<br>
              issued {html.escape(ts)} · link self-destructs on next rotation
            </div>
            <div style="font-family:Arial,sans-serif;font-size:11px;color:#363a46;margin-top:10px;">
              Sent by your own bot · delete this email after use
            </div>
          </td>
        </tr>
      </table>

    </td></tr>
  </table>

</div>
"""

    subject = _SUBJECT_ROTATE if kind == "rotate" else _SUBJECT_STATUS
    return subject, body


def build_reply_message(
    kind: Kind,
    url: str,
    access_word: str,
    to_addr: str,
) -> EmailMessage:
    """Build the full reply EmailMessage (marked so the watcher skips it)."""
    subject, body = render_reply(kind, url, access_word)
    msg = EmailMessage()
    msg["From"] = formataddr(("HM Bot Trader", to_addr))
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain="headmaster.fun")
    msg["X-HM-Bot-Auto"] = "1"
    msg["Auto-Submitted"] = "auto-generated"
    msg.set_content(
        "HM Bot Trader owner link\n\n"
        f"{url}\n\n"
        f"Next access word: {access_word}\n"
        f"{word_instructions(kind)}\n"
    )
    msg.add_alternative(body, subtype="html")
    return msg


def word_instructions(kind: Kind) -> str:
    if kind == "rotate":
        return "Memorize the access word above. Your next email must contain it in the subject."
    return "To rotate your link, email yourself again with the access word in the subject."
