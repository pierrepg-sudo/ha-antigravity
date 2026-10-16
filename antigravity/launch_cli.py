"""Own the CLI's local authentication and publish a verified private connection."""
import os
import json
import socket
import conversation_session as session
from pathlib import Path
import re
import secrets
import signal
import subprocess
import tempfile
import threading
import time
import native_connection as native

# Resume the workspace's last session instead of creating a new one on each boot.
STARTUP_ARGS = ['--remote-control', '--continue']


def start(binary, args, log, **stdio):
    token = secrets.token_urlsafe(48)
    # The private directory and mode protect CLI logs; tokens are never logged here.
    fd = os.open(log, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(fd)
    child = subprocess.Popen([binary, '--csrf_token=' + token, '--log-file=' + str(log), *args], **stdio)
    return child, token


def connect(child, token, log, stop, timeout=60):
    deadline = time.monotonic() + timeout
    try:
        _, started = native.process(child.pid)
        native.record_status('starting')
        while child.poll() is None and not stop.is_set() and time.monotonic() < deadline:
            with open(log, 'r', errors='replace') as handle:
                text = handle.read(1024 * 1024)
            pid = re.search(r'Starting language server process with pid (\d+)', text)
            port = re.search(r'Language server listening on (?:random )?port at (\d+) for HTTP\b', text)
            if pid and int(pid[1]) == child.pid and port:
                for host in ('127.0.0.1', '::1'):
                    connection = dict(pid=child.pid, started=started, host=host, port=int(port[1]), token=token)
                    try:
                        native.summaries(connection)
                        if child.poll() is not None or stop.is_set():
                            return False
                        native.save(connection)
                        native.record_status('connected')
                        return True
                    except native.NativeError:
                        continue
            stop.wait(.25)
        native.record_status('unavailable')
    except (OSError, native.NativeError):
        try:
            native.record_status('storage')
        except OSError:
            print('Conversations: cannot store local connection status.', flush=True)
    return False


def handoff(request, child):
    if not isinstance(request, dict) or set(request) != {'payload', 'pid', 'started'}:
        raise native.NativeError('Invalid session request.')
    connection = native.load()
    if connection['pid'] != child.pid or request['pid'] != child.pid or request['started'] != connection['started']:
        raise native.NativeError('The CLI session changed. Refresh and try again.')
    args = session.launch_args(request['payload'], connection)
    args = session.materialize(request['payload'], connection, args)
    child.terminate()
    child.wait(timeout=8)
    if request['payload'].get('action') == 'model':
        session.models.remember(request['payload']['id'], request['payload']['model'])
    return args


def main():
    native.STATE.parent.mkdir(parents=True, exist_ok=True)
    native.STATE.unlink(missing_ok=True)
    native.record_status('starting')
    path = session.socket_path()
    path.unlink(missing_ok=True)
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
        listener.bind(str(path))
        os.chmod(path, 0o600)
        listener.listen(1)
        listener.settimeout(.25)
        child = None
        def terminate(signum, frame):
            if child is not None and child.poll() is None:
                child.send_signal(signum)
            raise SystemExit(0)
        signal.signal(signal.SIGTERM, terminate)
        signal.signal(signal.SIGINT, lambda *_: None)
        args = STARTUP_ARGS
        cached_model = session.models.preferences().get(session.models.active_id(), '')
        if cached_model:
            args = [*args, '--model=' + cached_model]
        try:
            while True:
                with tempfile.TemporaryDirectory(prefix='.ha-cli-', dir=native.STATE.parent) as directory:
                    log = Path(directory) / 'cli.log'
                    child, token = start('/data/home/.local/bin/agy', args, log, env=session.environment(args))
                    stop = threading.Event()
                    thread = threading.Thread(target=connect, args=(child, token, log, stop), daemon=True)
                    thread.start()
                    switched = False
                    try:
                        while child.poll() is None:
                            try:
                                client, _ = listener.accept()
                            except socket.timeout:
                                continue
                            with client:
                                client.settimeout(3)
                                try:
                                    request = json.loads(client.makefile('rb').readline(8193))
                                    next_args = handoff(request, child)
                                    args = next_args
                                    switched = True
                                    result = {'ok': True}
                                except native.NativeError as error:
                                    result = {'error': str(error)}
                                except (OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired):
                                    result = {'error': 'Could not switch the terminal session. Check Terminal before retrying.'}
                                try:
                                    client.sendall(json.dumps(result).encode() + b'\n')
                                except OSError:
                                    pass
                            if switched:
                                break
                    finally:
                        stop.set()
                        thread.join(timeout=18)
                        native.STATE.unlink(missing_ok=True)
                    if not switched:
                        return child.wait()
        finally:
            path.unlink(missing_ok=True)
            native.STATE.unlink(missing_ok=True)
            native.record_status('stopped')


if __name__ == '__main__':
    raise SystemExit(main())
