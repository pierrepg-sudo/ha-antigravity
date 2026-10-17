"""Workspace-only file operations; never follows symlinks or overwrites files."""
import base64
import os
import secrets
import stat
from contextlib import contextmanager
from contextvars import ContextVar

ROOT = '/data/workspace/outputs'
ACTIVE_ROOT = ContextVar('file_root', default=None)
INPUT_MODE = ContextVar('input_mode', default=False)
UPLOAD_LIMIT = 500 * 1024 * 1024
DOWNLOAD_LIMIT = 500 * 1024 * 1024


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
    fd = os.open(ACTIVE_ROOT.get() or ROOT, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
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
                raise ValueError('Download limit is 500 MiB per file.')
            data = source.read(limit + 1)
            if len(data) > limit and not preview:
                raise ValueError('Download limit is 500 MiB per file.')
            if preview:
                shown = data[:limit]
                if b'\0' in shown:
                    raise ValueError('Binary file: use Download.')
                return {'text': shown.decode('utf-8', errors='replace'), 'truncated': len(data) > limit}
            return data, names[-1]


def upload_stream(path, name, source, length):
    if not isinstance(name, str) or not name or len(name.encode()) > 240 or len(parts(name)) != 1:
        raise ValueError('Use a single filename.')
    if not 0 <= length <= UPLOAD_LIMIT:
        raise FileOperationError('Upload limit is 500 MiB per file.')
    with directory(path) as fd:
        temp = '.upload-' + secrets.token_hex(16)
        handle = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o640 if INPUT_MODE.get() else 0o660, dir_fd=fd)
        try:
            with os.fdopen(handle, 'wb') as target:
                remaining = length
                while remaining:
                    chunk = source.read(min(64 * 1024, remaining))
                    if not chunk:
                        raise FileOperationError('Upload interrupted. No destination file was created.')
                    target.write(chunk)
                    remaining -= len(chunk)
            os.link(temp, name, src_dir_fd=fd, dst_dir_fd=fd, follow_symlinks=False)
        finally:
            os.unlink(temp, dir_fd=fd)
    return {'ok': True}


def change(payload, expected_identity=None):
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
            if expected_identity is not None and (info.st_dev, info.st_ino) != expected_identity:
                raise FileOperationError('The selected folder was replaced. The replacement was not deleted.')
            if stat.S_ISDIR(info.st_mode):
                if payload.get('kind') != 'folder':
                    raise ValueError('Folder deletion requires explicit folder confirmation.')
                import shutil
                if not shutil.rmtree.avoids_symlink_attacks:
                    raise FileOperationError('Safe folder deletion is unavailable on this platform.')
                try:
                    shutil.rmtree(name, dir_fd=fd)
                except OSError:
                    raise FileOperationError('Folder deletion did not finish. Some contents may have been removed. Refresh and check permissions or active writers before retrying.') from None
            elif stat.S_ISREG(info.st_mode):
                if payload.get('kind', 'file') != 'file':
                    raise ValueError('The selected item changed. Refresh and try again.')
                os.unlink(name, dir_fd=fd)
            else:
                raise ValueError('Only regular files and folders can be deleted.')
        elif action == 'rename':
            target = payload.get('newName')
            if not isinstance(target, str) or not target or len(target.encode()) > 240 or len(parts(target)) != 1:
                raise ValueError('Use a single filename or folder name.')
            info = os.stat(name, dir_fd=fd, follow_symlinks=False)
            if not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)):
                raise ValueError('Only regular files and folders can be renamed.')
            rename_new(fd, name, fd, target)
            name = target
        elif action == 'mkdir':
            os.mkdir(name, 0o2750 if INPUT_MODE.get() else 0o2770, dir_fd=fd)
        elif action == 'upload':
            encoded = payload.get('data')
            if not isinstance(encoded, str):
                raise ValueError('Invalid upload.')
            data = base64.b64decode(encoded, validate=True)
            if len(data) > UPLOAD_LIMIT:
                raise ValueError('Upload limit is 500 MiB per file.')
            temp = '.upload-' + secrets.token_hex(16)
            handle = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o640 if INPUT_MODE.get() else 0o660, dir_fd=fd)
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


# Bound recursive work on the HA host. ZIPs are spooled to disk after 8 MiB.
TREE_LIMIT = 500 * 1024 * 1024
ENTRY_LIMIT = 10000
DEPTH_LIMIT = 64


class FileOperationError(ValueError):
    """Fixed diagnostics suitable for display in the file manager."""


class Budget:
    def __init__(self):
        self.bytes = 0
        self.entries = 0

    def entry(self, depth):
        self.entries += 1
        if self.entries > ENTRY_LIMIT or depth > DEPTH_LIMIT:
            raise FileOperationError('Folder limit: 10,000 entries and 64 levels.')

    def consume(self, size):
        self.bytes += size
        if self.bytes > TREE_LIMIT:
            raise FileOperationError('Folder download/copy limit is 500 MiB of file contents.')


def identity(info):
    return info.st_dev, info.st_ino


def snapshot(info):
    return identity(info), info.st_size, info.st_mtime_ns, info.st_ctime_ns


def open_regular(parent, name):
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
    if not stat.S_ISREG(os.fstat(fd).st_mode):
        os.close(fd)
        raise FileOperationError('Links and special files cannot be copied or archived.')
    return os.fdopen(fd, 'rb')


def transfer_bytes(source, target, budget):
    before = os.fstat(source.fileno())
    while True:
        data = source.read(64 * 1024)
        if not data:
            break
        budget.consume(len(data))
        target.write(data)
    if snapshot(before) != snapshot(os.fstat(source.fileno())):
        raise FileOperationError('A source file changed during the operation. Try again when it is idle.')


def walk_tree(fd, prefix, budget, folder, file, depth=0):
    before = os.fstat(fd)
    budget.entry(depth)
    folder(prefix)
    for name in sorted(os.listdir(fd)):
        parts(name)  # Reject names unsafe for portable archive paths.
        path = prefix + '/' + name
        info = os.stat(name, dir_fd=fd, follow_symlinks=False)
        if stat.S_ISDIR(info.st_mode):
            child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            try:
                walk_tree(child, path, budget, folder, file, depth+1)
            finally:
                os.close(child)
        elif stat.S_ISREG(info.st_mode):
            budget.entry(depth+1)
            with open_regular(fd, name) as source:
                file(path, source)
        else:
            raise FileOperationError('Folder contains a link or special file. Nothing was copied or downloaded.')
    if snapshot(before) != snapshot(os.fstat(fd)):
        raise FileOperationError('A source folder changed during the operation. Try again when it is idle.')


def folder_zip(path):
    import tempfile
    import zipfile
    names = parts(path)
    label = names[-1] if names else os.path.basename(ACTIVE_ROOT.get() or ROOT)
    archive = tempfile.SpooledTemporaryFile(max_size=8*1024*1024)
    try:
        budget = Budget()
        with directory(path) as source, zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=1) as zip_file:
            def folder(name):
                zip_file.writestr(name+'/', b'')

            def file(name, stream):
                with zip_file.open(name, 'w') as target:
                    transfer_bytes(stream, target, budget)
            walk_tree(source, label, budget, folder, file)
        archive.seek(0)
        return archive, label+'.zip'
    except BaseException:
        archive.close()
        raise


def rename_new(source_fd, source, target_fd, target):
    """Linux atomic rename with RENAME_NOREPLACE: never race an existence check."""
    import ctypes
    libc = ctypes.CDLL(None, use_errno=True)
    rename = libc.renameat2
    rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    rename.restype = ctypes.c_int
    if rename(source_fd, os.fsencode(source), target_fd, os.fsencode(target), 1):
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error))


def reject_descendant(source_info, target_fd):
    """Compare inode ancestry, including aliased roots (legacy contains outputs)."""
    current = os.dup(target_fd)
    try:
        while True:
            info = os.fstat(current)
            if identity(info) == identity(source_info):
                raise FileOperationError('Choose a destination outside the source folder.')
            parent = os.open('..', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=current)
            if identity(os.fstat(parent)) == identity(info):
                os.close(parent)
                break
            os.close(current)
            current = parent
    finally:
        os.close(current)


def transfer(payload, source_root):
    """Copy between approved roots, or atomically move inside one writable area."""
    import shutil
    names = parts(payload.get('source'))
    name = payload.get('name')
    action = payload.get('action')
    if not names or not isinstance(name, str) or len(parts(name)) != 1 or len(name.encode()) > 240:
        raise FileOperationError('Select an item and use a single destination name.')
    if action not in ('copy', 'move'):
        raise FileOperationError('Unknown transfer operation.')
    with directory(payload.get('path', '')) as target:
        root_token = ACTIVE_ROOT.set(source_root)
        try:
            with directory('/'.join(names[:-1])) as parent:
                info = os.stat(names[-1], dir_fd=parent, follow_symlinks=False)
                is_folder = stat.S_ISDIR(info.st_mode)
                if not is_folder and not stat.S_ISREG(info.st_mode):
                    raise FileOperationError('Only files and folders can be copied or moved.')
                if is_folder:
                    reject_descendant(info, target)
                if action == 'move':
                    rename_new(parent, names[-1], target, name)
                else:
                    # Build privately, then publish in one rename. Failed copies never
                    # leave a partial destination or modify/delete their source.
                    temp = '.copy-' + secrets.token_hex(16)
                    os.mkdir(temp, 0o700, dir_fd=target)
                    stage = os.open(temp, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=target)
                    try:
                        budget = Budget()
                        def folder(path):
                            os.mkdir(path, 0o2750 if INPUT_MODE.get() else 0o2770, dir_fd=stage)
                        def file(path, stream):
                            out = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                                          (0o640 if INPUT_MODE.get() else 0o660) | (os.fstat(stream.fileno()).st_mode & 0o110), dir_fd=stage)
                            with os.fdopen(out, 'wb') as dest:
                                transfer_bytes(stream, dest, budget)
                        if is_folder:
                            child = os.open(names[-1], os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
                            try:
                                walk_tree(child, 'item', budget, folder, file)
                            finally:
                                os.close(child)
                        else:
                            with open_regular(parent, names[-1]) as stream:
                                file('item', stream)
                        rename_new(stage, 'item', target, name)
                    finally:
                        os.close(stage)
                        shutil.rmtree(temp, dir_fd=target)
        finally:
            ACTIVE_ROOT.reset(root_token)
    return {'ok': True, 'path': '/'.join(filter(None, [payload.get('path', ''), name]))}


@contextmanager
def download_file(path):
    """Keep one no-follow file descriptor open while HTTP streams bounded chunks."""
    names = parts(path)
    if not names:
        raise ValueError('Select a file.')
    with directory('/'.join(names[:-1])) as parent:
        with open_regular(parent, names[-1]) as source:
            size = os.fstat(source.fileno()).st_size
            if size > DOWNLOAD_LIMIT:
                raise FileOperationError('Download limit is 500 MiB per file.')
            yield source, names[-1], size
