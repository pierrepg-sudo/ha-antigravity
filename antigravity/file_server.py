"""File manager owned by a separate UID; agent has no direct input write access."""
import json
from pathlib import Path
import re
import secrets
import threading
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit, quote
import workspace_files

CSRF = secrets.token_hex(32)
PROXY_KEY = None
TRANSFER_LOCK = threading.Lock()
PREPARED_LOCK = threading.Lock()
PREPARED_ZIPS = {}
ZIP_TTL = 300


class ChunkedUpload:
    """Decode a bounded HTTP chunk stream forwarded by streaming ingress."""
    def __init__(self, source):
        self.source = source
        self.remaining = 0
        self.done = False

    def line(self):
        line = self.source.readline(8193)
        if len(line) > 8192 or not line.endswith(b'\r\n'):
            raise ValueError('Invalid chunk framing')
        return line[:-2]

    def read(self, size):
        if self.done:
            return b''
        if not self.remaining:
            header = self.line().split(b';', 1)[0]
            if not re.fullmatch(rb'[0-9a-fA-F]{1,16}', header):
                raise ValueError('Invalid chunk size')
            self.remaining = int(header, 16)
            if not self.remaining:
                total = 0
                while True:
                    trailer = self.line()
                    total += len(trailer) + 2
                    if total > 8192:
                        raise ValueError('Oversized trailers')
                    if not trailer:
                        break
                self.done = True
                return b''
        data = self.source.read(min(size, self.remaining))
        if not data:
            raise ValueError('Truncated chunk')
        self.remaining -= len(data)
        if not self.remaining and self.source.read(2) != b'\r\n':
            raise ValueError('Invalid chunk terminator')
        return data


def expire_zip(ticket):
    with PREPARED_LOCK:
        item = PREPARED_ZIPS.pop(ticket, None)
    if item:
        item['archive'].close()


def prepare_zip(path, area):
    # Reserve a bounded slot before generating; archives spill to disk at 8 MiB.
    ticket = secrets.token_hex(24)
    with PREPARED_LOCK:
        if len(PREPARED_ZIPS) >= 3:
            raise workspace_files.FileOperationError('Three ZIP downloads are waiting. Download one or wait five minutes, then retry.')
        PREPARED_ZIPS[ticket] = None
    archive = None
    try:
        archive, name = workspace_files.folder_zip(path)
        archive.seek(0, 2)
        length = archive.tell()
        archive.seek(0)
        with PREPARED_LOCK:
            PREPARED_ZIPS[ticket] = dict(archive=archive, name=name, length=length, area=area, path=path)
        timer = threading.Timer(ZIP_TTL, expire_zip, args=(ticket,))
        timer.daemon = True
        timer.start()
        return dict(ticket=ticket, name=name, size=length)
    except BaseException:
        with PREPARED_LOCK:
            PREPARED_ZIPS.pop(ticket, None)
        if archive:
            archive.close()
        raise


def take_zip(ticket, path, area):
    with PREPARED_LOCK:
        item = PREPARED_ZIPS.get(ticket)
        if not item or item['path'] != path or item['area'] != area:
            raise workspace_files.FileOperationError('This ZIP link expired or was already used. Prepare the folder download again.')
        return PREPARED_ZIPS.pop(ticket)

AREAS = {'inputs': '/data/inputs', 'outputs': '/data/workspace/outputs', 'archived': '/data/workspace/outputs'}


def project_folders():
    # The separate file-service UID must not read the CLI's private state or token.
    client = http.client.HTTPConnection('127.0.0.1', 7682, timeout=5)
    try:
        client.request('GET', '/project-folders')
        response = client.getresponse()
        body = response.read(1024 * 1024 + 1)
        if response.status != 200 or len(body) > 1024 * 1024:
            raise ValueError()
        projects = json.loads(body)['projects']
        if not isinstance(projects, list) or any(not isinstance(p, dict) or not isinstance(p.get('folder'), str) for p in projects):
            raise ValueError()
        return {p['folder']: p for p in projects if p['folder']}
    except (OSError, ValueError, KeyError, TypeError, http.client.HTTPException):
        raise workspace_files.FileOperationError('Project folder protection is unavailable. Reopen Conversations, then retry. No file operation was performed.') from None
    finally:
        client.close()


def guard_project_folder(area, payload):
    if area not in ('outputs', 'archived') or payload.get('action') not in ('delete', 'rename', 'move'):
        return
    path = payload.get('source', '') if payload['action'] == 'move' else '/'.join(filter(None, [payload.get('path', ''), payload.get('name', '')]))
    names = workspace_files.parts(path)
    if len(names) == 1 and names[0] in project_folders():
        raise workspace_files.FileOperationError('This folder is linked to a project. Manage its deletion, name or archive state in Conversations; direct deletion/moving is protected, including archived projects.')


def select_area(query):
    values = query.get('area', ['outputs'])
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

    def stream_download(self, source, name, length, content_type='application/octet-stream'):
        self.send_response(200)
        self.send_header('Content-Type', content_type)
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Disposition', 'attachment; filename="' + re.sub(r'[^A-Za-z0-9._-]', '_', name) + '"; filename*=UTF-8\'\'' + quote(name, safe=''))
        self.send_header('Content-Length', str(length))
        self.end_headers()
        # Never read a growing file beyond the advertised size or buffer it in RAM.
        remaining = length
        try:
            while remaining:
                chunk = source.read(min(64 * 1024, remaining))
                if not chunk:
                    self.close_connection = True
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)
        except OSError:
            # Headers already went out; do not append a JSON error to file contents.
            self.close_connection = True

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
        if route not in ('/file-list', '/file-preview', '/file-download', '/folder-download'):
            self.send_error(404)
            return
        token = None
        try:
            query = parse_qs(urlsplit(self.path).query, keep_blank_values=True)
            area = select_area(query)
            token = workspace_files.ACTIVE_ROOT.set(AREAS[area])
            path = query.get('path', [''])[0]
            if route == '/folder-download' and 'ticket' in query:
                item = take_zip(query['ticket'][0], path, area)
                with item['archive'] as archive:
                    self.stream_download(archive, item['name'], item['length'], 'application/zip')
                return
            projects = project_folders() if area in ('outputs', 'archived') and (not path or area == 'archived') else {}
            if area == 'archived' and path:
                names = workspace_files.parts(path)
                if not projects.get(names[0], {}).get('archived'):
                    raise workspace_files.FileOperationError('This project is no longer archived. Open Outputs to find its files.')
            if route == '/folder-download':
                if area == 'archived' and not path:
                    raise workspace_files.FileOperationError('Open an archived project folder before downloading its ZIP.')
                if not TRANSFER_LOCK.acquire(blocking=False):
                    raise workspace_files.FileOperationError('Another folder operation is running. Try again shortly.')
                try:
                    if query.get('prepare') == ['1']:
                        result = prepare_zip(path, area)
                        self.respond(200, json.dumps(result).encode())
                        return
                    archive, name = workspace_files.folder_zip(path)
                finally:
                    TRANSFER_LOCK.release()
                with archive:
                    archive.seek(0, 2)
                    length = archive.tell()
                    archive.seek(0)
                    self.stream_download(archive, name, length, 'application/zip')
            elif route == '/file-download':
                with workspace_files.download_file(path) as (source, name, length):
                    self.stream_download(source, name, length)
            else:
                result = workspace_files.listing(path) if route == '/file-list' else workspace_files.read_file(path, preview=True)
                if route == '/file-list':
                    result.update(root=AREAS[area], readOnly=False)
                    if area in ('outputs', 'archived') and not path:
                        result['entries'] = [dict(entry, project=projects.get(entry['name'])) for entry in result['entries']
                                             if bool(projects.get(entry['name'], {}).get('archived')) == (area == 'archived')]
                self.respond(200, json.dumps(result).encode())
        except workspace_files.FileOperationError as error:
            self.respond(400, json.dumps({'error': str(error)}).encode())
        except (OSError, ValueError):
            self.respond(400, b'{"error":"Cannot open path. Links and special files are blocked; download limit is 500 MiB."}')
        finally:
            if token is not None:
                workspace_files.ACTIVE_ROOT.reset(token)

    def do_POST(self):
        if not self.authenticated_proxy():
            return
        route = urlsplit(self.path).path
        if route not in ('/file-action', '/file-upload'):
            self.send_error(404)
            return
        tokens = []
        try:
            token = self.headers.get('X-Antigravity-CSRF', '')
            if not token.isascii() or not secrets.compare_digest(token, CSRF):
                self.respond(403, b'{"error":"Reopen Files and try again."}')
                return
            area = select_area(parse_qs(urlsplit(self.path).query, keep_blank_values=True))
            if route == '/file-upload':
                if self.headers.get('Content-Type') != 'application/octet-stream':
                    raise ValueError('Expected a file with a known length')
                encoding = self.headers.get('Transfer-Encoding', '').lower().strip()
                if encoding:
                    if encoding != 'chunked' or self.headers.get('Content-Length') is not None:
                        raise ValueError('Ambiguous upload framing')
                    length = None
                    source = ChunkedUpload(self.rfile)
                else:
                    length = int(self.headers.get('Content-Length', '-1'))
                    source = self.rfile
                if length is not None and not 0 <= length <= workspace_files.UPLOAD_LIMIT:
                    raise workspace_files.FileOperationError('Upload limit is 500 MiB per file.')
                query = parse_qs(urlsplit(self.path).query, keep_blank_values=True)
                path = query.get('path', [''])[0]
                name = query.get('name', [''])[0]
                tokens = [(workspace_files.ACTIVE_ROOT, workspace_files.ACTIVE_ROOT.set(AREAS[area])),
                          (workspace_files.INPUT_MODE, workspace_files.INPUT_MODE.set(area == 'inputs'))]
                if area == 'archived':
                    names = workspace_files.parts(path)
                    if not names or not project_folders().get(names[0], {}).get('archived'):
                        raise workspace_files.FileOperationError('Open an archived project folder before uploading.')
                self.connection.settimeout(300)
                result = workspace_files.upload_stream(path, name, source, length)
                self.respond(200, json.dumps(result).encode())
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
            if area == 'archived':
                names = workspace_files.parts(payload.get('path', ''))
                if not names or not project_folders().get(names[0], {}).get('archived'):
                    raise workspace_files.FileOperationError('Open an archived project folder to edit its contents. Use Archive/Restore for whole projects.')
            if payload.get('action') in ('rules-read', 'rules-save', 'rules-delete'):
                names = workspace_files.parts(payload.get('path', ''))
                if area not in ('outputs', 'archived') or len(names) != 1 or not project_folders().get(names[0]):
                    raise workspace_files.FileOperationError('Rules are available only for a linked project root folder.')
                with TRANSFER_LOCK:
                    result = workspace_files.project_rules(payload)
            elif payload.get('action') in ('copy', 'move'):
                source_area = payload.get('sourceArea')
                if not isinstance(source_area, str) or source_area not in AREAS:
                    raise ValueError('Unknown source area')
                if payload['action'] == 'move' and source_area != area:
                    raise workspace_files.FileOperationError('Move stays within Inputs or Outputs. Use Copy to transfer between locations.')
                if not TRANSFER_LOCK.acquire(blocking=False):
                    raise workspace_files.FileOperationError('Another folder operation is running. Try again shortly.')
                try:
                    guard_project_folder(source_area, payload)
                    result = workspace_files.transfer(payload, AREAS[source_area])
                finally:
                    TRANSFER_LOCK.release()
            elif payload.get('action') == 'extract':
                if not TRANSFER_LOCK.acquire(blocking=False):
                    raise workspace_files.FileOperationError('Another folder operation is running. Try again shortly.')
                try:
                    self.connection.settimeout(300)
                    result = workspace_files.extract_zip(payload)
                finally:
                    TRANSFER_LOCK.release()
            elif payload.get('action') in ('delete', 'rename'):
                if not TRANSFER_LOCK.acquire(blocking=False):
                    raise workspace_files.FileOperationError('Another folder operation is running. Try again shortly.')
                try:
                    guard_project_folder(area, payload)
                    result = workspace_files.change(payload)
                finally:
                    TRANSFER_LOCK.release()
            else:
                result = workspace_files.change(payload)
            self.respond(200, json.dumps(result).encode())
        except workspace_files.FileOperationError as error:
            self.respond(400, json.dumps({'error': str(error)}).encode())
        except FileExistsError:
            self.respond(409, b'{"error":"That name already exists. Choose another destination name."}')
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
