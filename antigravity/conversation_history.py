"""Native listing and direct deletion. No database mutation or terminal automation."""
import hashlib
import json
import re
import threading
import native_connection as native

LOCK = threading.Lock()
UUID = re.compile(r'[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\Z')
IDLE = {'CASCADE_RUN_STATUS_IDLE', 'CASCADE_RUN_STATUS_DONE', 'CASCADE_RUN_STATUS_COMPLETED',
        'CASCADE_RUN_STATUS_CANCELLED', 'CASCADE_RUN_STATUS_CANCELED', 'CASCADE_RUN_STATUS_FAILED'}
HistoryError = native.NativeError


def item(connection, cid, summary):
    annotations = summary.get('annotations') or {}
    if not isinstance(annotations, dict):
        raise HistoryError('Unsupported native summary format.')
    title = annotations.get('title') or summary.get('summary') or 'Untitled conversation'
    status = summary.get('status', 'Unknown')
    if not isinstance(title,str) or not isinstance(status,str):
        raise HistoryError('Unsupported native summary format.')
    modified = summary.get('lastModifiedTime') or ''
    steps = summary.get('stepCount', 0)
    revision = hashlib.sha256(json.dumps([connection['pid'],connection['started'],connection['port'],cid,title,status,modified,steps],sort_keys=True).encode()).hexdigest()
    blocked = ('Invalid conversation identifier.' if not UUID.fullmatch(cid) else
               'This conversation is running or its idle state is unrecognized.' if status not in IDLE else '')
    return {'id':cid, 'title':title, 'steps':steps, 'modified':modified, 'status':status, 'revision':revision, 'blocked':blocked}


def listing():
    with LOCK:
        connection = native.load()
        rows = native.summaries(connection)
        items = [item(connection,cid,summary) for cid,summary in rows.items()]
        items.sort(key=lambda row:str(row['modified']), reverse=True)
        return {'items':items}


def delete(payload):
    if set(payload) != {'id','revision','confirm'} or payload['confirm'] is not True:
        raise HistoryError('Confirm the selected conversation first.')
    cid = payload['id']
    if not isinstance(cid,str) or not UUID.fullmatch(cid) or not isinstance(payload['revision'],str):
        raise HistoryError('Invalid conversation selection.')
    with LOCK:
        connection = native.load()
        rows = native.summaries(connection)
        if cid not in rows:
            raise HistoryError('The selected conversation is no longer listed. Refresh the menu.')
        current = item(connection,cid,rows[cid])
        if current['blocked']:
            raise HistoryError(current['blocked'])
        if current['revision'] != payload['revision']:
            raise HistoryError('The conversation or connection changed. Refresh and confirm the current entry.')
        native.rpc(connection,native.DELETE,{'cascadeId':cid})
        try:
            remaining = native.summaries(connection)
        except HistoryError:
            raise HistoryError('Delete was sent, but its result could not be verified. Refresh before retrying.') from None
        if cid in remaining:
            raise HistoryError('Delete was sent, but the conversation is still listed. Deletion is not confirmed; refresh before retrying.')
        return {'ok':True, 'deleted':cid}
