"""Own the CLI's local authentication and publish a verified private connection."""
import os
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


def main():
    native.STATE.parent.mkdir(parents=True, exist_ok=True)
    native.STATE.unlink(missing_ok=True)
    native.record_status('starting')
    # Temporary logs are session-owned and removed when this CLI exits.
    with tempfile.TemporaryDirectory(prefix='.ha-cli-', dir=native.STATE.parent) as directory:
        log = Path(directory) / 'cli.log'
        child, token = start('/data/home/.local/bin/agy', STARTUP_ARGS, log)
        stop = threading.Event()
        thread = threading.Thread(target=connect, args=(child, token, log, stop), daemon=True)
        thread.start()
        def terminate(signum, frame):
            if child.poll() is None:
                child.send_signal(signum)
        signal.signal(signal.SIGTERM, terminate)
        # Both processes share the terminal; let the CLI handle Ctrl+C itself.
        signal.signal(signal.SIGINT, lambda *_: None)
        try:
            result = child.wait()
        finally:
            stop.set()
            thread.join(timeout=18)
            native.STATE.unlink(missing_ok=True)
            native.record_status('stopped')
        return result


if __name__ == '__main__':
    raise SystemExit(main())
