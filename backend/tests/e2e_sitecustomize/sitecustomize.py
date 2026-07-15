"""Process-wide network guard loaded only by the Playwright backend process."""

from __future__ import annotations

import ipaddress
import socket

_original_connect = socket.socket.connect
_original_connect_ex = socket.socket.connect_ex


def _assert_loopback(address) -> None:
    if not isinstance(address, tuple) or not address:
        return
    host = str(address[0])
    try:
        is_loopback = ipaddress.ip_address(host).is_loopback
    except ValueError:
        is_loopback = host.casefold() == "localhost"
    if not is_loopback:
        raise OSError(f"external network is disabled in E2E: {host}")


def _guarded_connect(self, address):
    _assert_loopback(address)
    return _original_connect(self, address)


def _guarded_connect_ex(self, address):
    _assert_loopback(address)
    return _original_connect_ex(self, address)


socket.socket.connect = _guarded_connect
socket.socket.connect_ex = _guarded_connect_ex
