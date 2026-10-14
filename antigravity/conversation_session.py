"""Validated requests to the terminal's private session launcher."""
import json
import socket
import native_connection as native
import saved_conversations as saved
import conversation_history as history


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
    elif action == 'open' and set(payload) == {'action', 'id', 'confirm'}:
        cid = payload['id']
        if not isinstance(cid, str) or not history.UUID.fullmatch(cid) or cid not in history.collect(connection):
            raise native.NativeError('The selected conversation is no longer available.')
        args = ['--remote-control', '--conversation=' + cid]
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
        return args
    project = payload['projectId'] or 'outside-of-project'
    result = native.rpc(connection, native.START, {
        'source': 'CORTEX_TRAJECTORY_SOURCE_CLI',
        'projectEnvConfig': {'projectId': project, 'defaultProjectEnvironment': {}}})
    cid = result.get('cascadeId')
    if not isinstance(cid, str) or not history.UUID.fullmatch(cid):
        raise native.NativeError('Conversation creation could not be verified. Refresh before trying again.')
    summary = native.summaries(connection).get(cid, {})
    if summary.get('trajectoryMetadata', {}).get('projectId') != project:
        raise native.NativeError('The new conversation project could not be verified. Check history before retrying.')
    return ['--remote-control', '--conversation=' + cid]
