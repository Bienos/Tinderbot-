"""Front door for customers' panels: <id>.<PUBLIC_DOMAIN> -> Fly app <APP_PREFIX><id>.

It never handles a panel itself. For every request it answers with a `fly-replay` header and Fly's proxy re-sends
the original request (body and cookies included, up to 1 MB) to that customer's bot over Fly's network. The bots
themselves have no public address. Stateless: the id in the hostname is the routing table, so there is nothing to
store or keep in sync. Logs nothing about requests (a sign-in link carries a one-time token in its query string).
"""
import os
import re
import socket
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DOMAIN = os.environ['PUBLIC_DOMAIN'].strip().lower().rstrip('.')
PREFIX = os.environ.get('APP_PREFIX', 'winq-b-')
BRAND = os.environ.get('BRAND_NAME', 'Winq')
HOME = os.environ.get('HOME_URL', 'https://winq.site')
BOT_ID = re.compile(r'^[a-z0-9]{6,16}$')

PAUSED = f'''<!doctype html><html lang="pl"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Panel chwilowo niedostępny · {BRAND}</title><body style="font:17px/1.5 system-ui,sans-serif;max-width:480px;margin:18vh auto;padding:0 20px;color:#2a0f22">
<h1 style="font-size:24px">Panel jest chwilowo niedostępny</h1>
<p>Twój serwer właśnie się uruchamia albo subskrypcja jest wstrzymana. Spróbuj za minutę albo sprawdź konto.</p>
<p><a href="{HOME}/konto" style="color:#fd267a;font-weight:600">Przejdź do konta</a></p></body></html>'''.encode()


class Router(BaseHTTPRequestHandler):
    server_version = 'router'
    sys_version = ''

    def log_message(self, *args):  # no request logging at all
        pass

    def _send(self, status, body=b'', headers=()):
        self.send_response(status)
        for name, value in headers:
            self.send_header(name, value)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(body)

    def route(self):
        if self.path == '/healthz':
            return self._send(200, b'ok', [('Content-Type', 'text/plain')])
        if self.headers.get('fly-replay-failed'):
            # The bot did not answer (stopped, starting, or no such customer): a clear page, not a proxy error.
            return self._send(503, PAUSED, [('Content-Type', 'text/html; charset=utf-8'), ('Retry-After', '60')])
        host = (self.headers.get('Host') or '').split(':')[0].strip().lower().rstrip('.')
        bot = host[:-len(DOMAIN) - 1] if host.endswith('.' + DOMAIN) else ''
        if not BOT_ID.match(bot):
            return self._send(404, b'Not found', [('Content-Type', 'text/plain')])
        self._send(204, b'', [('fly-replay', f'app={PREFIX}{bot};timeout=15s;fallback=force_self')])

    do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = do_HEAD = do_OPTIONS = route


class DualStack(ThreadingHTTPServer):
    address_family = socket.AF_INET6
    daemon_threads = True

    def server_bind(self):
        self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        super().server_bind()


if __name__ == '__main__':
    port = int(os.environ.get('PORT', '8080'))
    try:
        server = DualStack(('::', port), Router)
    except OSError:  # no IPv6 here
        server = ThreadingHTTPServer(('0.0.0.0', port), Router)
    server.serve_forever()
