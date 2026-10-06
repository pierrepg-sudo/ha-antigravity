"""Mobile controls and OAuth helper; localhost behind admin-only HA ingress."""
import json
import secrets
import threading
from pathlib import Path
import html
import re
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit


CSRF = secrets.token_hex(32)
LOCK = threading.Lock()
KEYS = {'Tab', 'BTab', 'Up', 'Down', 'Left', 'Right', 'S-Up', 'S-Down', 'Enter', 'Escape', 'BSpace'}


def tmux(*args, **kwargs):
    return subprocess.run(['tmux', *args], check=True, timeout=5,
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kwargs)


def send_input(payload):
    if set(payload) == {'key'} and isinstance(payload['key'], str) and payload['key'] in KEYS:
        with LOCK:
            tmux('send-keys', '-t', 'antigravity:0.0', payload['key'])
    else:
        raise ValueError('Unknown key or input format.')
    return {'ok': True}


def extract_url(screen):
    # tmux capture without -e omits terminal styling. Strip escapes defensively.
    screen = re.sub(r'\x1b\][^\x07]*(?:\x07|\x1b\\)', '', screen)
    screen = re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]', '', screen)
    lines = screen.splitlines()
    candidates = []
    for i, line in enumerate(lines):
        start = line.find('https://accounts.google.com/')
        if start < 0:
            continue
        candidate = line[start:].strip()
        # A TUI may hard-wrap even when tmux capture uses -J.
        for continuation in lines[i + 1:]:
            fragment = continuation.strip()
            if not fragment or not re.fullmatch(r"[A-Za-z0-9._~:/?#\[\]@!$&'()*+,;=%-]+", fragment):
                break
            if fragment.startswith('https://'):
                break
            candidate += fragment
        try:
            parsed = urlsplit(candidate)
            query = parse_qs(parsed.query)
            required = ('client_id', 'redirect_uri', 'code_challenge', 'state', 'scope')
            if (parsed.scheme == 'https' and parsed.netloc == 'accounts.google.com'
                    and parsed.path == '/o/oauth2/auth'
                    and query.get('response_type') == ['code']
                    and all(query.get(k) for k in required)):
                candidates.append(candidate)
        except ValueError:
            pass
    return candidates[-1] if candidates else None


def current_url():
    try:
        result = subprocess.run(
            ['tmux', 'capture-pane', '-p', '-J', '-t', 'antigravity:0.0'],
            capture_output=True, text=True, timeout=3, check=True)
        return extract_url(result.stdout)
    except (OSError, subprocess.SubprocessError):
        return None


def render(url):
    action = ('<a class="button" target="_blank" rel="noopener noreferrer" href="'
              + html.escape(url, quote=True) + '">Sign in with Google</a>') if url else (
              '<p>No complete Google sign-in link is visible yet. Open the terminal, '
              'follow its setup prompts, then return here and refresh.</p>')
    return ('''<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Antigravity sign-in</title><style>
body{font:17px system-ui;background:#181a20;color:#eee;max-width:650px;margin:40px auto;padding:20px;line-height:1.5}
a{color:#9bc9ff}.button{display:block;padding:16px;margin:20px 0;background:#255dad;color:white;border-radius:10px;text-align:center;text-decoration:none}
</style><h1>Antigravity sign-in</h1>
<p>Use the Google account with your AI Pro subscription.</p>''' + action + '''
<p>After Google sign-in, copy the authorization code, open the terminal below,
paste it into the authorization-code prompt, and press Return.</p>
<a class="button" href="controls">Open mobile terminal</a>
<p><a href="signin">Refresh sign-in link</a></p>
<p>To return here from the terminal, use Back or reopen the add-on's Open Web UI.</p>
<p><a href="https://antigravity.google.com" target="_blank" rel="noopener noreferrer">Open Remote Control</a> after signing in.</p></html>''').encode()


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        route = self.path.split('?', 1)[0]
        if route not in {'/signin', '/controls'}:
            self.send_error(404)
            return
        body = (Path(__file__).with_name('mobile.html').read_text().replace('__CSRF__', CSRF).encode()
                if route == '/controls' else render(current_url()))
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path != '/input':
            self.send_error(404)
            return
        status = 200
        try:
            token = self.headers.get('X-Antigravity-CSRF', '')
            if not token.isascii() or not secrets.compare_digest(token, CSRF):
                status = 403
                raise ValueError('Reopen the mobile controls page and try again.')
            if self.headers.get('Content-Type') != 'application/json':
                raise ValueError('Expected JSON.')
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 1024:
                raise ValueError('Request is empty or too large.')
            self.connection.settimeout(15)
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict):
                raise ValueError('Invalid request.')
            result = send_input(payload)
        except (ValueError, TypeError):
            status = status if status != 200 else 400
            result = {'error': 'Invalid request. Refresh controls; use a valid navigation key.'}
        except (OSError, subprocess.SubprocessError):
            status = 503
            result = {'error': 'Terminal unavailable. Check that the add-on is running.'}
        body = json.dumps(result).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass  # Do not log authentication URLs or terminal output.


if __name__ == '__main__':
    ThreadingHTTPServer(('127.0.0.1', 7682), Handler).serve_forever()
