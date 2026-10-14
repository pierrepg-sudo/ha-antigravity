"""Native listing and direct deletion. No database mutation or terminal automation."""
import hashlib
import json
import re
import threading
import native_connection as native
import saved_conversations as saved

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
    project_id = summary.get('projectId') or ''
    project_name = summary.get('projectName') or ''
    archive = summary.get('archived')
    if 'archived' in annotations:
        archive = annotations['archived'] if isinstance(annotations['archived'], bool) else None
    if project_id == 'outside-of-project':
        project_id = ''
    project_name = project_name or ('Project ' + project_id if project_id else 'No project')
    revision = hashlib.sha256(json.dumps([connection['pid'],connection['started'],connection['port'],cid,title,status,modified,steps,summary.get('_saved'),project_id,project_name,archive],sort_keys=True).encode()).hexdigest()
    blocked = ('Invalid conversation identifier.' if not UUID.fullmatch(cid) else
               'This conversation is running or its idle state is unrecognized.' if status not in IDLE else '')
    return {'id':cid, 'title':title, 'steps':steps, 'modified':modified, 'status':status, 'revision':revision, 'blocked':blocked, 'projectId':project_id, 'projectName':project_name, 'archived':archive}


def collect(connection):
    rows = saved.read()
    for cid, live in native.summaries(connection).items():
        if cid in rows:
            if isinstance(live.get('annotations'), dict):
                rows[cid]['archived'] = live['annotations'].get('archived', False)
            # The CLI index supplies disk history; a live busy state always wins.
            if live.get('status') not in IDLE:
                rows[cid]['status'] = live.get('status', 'Unknown')
        elif live.get('stepCount', 0) or live.get('summary') or (live.get('annotations') or {}).get('title'):
            rows[cid] = live
    return rows


def listing():
    with LOCK:
        connection = native.load()
        rows = collect(connection)
        items = [item(connection,cid,summary) for cid,summary in rows.items()]
        items.sort(key=lambda row:str(row['modified']), reverse=True)
        return {'items':items, 'projects':[{'id':key,'name':name} for key,name in sorted(saved.project_names().items(), key=lambda pair:pair[1].casefold()) if key != 'outside-of-project']}



def prepare(payload):
    """Load saved history and return a fresh confirmation; never delete."""
    cid = payload.get('id')
    if set(payload) != {'id'} or not isinstance(cid, str) or not UUID.fullmatch(cid):
        raise HistoryError('Invalid conversation selection.')
    with LOCK:
        connection = native.load()
        rows = collect(connection)
        if cid not in rows:
            raise HistoryError('The selected conversation is no longer listed.')
        current = item(connection, cid, rows[cid])
        if current['blocked']:
            raise HistoryError(current['blocked'])
        if '_saved' in rows[cid]:
            native.rpc(connection, native.LOAD, {'cascadeId': cid})
            loaded = native.summaries(connection).get(cid)
            if loaded is None or loaded.get('status') not in IDLE:
                raise HistoryError('The saved conversation is not idle. No deletion was attempted.')
        rows = collect(connection)
        if cid not in rows:
            raise HistoryError('The selected conversation is no longer listed.')
        current = item(connection, cid, rows[cid])
        if current['blocked']:
            raise HistoryError(current['blocked'])
        return {'item': current}


def delete(payload):
    if set(payload) != {'id','revision','confirm'} or payload['confirm'] is not True:
        raise HistoryError('Confirm the selected conversation first.')
    cid = payload['id']
    if not isinstance(cid,str) or not UUID.fullmatch(cid) or not isinstance(payload['revision'],str):
        raise HistoryError('Invalid conversation selection.')
    with LOCK:
        connection = native.load()
        rows = collect(connection)
        if cid not in rows:
            raise HistoryError('The selected conversation is no longer listed. Refresh the menu.')
        current = item(connection,cid,rows[cid])
        if current['blocked']:
            raise HistoryError(current['blocked'])
        if current['revision'] != payload['revision']:
            raise HistoryError('The conversation or connection changed. Refresh and confirm the current entry.')
        if '_saved' in rows[cid]:
            native.rpc(connection, native.LOAD, {'cascadeId': cid})
            loaded = native.summaries(connection).get(cid)
            if loaded is None or loaded.get('status') not in IDLE:
                raise HistoryError('The saved conversation is not idle. No deletion was attempted.')
            fresh = collect(connection)
            if cid not in fresh or item(connection, cid, fresh[cid])['revision'] != payload['revision']:
                raise HistoryError('Saved history changed while loading. Refresh and confirm the current entry.')
        native.rpc(connection,native.DELETE,{'cascadeId':cid})
        try:
            remaining = native.summaries(connection)
        except HistoryError:
            raise HistoryError('Delete was sent, but its result could not be verified. Refresh before retrying.') from None
        if cid in remaining or saved.exists(cid):
            raise HistoryError('Delete was sent, but the conversation is still listed. Deletion is not confirmed; refresh before retrying.')
        return {'ok':True, 'deleted':cid}
