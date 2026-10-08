"""Root-only storage setup. Never follow user-controlled symlinks."""
import json
import os
from pathlib import Path
import stat
import secrets
from prepare_settings import trusted_domains


def managed_directory(path, uid, gid, mode):
    path.mkdir(exist_ok=True)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode):
        raise ValueError('Managed path must be a real directory')
    os.chown(path, uid, gid, follow_symlinks=False)
    path.chmod(mode)


def prepare(base=Path('/data'), runtime=Path('/run/antigravity')):
    # Startup runs before any non-root services. Refuse unexpected path types.
    managed_directory(base, 0, 0, 0o755)
    managed_directory(base / 'home', 1000, 1000, 0o700)
    managed_directory(base / 'workspace', 0, 0, 0o755)
    managed_directory(base / 'workspace/outputs', 1000, 1000, 0o2770)
    managed_directory(base / 'inputs', 1001, 1000, 0o2750)
    # Inputs must remain owned by the file service, including after restores.
    for root, dirs, files in os.walk(base / 'inputs', followlinks=False):
        for name in dirs + files:
            path = Path(root) / name
            info = path.lstat()
            if not (stat.S_ISDIR(info.st_mode) or (stat.S_ISREG(info.st_mode) and info.st_nlink == 1)):
                raise ValueError('Inputs may only contain real directories and single-link regular files')
            os.chown(path, 1001, 1000, follow_symlinks=False)
            path.chmod(0o2750 if stat.S_ISDIR(info.st_mode) else 0o640)
    # Existing workspace data stays in place. Grant the file service group read
    # and traversal only; do not change ownership or follow symbolic links.
    for root, dirs, files in os.walk(base / 'workspace', followlinks=False):
        if Path(root) == base / 'workspace':
            dirs[:] = [name for name in dirs if name != 'outputs']
        for name in dirs + files:
            path = Path(root) / name
            info = path.lstat()
            if stat.S_ISDIR(info.st_mode) or (stat.S_ISREG(info.st_mode) and info.st_nlink == 1):
                os.chown(path, -1, 1000, follow_symlinks=False)
                path.chmod(stat.S_IMODE(info.st_mode) | (0o50 if stat.S_ISDIR(info.st_mode) else 0o40))
    # Restore group-read access on generated output without broadening it to others.
    for root, dirs, files in os.walk(base / 'workspace/outputs', followlinks=False):
        for name in dirs + files:
            path = Path(root) / name
            info = path.lstat()
            if stat.S_ISDIR(info.st_mode) or (stat.S_ISREG(info.st_mode) and info.st_nlink == 1):
                os.chown(path, 1000, 1000, follow_symlinks=False)
                path.chmod(stat.S_IMODE(info.st_mode) | (0o2070 if stat.S_ISDIR(info.st_mode) else 0o60))
    managed_directory(runtime, 0, 0, 0o755)
    options = json.loads((base / 'options.json').read_text()) if (base / 'options.json').exists() else {}
    domains = trusted_domains(options.get('trusted_read_domains', []))
    domain_path = runtime / 'trusted-read-domains.json'
    domain_path.write_text(json.dumps(domains) + '\n')
    domain_path.chmod(0o644)
    # Remove obsolete runtime state only; never delete private settings/history.
    for obsolete in ('profile',):
        (runtime / obsolete).unlink(missing_ok=True)
    canary = runtime / 'worker-deny-canary'
    canary.write_text('Non-secret isolation check.\n')
    canary.chmod(0o644)
    worker_runtime = runtime.with_name(runtime.name + '-worker')
    managed_directory(worker_runtime, 1002, 1000, 0o750)
    for name in ('worker.sock', 'status.json'):
        (worker_runtime / name).unlink(missing_ok=True)
    managed_directory(Path('/tmp/agy-worker'), 1002, 1000, 0o700)
    private = runtime.with_name(runtime.name + '-files')
    managed_directory(private, 1001, 1000, 0o700)
    key = secrets.token_hex(32)
    for name, value in [('key', key), ('proxy-key.conf', 'proxy_set_header X-Antigravity-File-Key "' + key + '";\n')]:
        target = private / name
        # Files are created by root at startup, before any service is launched.
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'w') as handle:
            handle.write(value)
        os.chown(target, 1001, 1000, follow_symlinks=False)
        target.chmod(0o600)


if __name__ == '__main__':
    prepare()
