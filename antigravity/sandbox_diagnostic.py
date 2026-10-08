"""Expose only a bounded, allowlisted sandbox failure summary, never raw logs."""
from datetime import datetime, timezone
import os
from pathlib import Path
import re
import stat

LIMIT = 65536
WORDS = {'mount', 'remount', 'unmount', 'tmpfs', 'proc', 'private', 'root', 'ro', 'bind'}
PATHS = {'/', '/dev/shm', '/dev/shm/setup', '/dev/shm/setup/root',
         '/dev/shm/setup/root/dev/shm', '/proc', '/proc/cpuinfo', '/proc/meminfo'}
ERRORS = {'permission denied', 'operation not permitted', 'read-only file system',
          'invalid argument', 'no such file or directory', 'device or resource busy',
          'function not implemented', 'no space left on device'}


def summarize(line):
    """No free-form text is returned, even if credentials occur in an error line."""
    match = re.fullmatch(r'sbox: (mount|remount|unmount) (.{1,1024}): ([a-z -]+)', line)
    if not match or match[3] not in ERRORS:
        return 'sbox: Unrecognized sandbox error; details withheld.'
    tokens = match[2].split()
    if len(tokens) > 8:
        return 'sbox: Unrecognized sandbox error; details withheld.'
    safe = [t if t in WORDS or t in PATHS or
            re.fullmatch(r'/dev/shm/setup/mnt[0-9]{1,8}', t) else '[REDACTED]'
            for t in tokens]
    return 'sbox: ' + match[1] + ' ' + ' '.join(safe) + ': ' + match[3]


def latest(base=None):
    base = Path.home() / '.gemini/antigravity-cli' if base is None else Path(base)
    try:
        # The normal cli.log symlink must name a single timestamped file in log/.
        target = os.readlink(base / 'cli.log')
        if target.startswith(str(base / 'log') + '/'):
            target = 'log/' + target[len(str(base / 'log')) + 1:]
        if not re.fullmatch(r'log/cli-[0-9]{8}_[0-9]{6}\.log', target):
            return {'message': 'Sandbox log unavailable: unexpected log link.'}
        directory = os.open(base / 'log', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            fd = os.open(target[4:], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        finally:
            os.close(directory)
        with os.fdopen(fd, 'rb') as source:
            info = os.fstat(source.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                return {'message': 'Sandbox log unavailable: unexpected file type.'}
            start = max(0, info.st_size - LIMIT)
            source.seek(start)
            data = source.read(LIMIT)
        if start:
            data = data.partition(b'\n')[2]  # Never report a partial first line.
        lines = data.decode('utf-8', errors='replace').splitlines()
        for line in reversed(lines):
            if line.startswith('sbox:'):
                return {'message': summarize(line),
                        'logModifiedUTC': datetime.fromtimestamp(info.st_mtime, timezone.utc).isoformat(),
                        'note': 'Latest error in the current log tail; it may predate your last test.'}
        return {'message': 'No sbox error found in the last 64 KiB of the current CLI log.'}
    except (OSError, ValueError):
        return {'message': 'Sandbox log unavailable.'}
