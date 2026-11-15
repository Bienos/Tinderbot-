"""Start the bot on one socket that takes both IPv4 (Fly's proxy) and IPv6 (Fly's health checks).

A plain `--host ::` is IPv6-only on hosts with net.ipv6.bindv6only=1, and `--host 0.0.0.0` is IPv4-only; an
explicit dual-stack socket works either way. Falls back to IPv4 where IPv6 is unavailable (e.g. some containers).
"""
import os
import socket

import uvicorn


def listening_socket(port: int) -> socket.socket:
    try:
        sock = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
        sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        address = ('::', port)
    except OSError:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        address = ('0.0.0.0', port)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(address)
    sock.set_inheritable(True)
    return sock


if __name__ == '__main__':
    sock = listening_socket(int(os.getenv('PORT', '8080')))
    uvicorn.run('app:app', fd=sock.fileno(), workers=1, access_log=False, limit_concurrency=100,
                timeout_keep_alive=5, timeout_graceful_shutdown=8)
