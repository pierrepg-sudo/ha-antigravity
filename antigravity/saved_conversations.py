"""Read the CLI's saved-history index without changing its databases or files."""
from contextlib import closing
from datetime import datetime, timezone
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
                rows = connection.execute('SELECT conversation_id, title, step_count, last_modified_time, '
                    'status, not_fully_idle, parent_conversation_id FROM conversation_summaries LIMIT ?',
                    (MAX_ITEMS + 1,)).fetchall()
                if len(rows) > MAX_ITEMS:
                    raise native.NativeError('Saved history index exceeds 10,000 entries.')
                records = {row['conversation_id']: dict(row) for row in rows}
            if fingerprint(db)[:2] != before[:2]:
                raise native.NativeError('Saved history changed during refresh. Refresh again.')
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
                'status': status, '_saved': marks}
        return result
    except (OSError, sqlite3.Error, TypeError, ValueError):
        raise native.NativeError('The CLI saved-history index could not be read. No deletion was attempted.') from None


def exists(cid):
    # Also check hidden/subagent entries; successful deletion must remove backing files.
    return any(os.path.lexists(ROOT / 'conversations' / (cid + suffix)) for suffix in ('.db', '.pb'))
