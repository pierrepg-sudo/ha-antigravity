"""Separate-UID command and managed-job broker. Never execute a request without confinement."""
import json
import os
from pathlib import Path
import selectors
import shutil
import signal
import socket
import socketserver
import struct
import subprocess
import tempfile
import time
import threading
import uuid
import re

SOCKET = '/run/antigravity-worker/worker.sock'
STATUS = Path('/run/antigravity-worker/status.json')
MAX_REQUEST = 65536
MAX_OUTPUT = 262144
TMP = Path('/tmp/agy-worker')


def validate_command(command):
    if not isinstance(command, str) or not command.strip() or len(command.encode()) > 32768 or '\x00' in command:
        raise ValueError('Command must be nonempty text of at most 32768 bytes')


def execute(command, label, timeout=90, stop=None, capture=None):
    validate_command(command)
    managed = stop is not None
    job = tempfile.mkdtemp(prefix='job-', dir=TMP)
    process = None
    output = bytearray()
    timed_out = False
    truncated = False
    try:
        process = subprocess.Popen(
            ['/usr/bin/python3', '-I', '/usr/local/bin/network_job.py', label, job, command] + (['managed'] if managed else []), stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True,
            close_fds=True, env={'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8'})
        with selectors.DefaultSelector() as poll:
            poll.register(process.stdout, selectors.EVENT_READ)
            end = time.monotonic() + timeout if timeout is not None else float('inf')
            exited_at = None
            while True:
                # Observe exit without reaping: reserve the leader PID until all
                # process-group signals have been sent, avoiding PID reuse races.
                exited = os.waitid(os.P_PID, process.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
                if exited is not None:
                    if exited_at is None:
                        exited_at = time.monotonic()
                    if not poll.get_map() or time.monotonic() - exited_at >= .2:
                        break
                if stop is not None and stop.is_set():
                    break
                if time.monotonic() >= end:
                    timed_out = True
                    break
                for key, _ in poll.select(min(0.2, max(0, end-time.monotonic()))):
                    data = os.read(key.fileobj.fileno(), 8192)
                    if not data:
                        poll.unregister(key.fileobj)
                        continue
                    if capture is not None:
                        capture(data)
                    remaining = MAX_OUTPUT-len(output)
                    output.extend(data[:remaining])
                    truncated |= len(data) > remaining
    finally:
        if process is not None:
            # Managed jobs get a short grace period, then all descendants and
            # network helpers are killed, including children retaining pipes.
            if managed:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                # Keep the group leader unreaped during the grace period.
                time.sleep(2)
            # The filter prevents descendants leaving the job's process group.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
            process.stdout.close()
        # Python uses fd-relative, symlink-safe rmtree on Linux.
        shutil.rmtree(job)
    return {'exitCode': process.returncode, 'timedOut': timed_out,
            'truncated': truncated, 'output': output.decode('utf-8', errors='replace')}


def self_test(label):
    """Actual child checks, not a namespace preflight. No real secrets are read."""
    script = r'''/usr/bin/python3 -I - <<'PY'
import errno, os, socket, subprocess, tempfile, threading
assert os.getuid() == 0
assert open('/proc/self/uid_map').read().split() == ['0', '1002', '1']
assert 'CapEff:\t0000000000000000' in open('/proc/self/status').read()
status = open('/proc/self/status').read()
assert 'NoNewPrivs:\t1' in status and 'Seccomp:\t2' in status
# A world-readable root-owned canary tests AppArmor, not just DAC.
for path, mode in [('/run/antigravity/worker-deny-canary', 'rb'),
                   ('/data/inputs/.worker-write-probe', 'wb')]:
    try:
        f = open(path, mode)
    except PermissionError:
        pass
    else:
        f.close()
        raise AssertionError('Filesystem boundary failed')
for family in (socket.AF_UNIX, socket.AF_NETLINK, socket.AF_PACKET):
    try:
        s = socket.socket(family)
    except PermissionError:
        pass
    else:
        s.close()
        raise AssertionError('Socket boundary failed')
# Exercise the anonymous IPC and thread startup used by curl's DNS resolver.
try:
    reader, writer = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    with reader, writer:
        reader.settimeout(3)
        thread = threading.Thread(target=writer.sendall, args=(b'resolver-check',))
        thread.start()
        thread.join(3)
        assert not thread.is_alive()
        assert reader.recv(64) == b'resolver-check'
except Exception as exc:
    raise AssertionError('Resolver thread/socketpair check failed') from exc
# The trusted namespace launcher already verified kernel reject counters before
# dropping capabilities. Check that the final profile permits IP socket creation.
for family in (socket.AF_INET, socket.AF_INET6):
    for kind in (socket.SOCK_STREAM, socket.SOCK_DGRAM):
        with socket.socket(family, kind):
            pass
with tempfile.TemporaryFile(dir='/data/workspace/outputs') as f:
    f.write(b'worker-check')
    f.seek(0)
    assert f.read() == b'worker-check'
assert subprocess.run(['/usr/bin/true']).returncode == 0
assert os.listdir('/data/inputs') is not None
try:
    os.setsid()
except PermissionError:
    pass
else:
    raise AssertionError('Process containment failed')
print('WORKER_ISOLATION_OK')
PY'''
    # Both launcher modes must pass identical checks before tools become ready.
    for mode in ('run', 'managed'):
        result = execute(script, label, timeout=40,
                         stop=threading.Event() if mode == 'managed' else None)
        ready = result['exitCode'] == 0 and not result['timedOut'] and result['output'].strip() == 'WORKER_ISOLATION_OK'
        if not ready:
            return False, mode + ': ' + (result['output'][:2000] or 'Isolation check timed out or exited without a result.')
    return True, ''



class Jobs:
    """In-memory job ownership; no arbitrary PID control or restart replay."""
    def __init__(self, label):
        self.label = label
        self.lock = threading.RLock()
        self.items = {}
        self.closing = False

    def summary(self, item):
        return {key: item[key] for key in
                ('id', 'name', 'state', 'started', 'finished', 'exitCode', 'truncated')}

    def start(self, command, name):
        validate_command(command)
        if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}', name):
            raise ValueError('Use a job name of 1-64 letters, digits, dots, dashes or underscores')
        with self.lock:
            if self.closing:
                raise ValueError('Worker is shutting down')
            active = [j for j in self.items.values() if j['state'] in ('starting', 'running', 'stopping')]
            for j in active:
                if j['name'] == name or j['command'] == command:
                    return dict(self.summary(j), alreadyRunning=True)
            if len(active) >= 2:
                raise ValueError('Two managed jobs are already active; stop one first')
            while len(self.items) >= 20:
                old = next(k for k, j in self.items.items() if j not in active)
                del self.items[old]
            item = dict(id=uuid.uuid4().hex, name=name, command=command, state='starting',
                        started=time.time(), finished=None, exitCode=None, truncated=False,
                        output=bytearray(), stop=threading.Event())
            self.items[item['id']] = item
            item['thread'] = threading.Thread(target=self.work, args=(item,))
            item['thread'].start()
            return self.summary(item)

    def work(self, item):
        def capture(data):
            with self.lock:
                item['output'].extend(data)
                if len(item['output']) > MAX_OUTPUT:
                    del item['output'][:-MAX_OUTPUT]
                    item['truncated'] = True
        with self.lock:
            if not item['stop'].is_set():
                item['state'] = 'running'
        try:
            result = execute(item['command'], self.label, timeout=None,
                             stop=item['stop'], capture=capture)
            code = result['exitCode']
        except Exception:
            capture(b'Worker launch or cleanup failed. No fallback was attempted.\n')
            code = 125
        with self.lock:
            item['exitCode'] = code
            item['state'] = 'stopped' if item['stop'].is_set() else ('exited' if code == 0 else 'failed')
            item['finished'] = time.time()

    def request(self, action, args):
        if action == 'start':
            if set(args) != {'command', 'name'}:
                raise ValueError('Expected command and name')
            return self.start(**args)
        with self.lock:
            if action == 'status' and not args:
                return {'jobs': [self.summary(j) for j in self.items.values()]}
            if set(args) != {'job_id'} or not isinstance(args['job_id'], str):
                raise ValueError('Expected job_id from start or status')
            item = self.items.get(args['job_id'])
            if item is None:
                raise ValueError('Unknown job; job IDs are valid only until add-on restart')
            if action == 'stop':
                if item['state'] in ('starting', 'running', 'stopping'):
                    item['state'] = 'stopping'
                    item['stop'].set()
            elif action == 'logs':
                return dict(self.summary(item), output=item['output'].decode('utf-8', errors='replace'))
            elif action != 'status':
                raise ValueError('Unknown job operation')
            return self.summary(item)

    def close(self):
        with self.lock:
            self.closing = True
            items = list(self.items.values())
            for item in items:
                if item['state'] in ('starting', 'running', 'stopping'):
                    item['state'] = 'stopping'
                    item['stop'].set()
        for item in items:
            item['thread'].join()


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        self.connection.settimeout(100)
        _, uid, _ = struct.unpack('3i', self.connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
        if uid != 1000:
            return
        try:
            raw = self.rfile.readline(MAX_REQUEST+1)
            if len(raw) > MAX_REQUEST or not raw.endswith(b'\n'):
                raise ValueError('Invalid request size')
            request = json.loads(raw)
            if not isinstance(request, dict):
                raise ValueError('Invalid request')
            if not self.server.ready:
                response = {'error': 'Restricted worker isolation checks failed. No command was run. Check add-on logs.'}
            elif set(request) == {'command'}:
                if not self.server.run_lock.acquire(blocking=False):
                    raise ValueError('A short command is already running')
                try:
                    response = execute(request['command'], self.server.label)
                finally:
                    self.server.run_lock.release()
            elif set(request) == {'action', 'args'} and request['action'] in ('start', 'stop', 'status', 'logs') and isinstance(request['args'], dict):
                response = self.server.jobs.request(request['action'], request['args'])
            else:
                raise ValueError('Invalid request')
        except ValueError as exc:
            response = {'error': str(exc)}
        except (OSError, subprocess.SubprocessError):
            response = {'error': 'Restricted worker request failed; no unsandboxed fallback is available.'}
        self.wfile.write(json.dumps(response).encode()+b'\n')


class Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    # Control calls remain responsive while a short command runs. Bound clients.
    daemon_threads = False
    def __init__(self, *args):
        self.slots = threading.BoundedSemaphore(8)
        self.run_lock = threading.Lock()
        super().__init__(*args)

    def process_request(self, request, address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, address)
        except Exception:
            self.slots.release()
            raise

    def process_request_thread(self, request, address):
        try:
            super().process_request_thread(request, address)
        finally:
            self.slots.release()


def main():
    if os.getuid() != 1002:
        raise SystemExit('Worker must run as UID 1002')
    outer = Path('/proc/self/attr/current').read_text().strip()
    if not outer.endswith(' (enforce)') or '//' in outer:
        raise SystemExit('Worker requires the enforced outer AppArmor profile')
    label = outer.removesuffix(' (enforce)') + '//command_worker'
    try:
        ready, error = self_test(label)
    except (OSError, ValueError, subprocess.SubprocessError):
        ready, error = False, 'Cannot launch the isolation check.'
    message = ('Restricted commands ready: inputs read-only; outputs writable; public internet enabled; private/local networks blocked.'
               if ready else 'Restricted commands unavailable: isolation checks failed. Commands remain blocked.')
    STATUS.write_text(json.dumps({'ready': ready, 'message': message, 'error': error})+'\n')
    STATUS.chmod(0o640)
    print(message, flush=True)
    if error:
        print(error, flush=True)
    with Server(SOCKET, Handler) as server:
        os.chmod(SOCKET, 0o660)
        server.ready, server.label = ready, label
        server.jobs = Jobs(label)
        def shutdown(signum, frame):
            raise SystemExit(0)
        signal.signal(signal.SIGTERM, shutdown)
        signal.signal(signal.SIGINT, shutdown)
        try:
            server.serve_forever()
        finally:
            server.jobs.close()


if __name__ == '__main__':
    main()
