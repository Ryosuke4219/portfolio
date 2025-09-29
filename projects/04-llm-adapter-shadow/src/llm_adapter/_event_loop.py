# ruff: noqa: I001

"""AsyncIO event loop helpers.

このモジュールは pytest-socket により ``socket.socket`` が禁止されている
環境でも ``asyncio`` のイベントループを初期化できるよう補助する。
"""

from __future__ import annotations

import os
import socket
import warnings
from typing import Any, cast

from asyncio import unix_events
from collections.abc import Callable


class _PipeEndpoint:
    """socket.socket の最小インターフェースを模したパイプエンドポイント。"""

    def __init__(self, fd: int, io_fn: Callable[[int, bytes], int] | None) -> None:
        self._fd = fd
        self._io_fn = io_fn

    def fileno(self) -> int:
        return self._fd

    def setblocking(self, flag: bool) -> None:
        os.set_blocking(self._fd, flag)

    def close(self) -> None:
        os.close(self._fd)

    def recv(self, size: int) -> bytes:
        return os.read(self._fd, size)

    def send(self, data: bytes) -> int:
        if self._io_fn is None:
            raise OSError("send on read-only pipe endpoint")
        return self._io_fn(self._fd, data)


_CAN_SOCKETPAIR: bool | None = None


def _probe_socketpair() -> bool:
    if not hasattr(socket, "socketpair"):
        return False

    try:
        sockets = socket.socketpair()
    except Exception:
        return False

    for sock in sockets:
        sock.close()
    return True


def _install_socketpair_fallback() -> None:
    loop_cls = cast(Any, unix_events._UnixSelectorEventLoop)

    if getattr(loop_cls, "_llm_adapter_socket_patch", False):
        return

    original_make_self_pipe = loop_cls._make_self_pipe

    def _patched_make_self_pipe(self: unix_events._UnixSelectorEventLoop) -> None:
        global _CAN_SOCKETPAIR
        if _CAN_SOCKETPAIR is not False:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", ResourceWarning)
                try:
                    original_make_self_pipe(self)
                except Exception:
                    _CAN_SOCKETPAIR = False
                else:
                    _CAN_SOCKETPAIR = True
                    return

        rfd, wfd = os.pipe()
        os.set_blocking(rfd, False)
        os.set_blocking(wfd, False)
        loop = cast(Any, self)
        loop._ssock = _PipeEndpoint(rfd, None)
        loop._csock = _PipeEndpoint(wfd, os.write)
        loop._internal_fds += 1
        loop._add_reader(loop._ssock.fileno(), loop._read_from_self)

    loop_cls._make_self_pipe = _patched_make_self_pipe
    loop_cls._llm_adapter_socket_patch = True


def ensure_socket_free_event_loop_policy() -> None:
    """socket が禁止された環境での ``asyncio.run`` 失敗を防ぐ。"""

    global _CAN_SOCKETPAIR
    if _CAN_SOCKETPAIR is None:
        _CAN_SOCKETPAIR = _probe_socketpair()

    _install_socketpair_fallback()
