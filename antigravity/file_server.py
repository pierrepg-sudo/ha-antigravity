"""File manager owned by a separate UID; agent has no direct input write access."""
import json
from pathlib import Path
import re
import secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit, quote
import workspace_files

CSRF = secrets.token_hex(32)
PROXY_KEY = None
AREAS = {'inputs': '/data/inputs', 'outputs': '/data/workspace/outputs', 'legacy': '/data/workspace'}


def select_area(query):
    values = query.get('area', ['inputs'])
    if len(values) != 1 or values[0] not in AREAS:
        raise ValueError('Unknown file area')
    return values[0]


class Handler(BaseHTTPRequestHandler):
    def respond(self, status, body, content_type='application/json', download=None):
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        if download:
            self.send_header('Content-Disposition', 'attachment; filename="' + re.sub(r'[^A-Za-z0-9._-]', '_', download) + '"; filename*=UTF-8\'\'' + quote(download, safe=''))
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def authenticated_proxy(self):
        supplied = self.headers.get('X-Antigravity-File-Key', '')
        if not PROXY_KEY or not supplied.isascii() or not secrets.compare_digest(supplied, PROXY_KEY):
            self.respond(403, b'{"error":"Use Home Assistant ingress to open Files."}')
            return False
        return True

    def do_GET(self):
        if not self.authenticated_proxy():
            return
        route = urlsplit(self.path).path
        if route == '/files':
            self.respond(200, Path(__file__).with_name('files.html').read_text().replace('__CSRF__', CSRF).encode(), 'text/html; charset=utf-8')
            return
        if route not in ('/file-list', '/file-preview', '/file-download'):
            self.send_error(404)
            return
        token = None
        try:
            query = parse_qs(urlsplit(self.path).query, keep_blank_values=True)
            area = select_area(query)
            token = workspace_files.ACTIVE_ROOT.set(AREAS[area])
            path = query.get('path', [''])[0]
            if route == '/file-download':
                body, name = workspace_files.read_file(path)
                self.respond(200, body, 'application/octet-stream', name)
            else:
                result = workspace_files.listing(path) if route == '/file-list' else workspace_files.read_file(path, preview=True)
                if route == '/file-list':
                    result.update(root=AREAS[area], readOnly=area == 'legacy')
                self.respond(200, json.dumps(result).encode())
        except (OSError, ValueError):
            self.respond(400, b'{"error":"Cannot open path. Links and special files are blocked; download limit is 32 MiB."}')
        finally:
            if token is not None:
                workspace_files.ACTIVE_ROOT.reset(token)

    def do_POST(self):
        if not self.authenticated_proxy():
            return
        if urlsplit(self.path).path != '/file-action':
            self.send_error(404)
            return
        tokens = []
        try:
            token = self.headers.get('X-Antigravity-CSRF', '')
            if not token.isascii() or not secrets.compare_digest(token, CSRF):
                self.respond(403, b'{"error":"Reopen Files and try again."}')
                return
            area = select_area(parse_qs(urlsplit(self.path).query, keep_blank_values=True))
            if area == 'legacy':
                self.respond(403, b'{"error":"Existing files are read-only in this menu. Download a copy and upload it to Inputs or Outputs."}')
                return
            if self.headers.get('Content-Type') != 'application/json':
                raise ValueError('Expected JSON')
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 12 * 1024 * 1024:
                raise ValueError('Invalid size')
            self.connection.settimeout(15)
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict):
                raise ValueError('Invalid payload')
            tokens = [(workspace_files.ACTIVE_ROOT, workspace_files.ACTIVE_ROOT.set(AREAS[area])),
                      (workspace_files.INPUT_MODE, workspace_files.INPUT_MODE.set(area == 'inputs'))]
            self.respond(200, json.dumps(workspace_files.change(payload)).encode())
        except FileExistsError:
            self.respond(409, b'{"error":"That name already exists. Rename before uploading."}')
        except (ValueError, TypeError):
            self.respond(400, b'{"error":"Invalid request. Check the name, path and file size."}')
        except OSError:
            self.respond(503, b'{"error":"File operation unavailable. Check folder permissions."}')
        finally:
            for var, token in reversed(tokens):
                var.reset(token)

    def log_message(self, *args):
        pass


if __name__ == '__main__':
    import os
    os.umask(0o007)
    PROXY_KEY = Path('/run/antigravity-files/key').read_text().strip()
    if len(PROXY_KEY) != 64:
        raise SystemExit('Missing file service ingress key')
    ThreadingHTTPServer(('127.0.0.1', 7683), Handler).serve_forever()
