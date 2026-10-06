"""Read-only conversation listing for the native CLI controls."""
from contextlib import contextmanager
import os
from pathlib import Path
import sqlite3

BASE = Path('/data/home/.gemini/antigravity-cli')

class HistoryError(Exception):
    pass


@contextmanager
def connect():
    path = BASE / 'conversation_summaries.db'
    if BASE.is_symlink() or path.is_symlink() or not path.is_file():
        raise HistoryError('Conversation index is missing or linked.')
    db = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=3)
    try:
        db.row_factory = sqlite3.Row
        columns = {row[1] for row in db.execute('PRAGMA table_info(conversation_summaries)')}
        if not {'conversation_id', 'title', 'step_count', 'last_modified_time'} <= columns:
            raise HistoryError('Unrecognized conversation index schema.')
        yield db
    finally:
        db.close()


def cli_running():
    for proc in Path('/proc').iterdir():
        if not proc.name.isdigit():
            continue
        try:
            if proc.stat().st_uid != os.getuid():
                continue
            name = Path(os.readlink(proc / 'exe')).name.removesuffix(' (deleted)')
            if name in {'agy', 'antigravity'} or name.startswith('language_server'):
                return True
        except FileNotFoundError:
            continue
        except PermissionError:
            # Fail closed when a same-user process cannot be inspected.
            return True
    return False



def listing():
    with connect() as db:
        rows = db.execute('SELECT conversation_id, title, step_count, last_modified_time FROM conversation_summaries ORDER BY last_modified_time DESC LIMIT 2000').fetchall()
    items = [{'id':row['conversation_id'], 'title':row['title'] or 'Untitled conversation',
              'steps':row['step_count'], 'modified':str(row['last_modified_time'] or '')}
             for row in rows if isinstance(row['conversation_id'], str) and row['conversation_id']]
    return {'items':items, 'running':cli_running(), 'limit':2000}
