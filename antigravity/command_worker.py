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
import fcntl
import stat

SOCKET = '/run/antigravity-worker/worker.sock'
STATUS = Path('/run/antigravity-worker/status.json')
MAX_REQUEST = 65536
MAX_OUTPUT = 262144
TMP = Path('/tmp/agy-worker')
RECOVERY = Path('/data/worker-state')
CWD = '/data/workspace/outputs'


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
    interrupted = False
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
                    interrupted = exited is None
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
    return {'exitCode': process.returncode, 'timedOut': timed_out, 'interrupted': interrupted,
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
                   ('/data/inputs/.worker-write-probe', 'wb'),
                   ('/data/worker-state/jobs.json', 'rb'),
                   ('/data/worker-state/.write-probe', 'wb')]:
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



class ResumeStore:
    """Broker-only, atomic recovery intent. Contents never enter MCP responses."""
    def __init__(self, directory):
        self.directory = Path(directory)
        info = self.directory.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
            raise ValueError('Recovery directory must be broker-owned mode 0700')
        self.guard = os.open(self.directory / 'broker.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(self.guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BaseException:
            os.close(self.guard)
            raise
        self.path = self.directory / 'jobs.json'
        try:
            self.records = self.load()
        except BaseException:
            self.close()
            raise

    def load(self):
        if not self.path.exists():
            self.write({})
            return {}
        fd = os.open(self.path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd) as f:
            info = os.fstat(f.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600:
                raise ValueError('Invalid recovery file permissions')
            raw = f.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024:
            raise ValueError('Recovery file too large')
        data = json.loads(raw)
        if not isinstance(data, dict) or set(data) != {'version', 'jobs'} or data['version'] != 1 or not isinstance(data['jobs'], dict) or len(data['jobs']) > 20:
            raise ValueError('Invalid recovery file')
        names, commands = set(), set()
        for ident, record in data['jobs'].items():
            if not re.fullmatch('[0-9a-f]{32}', ident) or not isinstance(record, dict) or set(record) != {'name', 'command', 'cwd', 'attempts', 'pending'}:
                raise ValueError('Invalid recovery record')
            validate_command(record['command'])
            if not isinstance(record['name'], str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}', record['name']) or record['cwd'] != CWD or type(record['pending']) is not bool:
                raise ValueError('Invalid recovery identity')
            if not isinstance(record['attempts'], list) or len(record['attempts']) > 3 or any(type(t) not in (int, float) or not 0 <= t < 1e12 for t in record['attempts']):
                raise ValueError('Invalid recovery attempts')
            if record['name'] in names or record['command'] in commands:
                raise ValueError('Duplicate recovery record')
            names.add(record['name']); commands.add(record['command'])
        return data['jobs']

    def write(self, records):
        fd, temporary = tempfile.mkstemp(prefix='.jobs-', dir=self.directory)
        try:
            with os.fdopen(fd, 'w') as f:
                json.dump({'version': 1, 'jobs': records}, f)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temporary, self.path)
            directory = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            Path(temporary).unlink(missing_ok=True)

    def put(self, ident, record=None):
        records = dict(self.records)
        if record is None:
            records.pop(ident, None)
        else:
            records[ident] = record
        self.write(records)
        self.records = records

    def close(self):
        os.close(self.guard)


class Jobs:
    """Managed jobs with opt-in durable restart intent and explicit stop semantics."""
    def __init__(self, label, store=None):
        self.label = label
        self.store = store
        self.lock = threading.RLock()
        self.items = {}
        self.closing = False
        self.recovery_error = None
        self.restored = False

    def summary(self, item):
        return {key: item[key] for key in
                ('id', 'name', 'state', 'started', 'finished', 'exitCode', 'truncated',
                 'resume_after_restart', 'recovery_count')}

    def record(self, item, pending=True):
        if self.store is None:
            raise ValueError('Persistent recovery storage is unavailable')
        self.store.put(item['id'], dict(name=item['name'], command=item['command'], cwd=CWD,
                                      attempts=item['attempts'], pending=pending))

    def forget(self, item):
        if self.store is not None and item['id'] in self.store.records:
            self.store.put(item['id'])

    def start(self, command, name, resume_after_restart=False, *, recovered=None):
        validate_command(command)
        if type(resume_after_restart) is not bool:
            raise ValueError('resume_after_restart must be boolean')
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
            if resume_after_restart and self.store is None:
                raise ValueError('Persistent recovery storage is unavailable')
            # An explicit new start supersedes inactive intent with the same identity.
            for j in list(self.items.values()):
                if j['name'] == name or j['command'] == command:
                    self.forget(j)
                    j['resume_after_restart'] = False
            while len(self.items) >= 20:
                old = next(k for k, j in self.items.items() if j not in active and not j['resume_after_restart'])
                del self.items[old]
            item = dict(id=recovered['id'] if recovered else uuid.uuid4().hex,
                        name=name, command=command, state='starting',
                        started=time.time(), finished=None, exitCode=None, truncated=False,
                        output=bytearray(), stop=threading.Event(), shutdown=False,
                        resume_after_restart=resume_after_restart,
                        attempts=recovered['attempts'] if recovered else [],
                        recovery_count=len(recovered['attempts']) if recovered else 0)
            if resume_after_restart:
                self.record(item)  # Durable authorization before any process can run.
            self.items[item['id']] = item
            item['thread'] = threading.Thread(target=self.work, args=(item,))
            try:
                item['thread'].start()
            except Exception:
                self.forget(item)
                item['state'] = 'failed'
                item['thread'] = None
                raise
            return self.summary(item)

    def restore(self):
        """Call once, only after startup isolation checks pass and before serving tools."""
        with self.lock:
            if self.restored:
                return
            self.restored = True
            self._restore()

    def _restore(self):
        if self.store is None:
            return
        for ident, record in list(self.store.records.items()):
            now = time.time()
            attempts = [t for t in record['attempts'] if now - t < 600]
            if not record['pending'] or len(attempts) >= 3 or len([j for j in self.items.values() if j['state'] in ('starting', 'running')]) >= 2:
                self.store.put(ident, dict(record, pending=False))
                self.items[ident] = dict(id=ident, name=record['name'], command=record['command'],
                    state='recovery_suspended', started=None, finished=None, exitCode=None,
                    truncated=False, resume_after_restart=True, recovery_count=len(attempts),
                    attempts=attempts, output=bytearray(b'Automatic recovery suspended; inspect and explicitly start again if authorized.\n'),
                    stop=threading.Event(), thread=None, shutdown=False)
                print('Managed job recovery suspended: ' + record['name'], flush=True)
                continue
            attempts.append(now)
            self.start(record['command'], record['name'], True, recovered={'id': ident, 'attempts': attempts})
            print('Recovering authorized managed job: ' + record['name'], flush=True)

    def work(self, item):
        def capture(data):
            with self.lock:
                item['output'].extend(data)
                if len(item['output']) > MAX_OUTPUT:
                    del item['output'][:-MAX_OUTPUT]
                    item['truncated'] = True
        with self.lock:
            if item['stop'].is_set():
                item['state'] = 'stopped'
                return
            item['state'] = 'running'
        interrupted = False
        try:
            result = execute(item['command'], self.label, timeout=None,
                             stop=item['stop'], capture=capture)
            code = result['exitCode']
            interrupted = result.get('interrupted', False)
        except Exception:
            capture(b'Worker launch or cleanup failed. No fallback was attempted.\n')
            code = 125
        with self.lock:
            item['exitCode'] = code
            item['state'] = 'stopped' if item['stop'].is_set() else ('exited' if code == 0 else 'failed')
            item['finished'] = time.time()
            if not (item['shutdown'] and interrupted and item['resume_after_restart']):
                try:
                    self.forget(item)
                    item['resume_after_restart'] = False
                except OSError:
                    self.recovery_error = 'Recovery storage update failed; restart intent may be stale. Check add-on storage before reboot.'
                    capture((self.recovery_error + '\n').encode())
                    print(self.recovery_error, flush=True)

    def request(self, action, args):
        if action == 'start':
            if not {'command', 'name'} <= set(args) or set(args) - {'command', 'name', 'resume_after_restart'}:
                raise ValueError('Expected command, name and optional resume_after_restart')
            return self.start(**args)
        with self.lock:
            if action == 'status' and not args:
                result = {'jobs': [self.summary(j) for j in self.items.values()]}
                if self.recovery_error:
                    result['error'] = self.recovery_error
                return result
            expected = {'job_id', 'resume_after_restart'} if action == 'restart_policy' else {'job_id'}
            if set(args) != expected or not isinstance(args['job_id'], str):
                raise ValueError('Expected job_id from start or status and restart_policy boolean when applicable')
            item = self.items.get(args['job_id'])
            if item is None:
                raise ValueError('Unknown job; call status with {} for current IDs')
            if action == 'restart_policy':
                enabled = args['resume_after_restart']
                if type(enabled) is not bool:
                    raise ValueError('resume_after_restart must be boolean')
                if enabled:
                    if item['state'] not in ('starting', 'running') or self.closing:
                        raise ValueError('Enable restart only for an active job; explicitly start inactive jobs')
                    self.record(item)
                else:
                    self.forget(item)
                item['resume_after_restart'] = enabled
            elif action == 'stop':
                self.forget(item)  # Persist stop before signalling; do not resurrect after a crash.
                item['resume_after_restart'] = False
                if item['state'] in ('starting', 'running', 'stopping'):
                    item['state'] = 'stopping'
                    item['stop'].set()
                elif item['state'] == 'recovery_suspended':
                    item['state'] = 'stopped'
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
                if item['state'] in ('starting', 'running'):
                    item['shutdown'] = True
                    item['state'] = 'stopping'
                    item['stop'].set()
        for item in items:
            if item['thread'] is not None:
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
            elif set(request) == {'action', 'args'} and request['action'] in ('start', 'stop', 'status', 'logs', 'restart_policy') and isinstance(request['args'], dict):
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
    store = ResumeStore(RECOVERY)  # Exclusive broker lock held for the process lifetime.
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
    try:
        with Server(SOCKET, Handler) as server:
            os.chmod(SOCKET, 0o660)
            server.ready, server.label = ready, label
            server.jobs = Jobs(label, store)
            def shutdown(signum, frame):
                raise SystemExit(0)
            signal.signal(signal.SIGTERM, shutdown)
            signal.signal(signal.SIGINT, shutdown)
            try:
                if ready:
                    server.jobs.restore()
                server.serve_forever()
            finally:
                server.jobs.close()
    finally:
        store.close()



if __name__ == '__main__':
    main()
