"""Project metadata, scoped output folders and confirmed native mutations."""
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import uuid
import fcntl
import threading
import stat
from urllib.parse import urlsplit, unquote
from contextlib import contextmanager
import native_connection as native
import saved_conversations as saved
import workspace_files as files

OUTPUTS = Path('/data/workspace/outputs')
_mutex = threading.RLock()
_local = threading.local()


@contextmanager
def preference_lock():
    # The launcher and HTTP service are different processes.
    with _mutex:
        if getattr(_local, 'held', False):
            yield
            return
        fd = os.open(native.STATE.with_name('ha-preferences.lock'), os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            _local.held = True
            yield
        finally:
            _local.held = False
            os.close(fd)


def state_path():
    return native.STATE.with_name('ha-conversation-preferences.json')


def read_state():
    try:
        with open(state_path(), 'r') as handle:
            value = json.loads(handle.read(1024 * 1024 + 1))
        if not isinstance(value, dict):
            raise ValueError()
        return value
    except FileNotFoundError:
        return {}
    except (OSError, ValueError):
        raise native.NativeError('Conversation preferences could not be read.') from None


def write_state(value):
    path = state_path()
    fd, temp = tempfile.mkstemp(prefix='.preferences-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as handle:
            json.dump(value, handle)
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def valid_name(name):
    if not isinstance(name, str) or not name.strip() or name != name.strip() or len(name.encode()) > 160:
        raise native.NativeError('Use a name of 1–160 bytes without leading or trailing spaces.')
    try:
        if len(files.parts(name)) != 1 or name.startswith('.'):
            raise ValueError()
    except ValueError:
        raise native.NativeError('Names cannot contain path separators, control characters or leading dots.') from None
    return name


def project(connection, pid):
    if not isinstance(pid, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', pid):
        raise native.NativeError('Invalid project identifier.')
    result = native.rpc(connection, 'ReadProject', {'id': pid}).get('project')
    if not isinstance(result, dict) or result.get('id') != pid:
        raise native.NativeError('The project could not be read.')
    return result


def project_paths(p):
    """Display native folder locations without granting Files access outside Outputs."""
    result = []
    resources = p.get('projectResources', {})
    if not isinstance(resources, dict):
        return result
    entries = resources.get('resources', [])
    if not isinstance(entries, list):
        return result
    for resource in entries:
        if not isinstance(resource, dict) or not isinstance(resource.get('folderUri'), str):
            continue
        uri = urlsplit(resource['folderUri'])
        if uri.scheme == 'file' and uri.netloc in ('', 'localhost') and not uri.query and not uri.fragment:
            path = unquote(uri.path)
            if path.startswith('/') and not any(ord(c) < 32 for c in path) and path not in result:
                result.append(path)
    return result


def resource_folder(p):
    """Recognize only a single, real immediate output folder in native metadata."""
    resources = p.get('projectResources', {}).get('resources', [])
    if len(resources) != 1 or not isinstance(resources[0], dict) or not isinstance(resources[0].get('folderUri'), str):
        return None
    uri = urlsplit(resources[0]['folderUri'])
    if uri.scheme != 'file' or uri.netloc not in ('', 'localhost') or uri.query or uri.fragment:
        return None
    path = Path(unquote(uri.path))
    alias = OUTPUTS.parent.parent / 'home/Documents'
    if path.parent == alias and alias.is_symlink() and os.readlink(alias) == str(OUTPUTS):
        path = OUTPUTS / path.name
    if path.parent != OUTPUTS:
        return None
    valid_name(path.name)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode):
        return None
    return path.name


def sync_project_folders(records):
    candidates = {}
    for pid, p in records.items():
        if pid in ('default-cli-project', 'outside-of-project'):
            continue
        try:
            folder = resource_folder(p)
        except (OSError, ValueError, TypeError, AttributeError, native.NativeError):
            continue
        if folder:
            candidates.setdefault(folder, set()).add(pid)
    if not candidates:
        return read_state().get('folders', {})
    with preference_lock():
        state = read_state()
        bindings = state.setdefault('folders', {})
        changed = False
        for folder, ids in candidates.items():
            if len(ids) != 1:
                continue
            pid = next(iter(ids))
            if pid not in bindings and folder not in bindings.values():
                bindings[pid] = folder
                changed = True
        if changed:
            write_state(state)
        return bindings


def projects(connection):
    # The CLI's local files, not a cloud-wide project inventory.
    result = []
    records = saved.project_records()
    bindings = sync_project_folders(records)
    for pid, p in records.items():
        if pid == 'outside-of-project':
            continue
        result.append({'id': pid, 'name': p.get('name', pid), 'archived': p.get('archived', False),
                       'folder': bindings.get(pid, ''), 'paths': project_paths(p)})
    return sorted(result, key=lambda p: p['name'].casefold())


def ensure_folder(connection, pid):
    if not pid or pid == 'outside-of-project':
        return str(OUTPUTS)
    p = project(connection, pid)
    sync_project_folders(saved.project_records())
    state = read_state()
    bindings = state.setdefault('folders', {})
    name = valid_name(bindings.get(pid) or p['name'])
    with files.directory('') as root:
        if pid not in bindings:
            # Never silently adopt an unrelated existing folder or merge projects.
            try:
                os.mkdir(name, 0o2770, dir_fd=root)
            except FileExistsError:
                raise native.NativeError('An output folder with this name already exists. Rename this project to a unique name first.') from None
            bindings[pid] = name
            write_state(state)
        fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root)
        os.close(fd)
    return str(OUTPUTS / name)


def selection(payload, connection):
    import conversation_history as history
    if payload.get('kind') not in ('project', 'conversation') or payload.get('action') not in ('rename', 'archive', 'restore', 'delete', 'reset-model'):
        raise native.NativeError('Invalid management action.')
    if payload['action'] == 'reset-model' and payload['kind'] != 'conversation':
        raise native.NativeError('Model preferences belong to individual conversations.')
    if payload.get('files', 'keep') not in ('keep', 'delete'):
        raise native.NativeError('Choose whether to keep or delete project files.')
    if payload.get('files', 'keep') == 'delete' and (payload['kind'] != 'project' or payload['action'] != 'delete'):
        raise native.NativeError('File deletion is only available when deleting a project.')
    ident = payload.get('id')
    if payload['action'] == 'rename':
        valid_name(payload.get('name'))
    rows = history.collect(connection)
    if payload['kind'] == 'conversation':
        if ident not in rows:
            raise native.NativeError('Conversation no longer listed.')
        ids = [ident]
        obj = None
    else:
        if ident in ('', 'default-cli-project', 'outside-of-project'):
            raise native.NativeError('The built-in CLI and unclassified groups cannot be changed as projects.')
        obj = project(connection, ident)
        ids = [cid for cid, row in rows.items() if row.get('projectId') == ident]
    if len(ids) > 200:
        raise native.NativeError('Manage projects with more than 200 conversations in smaller batches.')
    entries = [history.prepare({'id': cid})['item'] for cid in sorted(ids)]
    folder = read_state().get('folders', {}).get(ident) if obj is not None else None
    identity = None
    if folder and payload['action'] == 'delete' and payload.get('files', 'keep') == 'delete':
        valid_name(folder)
        with files.directory('') as root:
            try:
                info = os.stat(folder, dir_fd=root, follow_symlinks=False)
            except FileNotFoundError:
                raise native.NativeError('The project folder is missing. Choose Keep files to delete only the project.') from None
            if not stat.S_ISDIR(info.st_mode):
                raise native.NativeError('The project folder changed or is a link. Files were not selected for deletion.')
            identity = [info.st_dev, info.st_ino]
    revision = hashlib.sha256(json.dumps([obj, entries, read_state().get('folders', {}), payload.get('files', 'keep'), identity], sort_keys=True).encode()).hexdigest()
    return obj, entries, revision


def prepare(payload):
    import conversation_history as history
    with history.LOCK:
        obj, entries, revision = selection(payload, native.load())
        return {'revision': revision, 'count': len(entries),
                'folder': read_state().get('folders', {}).get(obj['id'], '') if obj else '',
                'projectName': obj.get('name', '') if obj else ''}


def action(payload):
    import conversation_history as history
    with history.LOCK, preference_lock():
        connection = native.load()
        if payload.get('confirm') is not True:
            raise native.NativeError('Confirm this operation first.')
        obj, entries, revision = selection(payload, connection)
        if payload.get('revision') != revision:
            raise native.NativeError('The selection changed. Refresh and confirm again.')
        operation = payload['action']
        completed = 0
        try:
            if operation == 'reset-model':
                import conversation_models
                conversation_models.remember(payload['id'], '')
                return {'ok': True}
            if operation == 'delete':
                cleanup_identity = None
                if obj is not None and payload.get('files', 'keep') == 'delete':
                    selected_folder = read_state().get('folders', {}).get(obj['id'])
                    if selected_folder:
                        with files.directory('') as root:
                            info = os.stat(selected_folder, dir_fd=root, follow_symlinks=False)
                            cleanup_identity = (info.st_dev, info.st_ino)
                for row in entries:
                    history.delete({'id': row['id'], 'revision': row['revision'], 'confirm': True})
                    completed += 1
                if obj is not None:
                    # Do not let DeleteProject unexpectedly delete newly added conversations.
                    if any(row.get('projectId') == obj['id'] for row in history.collect(connection).values()):
                        raise native.NativeError('Project membership changed; the project was not removed.')
                    native.rpc(connection, 'DeleteProject', {'id': obj['id']})
                    if obj['id'] in saved.project_names():
                        raise native.NativeError('Project deletion could not be verified.')
                    state = read_state()
                    folder = state.get('folders', {}).pop(obj['id'], None)
                    for row in entries:
                        state.get('contexts', {}).pop(row['id'], None)
                    write_state(state)
                    if folder and payload.get('files', 'keep') == 'delete':
                        try:
                            files.change({'action': 'delete', 'path': '', 'name': valid_name(folder), 'kind': 'folder', 'confirm': True}, expected_identity=cleanup_identity)
                        except (OSError, ValueError, files.FileOperationError):
                            raise native.NativeError('The project was deleted, but folder cleanup did not finish. Some files may have been removed. Check Outputs before deleting anything else.') from None
                return {'ok': True, 'deleted': completed}
            if obj is None:
                annotations = {'title': payload['name']} if operation == 'rename' else {'archived': operation == 'archive'}
                native.rpc(connection, 'UpdateConversationAnnotations', {'cascadeId': payload['id'], 'annotations': annotations, 'mergeAnnotations': True})
                live = native.summaries(connection).get(payload['id'], {}).get('annotations', {})
                if any(live.get(k, False if k == 'archived' else '') != v for k, v in annotations.items()):
                    raise native.NativeError('The update could not be verified. Refresh before retrying.')
            else:
                state = read_state()
                old = state.get('folders', {}).get(obj['id'])
                renamed = False
                if operation == 'rename':
                    if any(p['id'] != obj['id'] and p['name'].casefold() == payload['name'].casefold() for p in projects(connection)):
                        raise native.NativeError('Another project already uses that name.')
                    if old and old != payload['name']:
                        # Native remote projects keep their folder in projectResources.
                        linked = resource_folder(obj) == old
                        with files.directory('') as root:
                            files.rename_new(root, old, root, payload['name'])
                        renamed = True
                        if linked:
                            obj['projectResources']['resources'][0]['folderUri'] = (OUTPUTS / payload['name']).as_uri()
                    obj['name'] = payload['name']
                else:
                    obj['archived'] = operation == 'archive'
                try:
                    native.rpc(connection, 'UpdateProject', {'project': obj})
                    fresh = project(connection, obj['id'])
                    key = 'name' if operation == 'rename' else 'archived'
                    if fresh.get(key, False) != obj[key]:
                        raise native.NativeError('Project update could not be verified.')
                finally:
                    # Keep the binding accurate even if the native update fails; no file loss.
                    if renamed:
                        state['folders'][obj['id']] = payload['name']
                        for cid, folder in state.get('contexts', {}).items():
                            if folder == str(OUTPUTS / old):
                                state['contexts'][cid] = str(OUTPUTS / payload['name'])
                        write_state(state)
            return {'ok': True}
        except native.NativeError as error:
            if completed:
                raise native.NativeError(f'{completed} conversations deleted before the operation stopped. Refresh before retrying. {error}') from None
            raise
        except OSError:
            raise native.NativeError('Folder operation failed. Nothing was overwritten. Check names and permissions.') from None


def create(payload):
    import conversation_history as history
    with history.LOCK, preference_lock():
        name = valid_name(payload.get('name'))
        connection = native.load()
        if any(p['name'].casefold() == name.casefold() for p in projects(connection)):
            raise native.NativeError('A project with this name already exists.')
        if (OUTPUTS / name).exists() or (OUTPUTS / name).is_symlink():
            raise native.NativeError('An output folder with this name already exists. Choose a unique project name.')
        pid = str(uuid.uuid4())
        native.rpc(connection, 'CreateProject', {'project': {'id': pid, 'name': name, 'projectResources': {}}})
        project(connection, pid)
        try:
            folder = ensure_folder(connection, pid)
        except (OSError, native.NativeError):
            raise native.NativeError('Project created, but its output folder could not be prepared. Refresh and resolve the folder before starting a conversation.') from None
        return {'ok': True, 'id': pid, 'folder': folder}
