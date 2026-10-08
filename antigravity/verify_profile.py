"""Refuse to start the experimental build without its enforced HA profile."""
from pathlib import Path
import re
import socket


def verify(path=Path('/proc/self/attr/current'), hostname=None):
    host = socket.gethostname() if hostname is None else hostname
    expected = host.replace('-', '_')
    if not re.fullmatch(r'(?:[a-f0-9]{8}|local)_antigravity_remote', expected):
        raise RuntimeError('Cannot establish the Home Assistant add-on profile identity.')
    try:
        current = path.read_text().strip()
    except OSError as error:
        raise RuntimeError('Cannot read the active AppArmor profile; startup stopped.') from error
    if current != expected + ' (enforce)':
        raise RuntimeError('Required add-on AppArmor profile is not enforced; startup stopped. Check Supervisor AppArmor logs. Do not disable protection.')
    return current


if __name__ == '__main__':
    try:
        print('AppArmor verified: ' + verify(), flush=True)
    except RuntimeError as error:
        raise SystemExit(str(error))
