"""Private connection to the CLI-owned local language server; no secret logging."""
import http.client
import json
import os
from pathlib import Path
import stat
import tempfile
from urllib.parse import urlsplit

STATE = Path('/data/home/.gemini/antigravity-cli/ha-native-connection.json')
SERVICE = '/exa.language_server_pb.LanguageServerService/'
LIST = 'GetAllCascadeTrajectories'
DELETE = 'DeleteCascadeTrajectory'

class NativeError(Exception):
    pass


def process(pid):
    directory = Path('/proc') / str(pid)
    if directory.stat().st_uid != os.getuid():
        raise NativeError('The CLI process owner does not match the add-on.')
    fields = (directory / 'stat').read_text().rsplit(')', 1)[1].split()
    return int(fields[1]), fields[19], Path(os.readlink(directory / 'exe')).name.removesuffix(' (deleted)')


def cli_parent():
    pid = os.getppid()
    for _ in range(64):
        if pid <= 1:
            break
        parent, started, name = process(pid)
        if name in {'agy', 'antigravity'}:
            return pid, started
        pid = parent
    raise NativeError('Ask Antigravity to run this command as a tool. A regular terminal shell does not receive its API credentials.')


def validate(connection):
    try:
        if set(connection) != {'pid', 'started', 'host', 'port', 'token'}:
            raise ValueError()
        if type(connection['pid']) is not int or connection['pid'] <= 1:
            raise ValueError()
        if connection['host'] not in {'127.0.0.1', '::1'}:
            raise ValueError()
        if type(connection['port']) is not int or not 1 <= connection['port'] <= 65535:
            raise ValueError()
        token = connection['token']
        if not isinstance(token, str) or not 1 <= len(token) <= 4096 or any(ord(c) < 33 or ord(c) > 126 for c in token):
            raise ValueError()
        _, started, name = process(connection['pid'])
        if name not in {'agy', 'antigravity'} or started != connection['started']:
            raise ValueError()
    except (OSError, ValueError, TypeError, KeyError):
        raise NativeError('The native connection is invalid or the CLI restarted. Ask Antigravity to run antigravity-connect again.') from None


def rpc(connection, method, payload):
    if method not in {LIST, DELETE}:
        raise NativeError('Unsupported native operation.')
    validate(connection)
    client = http.client.HTTPConnection(connection['host'], connection['port'], timeout=8)
    try:
        client.request('POST', SERVICE + method, body=json.dumps(payload).encode(), headers={
            'Content-Type':'application/json', 'x-codeium-csrf-token':connection['token']})
        response = client.getresponse()
        body = response.read(16 * 1024 * 1024 + 1)
        if response.status != 200:
            raise NativeError(f'Native API returned HTTP {response.status}. No automatic retry was made. Refresh or reconnect before trying again.')
        if len(body) > 16 * 1024 * 1024:
            raise NativeError('Native API response exceeds the size limit.')
        result = json.loads(body)
        if not isinstance(result, dict) or 'error' in result or 'code' in result:
            raise NativeError('Native API returned an unexpected response.')
        return result
    except (OSError, http.client.HTTPException, ValueError):
        raise NativeError('Native API response could not be verified. If deleting, the outcome is unknown; refresh before retrying.') from None
    finally:
        client.close()


def summaries(connection):
    result = rpc(connection, LIST, {})
    items = result.get('trajectorySummaries', {})
    if set(result) - {'trajectorySummaries'} or not isinstance(items, dict) or any(not isinstance(v,dict) for v in items.values()):
        raise NativeError('Unrecognized native conversation list. No deletion was attempted.')
    return items


def load():
    try:
        fd = os.open(STATE, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, 'rb') as handle:
            info = os.fstat(handle.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise NativeError('Native connection file must be private to the add-on user.')
            content = handle.read(16385)
        if len(content) > 16384:
            raise ValueError()
        connection = json.loads(content)
        validate(connection)
        return connection
    except (OSError, ValueError, TypeError):
        raise NativeError('Native API is not connected. Ask Antigravity to run /usr/local/bin/antigravity-connect, then refresh.') from None


def pair():
    address = os.environ.get('ANTIGRAVITY_LS_ADDRESS', '')
    token = os.environ.get('ANTIGRAVITY_CSRF_TOKEN', '')
    try:
        url = urlsplit('http://' + address)
        if url.hostname not in {'localhost','127.0.0.1','::1'} or url.username or url.password or url.path or url.query or url.fragment or not url.port:
            raise ValueError()
        host, port = ('::1' if url.hostname == '::1' else '127.0.0.1'), url.port
    except ValueError:
        raise NativeError('No valid local API address was supplied. Run this command through an Antigravity tool.') from None
    pid, started = cli_parent()
    connection = dict(pid=pid, started=started, host=host, port=port, token=token)
    items = summaries(connection)  # Read-only verification before storing credentials.
    STATE.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.ha-native-', dir=STATE.parent)
    try:
        with os.fdopen(fd, 'w') as handle:
            os.fchmod(handle.fileno(), 0o600)
            json.dump(connection, handle)
            handle.flush(); os.fsync(handle.fileno())
        os.replace(temporary, STATE)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)
    print(f'Native API connected. Read-only listing succeeded ({len(items)} conversations). No conversations deleted.')
