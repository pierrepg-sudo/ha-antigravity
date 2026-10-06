"""Offline, recoverable local history removal. Never touches workspace files."""
import base64
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import uuid

BASE = Path('/data/home/.gemini/antigravity-cli')
UUID = re.compile(r'[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\Z')

class HistoryError(Exception):
    pass


def plain(path):
    if path.is_symlink():
        raise HistoryError('Linked history paths are not supported.')
    return path


@contextmanager
def connect(write=False):
    plain(BASE); plain(BASE / 'conversations')
    path = plain(BASE / 'conversation_summaries.db')
    if not path.is_file():
        raise HistoryError('Conversation index not found at the expected CLI location.')
    connection = sqlite3.connect(path.as_uri() + ('?mode=rw' if write else '?mode=ro'), uri=True, timeout=3)
    connection.row_factory = sqlite3.Row
    columns = {r[1] for r in connection.execute('PRAGMA table_info(conversation_summaries)')}
    if not {'conversation_id', 'title', 'step_count', 'last_modified_time', 'parent_conversation_id', 'not_fully_idle'} <= columns:
        connection.close()
        raise HistoryError('Unrecognized conversation schema; no changes made.')
    try:
        yield connection
    finally:
        connection.close()


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


@contextmanager
def offline():
    plain(BASE)
    BASE.mkdir(parents=True, exist_ok=True)
    fd = os.open(BASE / 'history.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise HistoryError('Exit the CLI with /exit first, then retry here. Restart the add-on when finished.')
        if cli_running():
            raise HistoryError('The CLI or its language server is still running. Exit it before deleting or restoring history.')
        yield
    finally:
        os.close(fd)


def sync_dir(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try: os.fsync(fd)
    finally: os.close(fd)


def entries():
    root = plain(BASE / 'history-trash')
    if not root.exists():
        return []
    result = []
    for folder in root.iterdir():
        if not UUID.fullmatch(folder.name) or folder.is_symlink() or not folder.is_dir():
            continue
        record = plain(folder / 'record.json')
        if not record.exists():
            continue  # Empty directory left before an atomic record write.
        data = json.loads(record.read_text())
        if not UUID.fullmatch(data.get('id', '')):
            raise HistoryError('Invalid recovery record; history changes are blocked.')
        result.append((folder, data))
    return result


def reconcile(connection):
    # SQLite is the commit marker. A crash before COMMIT restores moved files;
    # a crash after COMMIT keeps them archived. The same rule covers Undo.
    for folder, data in entries():
        exists = connection.execute('SELECT 1 FROM conversation_summaries WHERE conversation_id=?', (data['id'],)).fetchone()
        for suffix in ('.db', '.db-wal', '.db-shm', '.db-journal'):
            active = plain(BASE / 'conversations' / (data['id'] + suffix))
            saved = plain(folder / ('conversation' + suffix))
            source, target = (saved, active) if exists else (active, saved)
            if source.exists():
                if target.exists():
                    raise HistoryError('Conflicting history files; automatic recovery stopped without overwriting either copy.')
                os.rename(source, target)
        sync_dir(folder)
    sync_dir(BASE / 'conversations')


def recover():
    with offline():
        if not any(any((folder / ('conversation' + suffix)).exists() for suffix in ('.db', '.db-wal', '.db-shm', '.db-journal')) for folder, _ in entries()):
            return
        if not (BASE / 'conversation_summaries.db').exists():
            return
        with connect() as db:
            reconcile(db)


def listing():
    with connect() as db:
        rows = db.execute('SELECT conversation_id, title, step_count, last_modified_time, parent_conversation_id, not_fully_idle FROM conversation_summaries ORDER BY last_modified_time DESC LIMIT 2000').fetchall()
        present = {row[0] for row in db.execute('SELECT conversation_id FROM conversation_summaries')}
        parents = {row[0] for row in db.execute('SELECT DISTINCT parent_conversation_id FROM conversation_summaries WHERE parent_conversation_id IS NOT NULL')}
    result = []
    for row in rows:
        item = dict(row); cid = item.pop('conversation_id')
        local = bool(UUID.fullmatch(cid or '')) and (BASE / 'conversations' / (cid + '.db')).is_file()
        reason = ('Only locally stored conversations can be removed.' if not local else
                  'Remove child conversations first.' if cid in parents else
                  'Subagent or nested conversations must be managed in the CLI.' if item['parent_conversation_id'] else
                  'This conversation is marked active; finish it in the CLI first.' if item['not_fully_idle'] else '')
        result.append({'id':cid, 'title':item['title'] or 'Untitled conversation', 'steps':item['step_count'], 'modified':str(item['last_modified_time'] or ''), 'blocked':reason})
    trash = [{'backup':folder.name, 'title':data['title'], 'id':data['id']} for folder,data in entries()
             if data['id'] not in present and (folder / 'conversation.db').is_file()]
    return {'items':result, 'trash':trash, 'running':cli_running(), 'limit':2000}


def pack(value):
    return {'blob':base64.b64encode(value).decode()} if isinstance(value, bytes) else value


def unpack(value):
    return base64.b64decode(value['blob'], validate=True) if isinstance(value, dict) else value


def change(payload):
    if payload.get('confirm') is not True:
        raise HistoryError('Confirm the selected conversation first.')
    action = payload.get('action')
    key = payload.get('id' if action == 'delete' else 'backup', '')
    if action not in {'delete','restore'} or not isinstance(key,str) or not UUID.fullmatch(key):
        raise HistoryError('Invalid history action.')
    with offline(), connect(True) as db:
        reconcile(db)
        db.execute('BEGIN IMMEDIATE')
        try:
            if action == 'delete':
                row = db.execute('SELECT * FROM conversation_summaries WHERE conversation_id=?', (key,)).fetchone()
                if row is None:
                    raise HistoryError('Conversation no longer exists. Refresh the list.')
                if row['parent_conversation_id'] or row['not_fully_idle']:
                    raise HistoryError('Active or nested conversations must be managed in the CLI.')
                if db.execute('SELECT 1 FROM conversation_summaries WHERE parent_conversation_id=?', (key,)).fetchone():
                    raise HistoryError('This conversation has child sessions; use the CLI to delete it.')
                source = plain(BASE / 'conversations' / (key + '.db'))
                if not source.is_file():
                    raise HistoryError('Local conversation database not found.')
                root = plain(BASE / 'history-trash'); root.mkdir(mode=0o700, exist_ok=True)
                folder = root / str(uuid.uuid4()); folder.mkdir(mode=0o700)
                data = {'id':key, 'title':row['title'] or 'Untitled conversation', 'row':{k:pack(row[k]) for k in row.keys()}}
                record = folder / 'record.tmp'
                with record.open('x') as handle:
                    json.dump(data, handle); handle.flush(); os.fsync(handle.fileno())
                os.replace(record, folder / 'record.json')
                sync_dir(folder); sync_dir(root)
                for suffix in ('.db', '.db-wal', '.db-shm', '.db-journal'):
                    source = plain(BASE / 'conversations' / (key + suffix))
                    if source.exists(): os.rename(source, folder / ('conversation' + suffix))
                sync_dir(folder); sync_dir(BASE / 'conversations')
                db.execute('DELETE FROM conversation_summaries WHERE conversation_id=?', (key,))
            else:
                found = [(folder,data) for folder,data in entries() if folder.name == key]
                if len(found) != 1:
                    raise HistoryError('Recovery backup not found.')
                folder,data = found[0]
                if db.execute('SELECT 1 FROM conversation_summaries WHERE conversation_id=?', (data['id'],)).fetchone():
                    raise HistoryError('Conversation already exists; nothing was overwritten.')
                if not (folder / 'conversation.db').is_file():
                    raise HistoryError('Recovery database is missing.')
                columns = list(data['row'])
                known = {row[1] for row in db.execute('PRAGMA table_info(conversation_summaries)')}
                if set(columns) != known:
                    raise HistoryError('The CLI schema changed; automatic restore is unavailable.')
                quoted = ','.join('"'+c.replace('"','""')+'"' for c in columns)
                db.execute('INSERT INTO conversation_summaries ('+quoted+') VALUES ('+','.join('?' for c in columns)+')', [unpack(data['row'][c]) for c in columns])
                # Commit first. Reconcile moves files back; startup retries if interrupted.
            db.commit()
        except BaseException:
            db.rollback()
            reconcile(db)
            raise
        reconcile(db)
    return {'ok':True}


if __name__ == '__main__':
    try:
        recover()
    except (HistoryError, OSError, sqlite3.Error, ValueError) as error:
        print('History recovery could not finish. CLI startup stopped to preserve data: ' + str(error), file=sys.stderr)
        sys.exit(1)
