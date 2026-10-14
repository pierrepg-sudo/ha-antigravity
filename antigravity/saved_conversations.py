"""Read the CLI's saved-history index without changing its databases or files."""
from contextlib import closing
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import native_connection as native

ROOT = Path('/data/home/.gemini/antigravity-cli')
UUID = re.compile(r'[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\Z')
MAX_ITEMS = 10000


def fingerprint(path):
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
        raise native.NativeError('Saved history contains an unsupported file. No deletion was attempted.')
    return [info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns]


def timestamp(value):
    if not value:
        return ''
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')



def wire_fields(data):
    """Bounded protobuf wire reader for CLI 1.3.4 summary archive metadata."""
    if not isinstance(data, bytes) or len(data) > 1024 * 1024:
        raise ValueError('Unsupported summary')
    offset = 0
    def varint():
        nonlocal offset
        value = 0
        for shift in range(0, 70, 7):
            if offset >= len(data):
                raise ValueError('Truncated summary')
            byte = data[offset]; offset += 1
            value |= (byte & 127) << shift
            if byte < 128:
                return value
        raise ValueError('Invalid varint')
    while offset < len(data):
        tag = varint(); number, kind = tag >> 3, tag & 7
        if not number:
            raise ValueError('Invalid field')
        if kind == 0:
            value = varint()
        elif kind in (1, 2, 5):
            length = varint() if kind == 2 else (8 if kind == 1 else 4)
            if length > len(data) - offset:
                raise ValueError('Truncated field')
            value = data[offset:offset + length]; offset += length
        else:
            raise ValueError('Unsupported field')
        yield number, kind, value


def archived(raw):
    if not raw:
        return None
    try:
        state = False
        # CascadeTrajectorySummary.annotations = 15;
        # jetski ConversationAnnotations.archived = 4 (not product API field 3).
        for number, kind, value in wire_fields(raw):
            if number == 15:
                if kind != 2:
                    return None
                for field, wire, flag in wire_fields(value):
                    if field == 4:
                        if wire != 0 or flag not in (0, 1):
                            return None
                        state = bool(flag)
        return state
    except ValueError:
        return None


def project_names():
    directory = ROOT / 'projects'
    if directory.is_symlink():
        return {}
    names = {}
    if not directory.exists():
        return names
    for index, path in enumerate(directory.iterdir()):
        if index >= MAX_ITEMS:
            break
        if path.suffix != '.json':
            continue
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
            with os.fdopen(fd, 'rb') as handle:
                info = os.fstat(handle.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
                    continue
                content = handle.read(1024 * 1024 + 1)
            if len(content) > 1024 * 1024:
                continue
            project = json.loads(content)
            if isinstance(project, dict) and isinstance(project.get('name'), str):
                names[path.stem] = project['name']
                if isinstance(project.get('id'), str):
                    names[project['id']] = project['name']
        except (OSError, ValueError):
            continue
    return names


def read():
    """Match the picker's .db/.pb files; stale summary rows cannot resurrect deletes."""
    try:
        directory = ROOT / 'conversations'
        if directory.is_symlink() or ROOT.is_symlink():
            raise native.NativeError('Saved history must use the CLI data directory.')
        files = {}
        if directory.exists():
            for path in directory.iterdir():
                if path.suffix not in {'.db', '.pb'} or not UUID.fullmatch(path.stem):
                    continue
                parts = files.setdefault(path.stem, {})
                for candidate in (path, Path(str(path) + '-wal')):
                    mark = fingerprint(candidate)
                    if mark is not None:
                        parts[candidate.name] = mark
                if len(files) > MAX_ITEMS:
                    raise native.NativeError('Saved history exceeds 10,000 conversations. No partial list was returned.')
        db = ROOT / 'conversation_summaries.db'
        records = {}
        if db.exists() or db.is_symlink():
            before = fingerprint(db)
            for suffix in ('-wal', '-shm'):
                fingerprint(Path(str(db) + suffix))
            with closing(sqlite3.connect(db.as_uri() + '?mode=ro', uri=True, timeout=2)) as connection:
                connection.execute('PRAGMA query_only=ON')
                connection.execute('PRAGMA trusted_schema=OFF')
                connection.row_factory = sqlite3.Row
                columns = {r[1] for r in connection.execute('PRAGMA table_info(conversation_summaries)')}
                optional = ', project_id' if 'project_id' in columns else ''
                if 'raw_summary' in columns:
                    optional += ', CASE WHEN length(raw_summary) <= 1048576 THEN raw_summary END AS raw_summary'
                rows = connection.execute('SELECT conversation_id, title, step_count, last_modified_time, '
                    'status, not_fully_idle, parent_conversation_id' + optional + ' FROM conversation_summaries LIMIT ?',
                    (MAX_ITEMS + 1,)).fetchall()
                if len(rows) > MAX_ITEMS:
                    raise native.NativeError('Saved history index exceeds 10,000 entries.')
                records = {row['conversation_id']: dict(row) for row in rows}
            if fingerprint(db)[:2] != before[:2]:
                raise native.NativeError('Saved history changed during refresh. Refresh again.')
        names = project_names()
        result = {}
        for cid, marks in files.items():
            row = records.get(cid, {})
            if row.get('parent_conversation_id'):
                continue
            status = row.get('status') or 'Unknown'
            if row.get('not_fully_idle') not in (0, False):
                status = 'Unknown' if not row else 'CASCADE_RUN_STATUS_RUNNING'
            result[cid] = {'summary': row.get('title') or 'Untitled saved conversation',
                'stepCount': row.get('step_count', 0), 'lastModifiedTime': timestamp(row.get('last_modified_time')),
                'status': status, '_saved': marks,
                'projectId': row.get('project_id') or '',
                'projectName': names.get(row.get('project_id'), ''),
                'archived': archived(row.get('raw_summary'))}
        return result
    except (OSError, sqlite3.Error, TypeError, ValueError):
        raise native.NativeError('The CLI saved-history index could not be read. No deletion was attempted.') from None


def exists(cid):
    # Also check hidden/subagent entries; successful deletion must remove backing files.
    return any(os.path.lexists(ROOT / 'conversations' / (cid + suffix)) for suffix in ('.db', '.pb'))
