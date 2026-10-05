"""Read-only OAuth link helper, reachable only through the HA ingress proxy."""
import html
import re
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit


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
<a class="button" href="./">Open terminal</a>
<p><a href="signin">Refresh sign-in link</a></p>
<p>To return here from the terminal, use Back or reopen the add-on's Open Web UI.</p>
<p><a href="https://antigravity.google.com" target="_blank" rel="noopener noreferrer">Open Remote Control</a> after signing in.</p></html>''').encode()


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.split('?', 1)[0] != '/signin':
            self.send_error(404)
            return
        body = render(current_url())
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass  # Do not log authentication URLs or terminal output.


if __name__ == '__main__':
    ThreadingHTTPServer(('127.0.0.1', 7682), Handler).serve_forever()
