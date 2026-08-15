"""Minimal WebSocket server (RFC 6455) for the bridge endpoint.

Runs inside the dashboard's existing ``ThreadingHTTPServer``: ``do_GET``
calls :func:`serve`, which performs the upgrade handshake and then owns the
connection (one thread per connection, so this blocking loop is fine).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import socket
import struct
from typing import Any

from bridge.manager import _Connection, resolve_bridge_token

logger = logging.getLogger("bridge.ws")

WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
MAX_MESSAGE = 4 * 1024 * 1024  # 4 MB guard
READ_TIMEOUT = 35.0

_OP_CONT = 0x0
_OP_TEXT = 0x1
_OP_BINARY = 0x2
_OP_CLOSE = 0x8
_OP_PING = 0x9
_OP_PONG = 0xA


def _accept_key(sec_key: str) -> str:
    digest = hashlib.sha1((sec_key + WS_GUID).encode("ascii")).digest()
    return base64.b64encode(digest).decode("ascii")


def _read_exact(sock: socket.socket, n: int) -> bytes:
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("socket closed")
        buf.extend(chunk)
    return bytes(buf)


def _read_frame(sock: socket.socket) -> tuple[int, bytes]:
    header = _read_exact(sock, 2)
    fin = header[0] & 0x80
    opcode = header[0] & 0x0F
    masked = header[1] & 0x80
    length = header[1] & 0x7F

    if length == 126:
        length = struct.unpack(">H", _read_exact(sock, 2))[0]
    elif length == 127:
        length = struct.unpack(">Q", _read_exact(sock, 8))[0]

    if length > MAX_MESSAGE:
        raise ConnectionError("frame too large")

    mask_key = _read_exact(sock, 4) if masked else b""
    payload = _read_exact(sock, length)
    if masked:
        payload = bytes(byte ^ mask_key[i % 4] for i, byte in enumerate(payload))
    return opcode, payload


def _encode_frame(opcode: int, payload: bytes) -> bytes:
    header = bytearray([0x80 | opcode])
    length = len(payload)
    if length < 126:
        header.append(length)
    elif length < 0x10000:
        header.append(126)
        header.extend(struct.pack(">H", length))
    else:
        header.append(127)
        header.extend(struct.pack(">Q", length))
    return bytes(header) + payload


class _ServerConnection(_Connection):
    def __init__(self, sock: socket.socket) -> None:
        self._sock = sock
        self._write_lock = __import__("threading").Lock()
        super().__init__(self._send_text)

    def _send_text(self, text: str) -> None:
        frame = _encode_frame(_OP_TEXT, text.encode("utf-8"))
        with self._write_lock:
            self._sock.sendall(frame)

    def close(self) -> None:
        self.closed = True
        try:
            self._sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass


def serve(handler: Any, manager: Any) -> None:
    """Upgrade the request to WebSocket, authenticate, then run the loop."""
    sock: socket.socket = handler.connection
    key = handler.headers.get("Sec-WebSocket-Key", "")
    if not key:
        return
    handler.close_connection = True

    expected = resolve_bridge_token()
    if not expected:
        logger.warning("bridge: no HM_BRIDGE_TOKEN set — refusing agent")
        return

    sock.settimeout(READ_TIMEOUT)
    accept = _accept_key(key)
    sock.sendall(
        b"HTTP/1.1 101 Switching Protocols\r\n"
        b"Upgrade: websocket\r\n"
        b"Connection: Upgrade\r\n"
        b"Sec-WebSocket-Accept: "
        + accept.encode("ascii")
        + b"\r\n\r\n"
    )
    logger.info("bridge: handshake done, waiting for auth")

    conn = _ServerConnection(sock)
    try:
        _recv_first = _read_frame(sock)
        if _recv_first[0] != _OP_TEXT:
            return
        try:
            first = json.loads(_recv_first[1].decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return
        token = str(first.get("token") or "")
        if first.get("type") != "auth" or not hmac.compare_digest(token, expected):
            logger.warning("bridge: auth rejected")
            _send_error_and_close(conn, "auth failed")
            return

        if not manager.attach(conn):
            logger.warning("bridge: another agent already attached")
            _send_error_and_close(conn, "busy")
            return

        conn.send_text(json.dumps({"type": "auth_ok"}))
        logger.info("bridge: agent authenticated")

        while not conn.closed:
            opcode, payload = _read_frame(sock)
            if opcode == _OP_CLOSE:
                break
            if opcode == _OP_PING:
                with conn._write_lock:  # noqa: SLF001
                    sock.sendall(_encode_frame(_OP_PONG, payload))
                continue
            if opcode == _OP_PONG:
                continue
            if opcode == _OP_TEXT:
                try:
                    message = json.loads(payload.decode("utf-8"))
                except (json.JSONDecodeError, UnicodeDecodeError):
                    continue
                manager._on_message(message)  # noqa: SLF001
            # binary/continuation frames ignored
    except (ConnectionError, socket.timeout, OSError):
        pass
    finally:
        manager.detach(conn)
        conn.close()


def _send_error_and_close(conn: _ServerConnection, message: str) -> None:
    try:
        conn.send_text(json.dumps({"type": "error", "error": message}))
    except OSError:
        pass
    conn.close()
