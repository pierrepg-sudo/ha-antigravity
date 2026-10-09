"""Separate-UID, serial command broker. Never execute a request without confinement."""
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

SOCKET = '/run/antigravity-worker/worker.sock'
STATUS = Path('/run/antigravity-worker/status.json')
MAX_REQUEST = 65536
MAX_OUTPUT = 262144
TMP = Path('/tmp/agy-worker')


def execute(command, label, timeout=90):
    if not isinstance(command, str) or not command.strip() or len(command.encode()) > 32768 or '\x00' in command:
        raise ValueError('Command must be nonempty text of at most 32768 bytes')
    job = tempfile.mkdtemp(prefix='job-', dir=TMP)
    process = None
    output = bytearray()
    timed_out = False
    truncated = False
    try:
        process = subprocess.Popen(
            ['/usr/bin/python3', '-I', '/usr/local/bin/network_job.py', label, job, command], stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True,
            close_fds=True, env={'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8'})
        with selectors.DefaultSelector() as poll:
            poll.register(process.stdout, selectors.EVENT_READ)
            end = time.monotonic() + timeout
            while poll.get_map():
                if time.monotonic() >= end:
                    timed_out = True
                    break
                for key, _ in poll.select(min(0.2, max(0, end-time.monotonic()))):
                    data = os.read(key.fileobj.fileno(), 8192)
                    if not data:
                        poll.unregister(key.fileobj)
                        continue
                    remaining = MAX_OUTPUT-len(output)
                    output.extend(data[:remaining])
                    truncated |= len(data) > remaining
            if not timed_out:
                try:
                    process.wait(timeout=max(0.01, end-time.monotonic()))
                except subprocess.TimeoutExpired:
                    timed_out = True
    finally:
        if process is not None:
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
    result = execute(script, label, timeout=40)
    ready = result['exitCode'] == 0 and not result['timedOut'] and result['output'].strip() == 'WORKER_ISOLATION_OK'
    # This output is solely from the fixed check above, not user commands or logs.
    return ready, '' if ready else result['output'][:2048] or 'Isolation check timed out or exited without a result.'


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
            if not isinstance(request, dict) or set(request) != {'command'}:
                raise ValueError('Invalid request')
            if not self.server.ready:
                response = {'error': 'Restricted worker isolation checks failed. No command was run. Check add-on logs.'}
            else:
                response = execute(request['command'], self.server.label)
        except (ValueError, OSError, subprocess.SubprocessError):
            response = {'error': 'Restricted worker request failed; no unsandboxed fallback is available.'}
        self.wfile.write(json.dumps(response).encode()+b'\n')


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
    with socketserver.UnixStreamServer(SOCKET, Handler) as server:
        os.chmod(SOCKET, 0o660)
        server.ready, server.label = ready, label
        server.serve_forever()


if __name__ == '__main__':
    main()
