"""Validated requests to the terminal's private session launcher."""
import json
import socket
import native_connection as native
import saved_conversations as saved
import conversation_history as history
import conversation_management as management
import conversation_models as models
import os


def socket_path():
    return native.STATE.with_name('ha-session.sock')


def launch_args(payload, connection):
    if not isinstance(payload, dict) or payload.get('confirm') is not True:
        raise native.NativeError('Confirm switching the terminal session first.')
    action = payload.get('action')
    if action == 'new' and set(payload) == {'action', 'projectId', 'confirm'}:
        project = payload['projectId']
        if not isinstance(project, str) or (project and project not in saved.project_names()):
            raise native.NativeError('The selected project is no longer available. Refresh and select it again.')
        args = None  # Created through the native API after the launcher rechecks idle state.
    elif (action == 'open' and set(payload) == {'action', 'id', 'confirm'}) or (action == 'model' and set(payload) == {'action', 'id', 'model', 'confirm'}):
        cid = payload['id']
        if not isinstance(cid, str) or not history.UUID.fullmatch(cid) or cid not in history.collect(connection):
            raise native.NativeError('The selected conversation is no longer available.')
        args = ['--remote-control', '--conversation=' + cid]
        if action == 'model':
            if cid != models.active_id():
                raise native.NativeError('The active conversation changed. Refresh the model selector.')
            if not isinstance(payload['model'], str) or (payload['model'] and payload['model'] not in {m['id'] for m in models.catalog()}):
                raise native.NativeError('Select a currently available model.')
    else:
        raise native.NativeError('Invalid session request.')
    # Check every loaded trajectory, including ones omitted from the history UI.
    if any(row.get('status') not in history.IDLE for row in native.summaries(connection).values()):
        raise native.NativeError('The CLI is working. Wait for it to finish before switching sessions.')
    return args


def switch(payload):
    with history.LOCK:
        connection = native.load()
        launch_args(payload, connection)
        request = dict(payload=payload, pid=connection['pid'], started=connection['started'])
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                client.settimeout(20)
                client.connect(str(socket_path()))
                client.sendall(json.dumps(request).encode() + b'\n')
                response = client.makefile('rb').readline(8193)
            result = json.loads(response)
            if result.get('ok') is not True:
                raise native.NativeError(result.get('error', 'The terminal session could not be switched.'))
            return {'ok': True}
        except (OSError, ValueError):
            raise native.NativeError('The session handoff could not be confirmed. Check Terminal before retrying.') from None


def materialize(payload, connection, args):
    if args is not None:
        cid = payload['id']
        row = history.collect(connection).get(cid, {})
        project = row.get('projectId') or (row.get('trajectoryMetadata') or {}).get('projectId', '')
        return configure_session(payload, connection, args, cid, project)
    project = payload['projectId'] or 'outside-of-project'
    with management.preference_lock():
        management.ensure_folder(connection, project)
    result = native.rpc(connection, native.START, {
        'source': 'CORTEX_TRAJECTORY_SOURCE_CLI',
        'projectEnvConfig': {'projectId': project, 'defaultProjectEnvironment': {}}})
    cid = result.get('cascadeId')
    if not isinstance(cid, str) or not history.UUID.fullmatch(cid):
        raise native.NativeError('Conversation creation could not be verified. Refresh before trying again.')
    summary = native.summaries(connection).get(cid, {})
    if summary.get('trajectoryMetadata', {}).get('projectId') != project:
        raise native.NativeError('The new conversation project could not be verified. Check history before retrying.')
    return configure_session(payload, connection, ['--remote-control', '--conversation=' + cid], cid, project)


def configure_session(payload, connection, args, cid, project):
    with management.preference_lock():
        folder = management.ensure_folder(connection, project)
        state = management.read_state()
        state.setdefault('contexts', {})[cid] = folder
        management.write_state(state)
    model = payload['model'] if payload.get('action') == 'model' else models.preferences().get(cid, '')
    if model:
        if model not in {m['id'] for m in models.catalog()}:
            raise native.NativeError('The saved model is no longer available. Reset its preference before reopening.')
        args = [*args, '--model=' + model]
    return args


def environment(args):
    cid = next((arg.split('=', 1)[1] for arg in args if arg.startswith('--conversation=')), models.active_id())
    folder = management.read_state().get('contexts', {}).get(cid, '/data/workspace/outputs')
    env = dict(os.environ)
    env['HA_PROJECT_OUTPUT'] = folder
    return env
