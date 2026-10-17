"""Private connection to the CLI-owned local language server; no secret logging."""
import http.client
import json
import os
from pathlib import Path
import stat
import tempfile
import time

STATE = Path('/data/home/.gemini/antigravity-cli/ha-native-connection.json')
SERVICE = '/exa.language_server_pb.LanguageServerService/'
LIST = 'GetAllCascadeTrajectories'
DELETE = 'DeleteCascadeTrajectory'
LOAD = 'LoadTrajectory'
START = 'StartCascade'

class NativeError(Exception):
    pass


def process(pid):
    # Never inspect an unrelated host PID when /proc belongs to another namespace.
    if int(Path('/proc/self/stat').read_text().split(' ', 1)[0]) != os.getpid():
        raise NativeError('The process filesystem does not match the CLI namespace.')
    directory = Path('/proc') / str(pid)
    if directory.stat().st_uid != os.getuid():
        raise NativeError('The CLI process owner does not match the add-on.')
    fields = (directory / 'stat').read_text().rsplit(')', 1)[1].split()
    return int(fields[1]), fields[19]


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
        _, started = process(connection['pid'])
        if started != connection['started']:
            raise ValueError()
    except (OSError, ValueError, TypeError, KeyError):
        raise NativeError('The native connection is invalid or the CLI restarted. Restart the add-on to establish a fresh local connection.') from None


def rpc(connection, method, payload):
    if method not in {LIST, DELETE, LOAD, START, 'ReadProject', 'CreateProject', 'UpdateProject',
                      'DeleteProject', 'UpdateConversationAnnotations',
                      'GetDefaultProjectDir', 'GetLocalUserInfo'}:
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
        raise NativeError(connection_diagnostic()) from None


def save(connection):
    validate(connection)
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

DIAGNOSTICS = {
    'starting': 'The CLI is starting. Local connection setup runs automatically.',
    'unavailable': 'The CLI local API could not be verified within 60 seconds. Check the CLI version and restart the add-on. No connection was saved.',
    'storage': 'The private local connection could not be stored or its process verified.',
    'connected': 'The saved connection is unavailable. Restart the add-on.',
    'stopped': 'The CLI has stopped. Restart the add-on to reconnect.',
}


def record_status(code):
    """Store only a fixed diagnostic code and timestamp, never an exception or env."""
    target = STATE.with_name('ha-native-status.json')
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.ha-native-status-', dir=target.parent)
    try:
        with os.fdopen(fd, 'w') as handle:
            os.fchmod(handle.fileno(), 0o600)
            json.dump({'code': code, 'time': int(time.time())}, handle)
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def connection_diagnostic():
    try:
        fd = os.open(STATE.with_name('ha-native-status.json'), os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, 'rb') as handle:
            info = os.fstat(handle.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise ValueError()
            status = json.loads(handle.read(1024))
        code = status['code']
        if code in DIAGNOSTICS:
            return DIAGNOSTICS[code] + ' [connection:' + code + ']'
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return 'Local connection setup has not reported. Restart the add-on. [connection:not-started]'
