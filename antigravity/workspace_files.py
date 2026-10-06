"""Workspace-only file operations; never follows symlinks or overwrites files."""
import base64
import os
import secrets
import stat
from contextlib import contextmanager

ROOT = '/data/workspace'
UPLOAD_LIMIT = 8 * 1024 * 1024
DOWNLOAD_LIMIT = 32 * 1024 * 1024


def parts(path):
    if not isinstance(path, str) or len(path) > 4096 or path.startswith('/') or '\\' in path or '\0' in path:
        raise ValueError('Invalid workspace path.')
    if not path:
        return []
    result = path.split('/')
    if any(x in ('', '.', '..') or any(ord(c) < 32 for c in x) for x in result):
        raise ValueError('Invalid workspace path.')
    return result


@contextmanager
def directory(path):
    names = parts(path)
    fd = os.open(ROOT, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for name in names:
            child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        yield fd
    finally:
        os.close(fd)


def listing(path):
    with directory(path) as fd:
        entries = []
        for name in os.listdir(fd):
            try:
                info = os.stat(name, dir_fd=fd, follow_symlinks=False)
            except FileNotFoundError:
                continue
            kind = 'folder' if stat.S_ISDIR(info.st_mode) else 'file' if stat.S_ISREG(info.st_mode) else 'blocked'
            entries.append({'name': name, 'kind': kind, 'size': info.st_size})
        entries.sort(key=lambda e: (e['kind'] != 'folder', e['name'].lower()))
        return {'path': path, 'entries': entries}


def read_file(path, preview=False):
    names = parts(path)
    if not names:
        raise ValueError('Select a file.')
    with directory('/'.join(names[:-1])) as parent:
        fd = os.open(names[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        with os.fdopen(fd, 'rb') as source:
            info = os.fstat(source.fileno())
            if not stat.S_ISREG(info.st_mode):
                raise ValueError('Only regular files are accessible.')
            limit = 256 * 1024 if preview else DOWNLOAD_LIMIT
            if not preview and info.st_size > limit:
                raise ValueError('Download limit is 32 MiB per file.')
            data = source.read(limit + 1)
            if len(data) > limit and not preview:
                raise ValueError('Download limit is 32 MiB per file.')
            if preview:
                shown = data[:limit]
                if b'\0' in shown:
                    raise ValueError('Binary file: use Download.')
                return {'text': shown.decode('utf-8', errors='replace'), 'truncated': len(data) > limit}
            return data, names[-1]


def change(payload):
    action = payload.get('action')
    path = payload.get('path', '')
    name = payload.get('name')
    if not isinstance(name, str) or not name or len(name.encode()) > 240 or len(parts(name)) != 1:
        raise ValueError('Use a single filename or folder name.')
    with directory(path) as fd:
        if action == 'delete':
            if payload.get('confirm') is not True:
                raise ValueError('Delete requires confirmation.')
            info = os.stat(name, dir_fd=fd, follow_symlinks=False)
            if not stat.S_ISREG(info.st_mode):
                raise ValueError('Only regular files can be deleted.')
            os.unlink(name, dir_fd=fd)
        elif action == 'mkdir':
            os.mkdir(name, 0o700, dir_fd=fd)
        elif action == 'upload':
            encoded = payload.get('data')
            if not isinstance(encoded, str):
                raise ValueError('Invalid upload.')
            data = base64.b64decode(encoded, validate=True)
            if len(data) > UPLOAD_LIMIT:
                raise ValueError('Upload limit is 8 MiB per file.')
            temp = '.upload-' + secrets.token_hex(16)
            handle = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd)
            try:
                with os.fdopen(handle, 'wb') as target:
                    target.write(data)
                # Atomic publication with no overwrite, including existing symlinks.
                os.link(temp, name, src_dir_fd=fd, dst_dir_fd=fd, follow_symlinks=False)
            finally:
                os.unlink(temp, dir_fd=fd)
        else:
            raise ValueError('Unknown file operation.')
    return {'ok': True, 'path': '/'.join([x for x in [path, name] if x])}
