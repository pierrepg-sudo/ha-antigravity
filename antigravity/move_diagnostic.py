"""Opt-in native project-update experiment, restricted to generated test objects."""
import copy
import hashlib
import json
import uuid
import native_connection as native
import conversation_history as history
import conversation_management as management
import conversation_models as models


def save(run):
    state = management.read_state()
    state['moveDiagnostic'] = run
    management.write_state(state)


def process_id(connection):
    return [connection['pid'], connection['started']]


def idle(connection):
    if any(row.get('status') not in history.IDLE for row in native.summaries(connection).values()):
        raise native.NativeError('Wait until all conversations are idle before running this test.')


def snapshot(connection, run):
    cid = run['conversation']
    native.rpc(connection, native.LOAD, {'cascadeId': cid})
    row = native.summaries(connection).get(cid)
    if not isinstance(row, dict):
        raise native.NativeError('The test conversation could not be loaded.')
    records = {key: management.project(connection, run[key]) for key in ('source', 'destination')}
    trajectory = native.rpc(connection, 'GetCascadeTrajectory', {'cascadeId': cid}).get('trajectory', {})
    steps = trajectory.get('steps') if isinstance(trajectory, dict) else None
    return {'conversationId': cid, 'projectId': (row.get('trajectoryMetadata') or {}).get('projectId'),
            'historyDigest': hashlib.sha256(json.dumps(steps, sort_keys=True).encode()).hexdigest() if isinstance(steps, list) and steps else None,
            'steps': row.get('stepCount', 0), 'status': row.get('status'),
            'title': (row.get('annotations') or {}).get('title') or row.get('summary', ''),
            'projectRecords': records}


def report(run):
    """Expose only test identifiers and relevant evidence, never full project settings."""
    result = copy.deepcopy(run)
    if result:
        snapshots = [result.get('before', {})] + [check.get('snapshot', {}) for check in result.get('checks', [])]
        for snap in snapshots:
            if 'projectRecords' in snap:
                snap['projectRecords'] = {key: {field: value.get(field) for field in ('id', 'name', 'projectConversations')}
                                          for key, value in snap['projectRecords'].items()}
    return {'run': result}


def reference_update(source, destination, cid):
    """Use the shape returned by ReadProject; do not guess absent native fields."""
    block = source.get('projectConversations')
    if not isinstance(block, dict):
        raise native.NativeError('ReadProject did not return a conversation list. No project update was attempted.')
    entries = block.get('conversations')
    target = destination.get('projectConversations', {}).get('conversations')
    if isinstance(entries, list) and len(entries) == 1 and isinstance(entries[0], dict) and entries[0].get('conversationId') == cid:
        if target not in (None, []):
            raise native.NativeError('The destination test project is no longer empty.')
        moved, empty = copy.deepcopy(entries), []
    elif isinstance(entries, dict) and len(entries) == 1:
        key, value = next(iter(entries.items()))
        if not isinstance(value, dict) or value.get('conversationId') != cid or target not in (None, {}):
            raise native.NativeError('Unsupported conversation reference format or nonempty destination. No update was attempted.')
        moved, empty = copy.deepcopy(entries), {}
    else:
        raise native.NativeError('The source test project must contain exactly the disposable conversation in a recognized format. No update was attempted.')
    left, right = copy.deepcopy(source), copy.deepcopy(destination)
    left['projectConversations']['conversations'] = empty
    right.setdefault('projectConversations', {})['conversations'] = moved
    return left, right


def action(payload):
    if set(payload) != {'action', 'confirm'} or payload.get('confirm') is not True or payload['action'] not in ('setup', 'attempt', 'check', 'report'):
        raise native.NativeError('Invalid diagnostic request.')
    with history.LOCK, management.preference_lock():
        run = management.read_state().get('moveDiagnostic')
        if payload['action'] == 'report':
            return report(run)
        connection = native.load()
        idle(connection)
        if payload['action'] == 'setup':
            if run:
                raise native.NativeError('A diagnostic already exists. Use Check or View results; setup is never repeated automatically.')
            suffix = uuid.uuid4().hex[:10]
            run = {'phase': 'creating', 'source': str(uuid.uuid4()), 'destination': str(uuid.uuid4()),
                   'sourceName': 'Move test A ' + suffix, 'destinationName': 'Move test B ' + suffix,
                   'setupProcess': process_id(connection), 'checks': []}
            save(run)  # Persist before each mutation so uncertain responses cannot trigger duplicates.
            try:
                for key in ('source', 'destination'):
                    native.rpc(connection, 'CreateProject', {'project': {'id': run[key], 'name': run[key + 'Name'], 'projectResources': {}}})
                    management.project(connection, run[key])
                    management.ensure_folder(connection, run[key])
                result = native.rpc(connection, native.START, {'source': 'CORTEX_TRAJECTORY_SOURCE_CLI',
                    'projectEnvConfig': {'projectId': run['source'], 'defaultProjectEnvironment': {}}})
                cid = result.get('cascadeId')
                if not isinstance(cid, str) or not history.UUID.fullmatch(cid):
                    raise native.NativeError('Test conversation creation returned no valid ID. Inspect the test projects before doing anything else.')
                run['conversation'] = cid
                save(run)
                native.rpc(connection, 'UpdateConversationAnnotations', {'cascadeId': cid,
                    'annotations': {'title': 'Disposable project move test'}, 'mergeAnnotations': True})
                initial = snapshot(connection, run)
                if initial['projectId'] != run['source']:
                    raise native.NativeError('The test conversation was not created in the source project.')
                run['phase'] = 'ready'
            except (native.NativeError, OSError) as error:
                run['phase'], run['error'] = 'setup stopped', str(error)
            save(run)
            return report(run)
        if not run or 'conversation' not in run:
            raise native.NativeError('Create the disposable test first. If setup stopped, share View results.')
        if payload['action'] == 'attempt':
            if run['phase'] != 'ready':
                raise native.NativeError('This test cannot be attempted again. Check and share the existing results.')
            if models.active_id() == run['conversation']:
                raise native.NativeError('Open a different conversation in Terminal before testing the move.')
            before = snapshot(connection, run)
            if before['projectId'] != run['source'] or before['status'] not in history.IDLE or before['steps'] < 1:
                raise native.NativeError('Send a short message in the test conversation, wait for completion, then open a different conversation before testing.')
            if not before['historyDigest']:
                run['phase'], run['before'], run['error'] = 'history verification unavailable', before, 'The CLI did not return verifiable test history. No project update was attempted.'
                save(run)
                return report(run)
            for key in ('source', 'destination'):
                record = before['projectRecords'][key]
                if record.get('name') != run[key + 'Name'] or record.get('archived'):
                    raise native.NativeError('A test project was renamed or archived. No update was attempted.')
            # Refuse projects containing any other conversations, even if their reference list is stale.
            for cid, row in history.collect(connection).items():
                if row.get('projectId') in (run['source'], run['destination']) and cid != run['conversation']:
                    raise native.NativeError('A test project contains another conversation. No update was attempted.')
            run['before'] = before
            try:
                left, right = reference_update(before['projectRecords']['source'], before['projectRecords']['destination'], run['conversation'])
            except native.NativeError as error:
                run['phase'], run['error'] = 'unsupported reference format', str(error)
                save(run)
                return report(run)
            run['phase'], run['attemptProcess'] = 'attempt started', process_id(connection)
            save(run)
            try:
                # Test objects only. Add the reference first; never delete a conversation or its files.
                native.rpc(connection, 'UpdateProject', {'project': right})
                run['phase'] = 'destination updated'
                save(run)
                native.rpc(connection, 'UpdateProject', {'project': left})
                run['phase'] = 'attempt completed'
            except native.NativeError as error:
                run['phase'], run['error'] = 'attempt stopped', str(error)
            save(run)
        try:
            current = snapshot(connection, run)
            before = run.get('before', {})
            check = {'afterRestart': bool(run.get('attemptProcess') and process_id(connection) != run['attemptProcess']),
                     'actualProjectIsDestination': current['projectId'] == run['destination'],
                     'historyUnchanged': bool(before.get('historyDigest') and current['historyDigest'] == before['historyDigest']),
                     'stepCountUnchanged': current['steps'] == before.get('steps'), 'snapshot': current}
            run['checks'] = (run.get('checks', []) + [check])[-8:]
            run.pop('checkError', None)
        except native.NativeError as error:
            run['checkError'] = str(error)
        save(run)
        return report(run)
