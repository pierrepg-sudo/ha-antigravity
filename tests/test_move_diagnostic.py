import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import move_diagnostic as diagnostic
import conversation_management as management
import conversation_history as history
import conversation_models as models
import native_connection as native


class MoveDiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.connection = {'pid': 123, 'started': 'one'}
        self.records, self.rows, self.calls = {}, {}, []
        self.cid = '00000000-0000-0000-0000-000000000001'
        self.history = [{'type': 'user', 'text': 'Reply OK'}, {'type': 'assistant', 'text': 'OK'}]
        for target, key, value in [(native, 'STATE', Path(self.temp.name)/'state.json'),
                                   (native, 'load', lambda: self.connection),
                                   (native, 'rpc', self.rpc), (native, 'summaries', lambda c: copy.deepcopy(self.rows)),
                                   (management, 'ensure_folder', lambda c, p: '/test/'+p),
                                   (history, 'collect', lambda c: {cid: dict(r, projectId=r['trajectoryMetadata']['projectId']) for cid, r in self.rows.items()}),
                                   (models, 'active_id', lambda: 'other')]:
            p = patch.object(target, key, value); p.start(); self.addCleanup(p.stop)

    def rpc(self, connection, method, payload):
        self.calls.append((method, copy.deepcopy(payload)))
        if method == 'CreateProject':
            p = copy.deepcopy(payload['project']); self.records[p['id']] = p
        elif method == 'ReadProject':
            return {'project': copy.deepcopy(self.records[payload['id']])}
        elif method == native.START:
            pid = payload['projectEnvConfig']['projectId']
            self.rows[self.cid] = {'status': 'CASCADE_RUN_STATUS_IDLE', 'stepCount': 2, 'trajectoryMetadata': {'projectId': pid}}
            self.records[pid]['projectConversations'] = {'conversations': [{'conversationId': self.cid, 'environmentId': 'e1'}]}
            return {'cascadeId': self.cid}
        elif method == 'UpdateProject':
            # Deliberately model an API that accepts records but does NOT reassign the trajectory.
            self.records[payload['project']['id']] = copy.deepcopy(payload['project'])
        elif method == 'GetCascadeTrajectory':
            return {'trajectory': {'steps': self.history}}
        return {}

    def call(self, action):
        return diagnostic.action({'action': action, 'confirm': True})['run']

    def test_native_reference_change_is_not_misreported_as_move(self):
        run = self.call('setup')
        source, target = run['source'], run['destination']
        self.records[source]['settings'] = {'secret': 'never disclose'}
        result = self.call('attempt')
        self.assertEqual(result['phase'], 'attempt completed')
        self.assertFalse(result['checks'][-1]['actualProjectIsDestination'])
        self.assertTrue(result['checks'][-1]['historyUnchanged'])
        self.assertNotIn('settings', result['before']['projectRecords']['source'])
        self.assertEqual({p['project']['id'] for m, p in self.calls if m == 'UpdateProject'}, {source, target})
        self.assertFalse(any(m.startswith('Delete') for m, _ in self.calls))
        self.connection['started'] = 'two'
        self.assertTrue(self.call('check')['checks'][-1]['afterRestart'])
        self.history[1]['text'] = 'changed'
        self.assertFalse(self.call('check')['checks'][-1]['historyUnchanged'])
        before = len(self.calls)
        with self.assertRaises(native.NativeError): self.call('attempt')
        self.assertFalse(any(m == 'UpdateProject' for m, _ in self.calls[before:]))

    def test_refuses_existing_or_busy_conversations_and_client_ids(self):
        run = self.call('setup')
        with self.assertRaises(native.NativeError): self.call('setup')
        with self.assertRaises(native.NativeError): diagnostic.action({'action': 'attempt', 'confirm': True, 'id': 'user-conversation'})
        self.rows['other'] = {'status': 'CASCADE_RUN_STATUS_IDLE', 'trajectoryMetadata': {'projectId': run['source']}}
        with self.assertRaises(native.NativeError): self.call('attempt')
        self.rows.pop('other')
        self.rows[self.cid]['status'] = 'CASCADE_RUN_STATUS_RUNNING'
        with self.assertRaises(native.NativeError): self.call('attempt')
        self.assertFalse(any(m == 'UpdateProject' for m, _ in self.calls))

    def test_unknown_format_stops_before_mutation(self):
        run = self.call('setup')
        self.records[run['source']].pop('projectConversations')
        result = self.call('attempt')
        self.assertEqual(result['phase'], 'unsupported reference format')
        self.assertFalse(any(m == 'UpdateProject' for m, _ in self.calls))

    def test_lost_response_is_persisted_without_retry(self):
        self.call('setup')
        original = self.rpc
        def lost(connection, method, payload):
            result = original(connection, method, payload)
            if method == 'UpdateProject': raise native.NativeError('Response lost')
            return result
        with patch.object(native, 'rpc', lost): result = self.call('attempt')
        self.assertEqual(result['phase'], 'attempt stopped')
        self.assertEqual(len([m for m, _ in self.calls if m == 'UpdateProject']), 1)
        with self.assertRaises(native.NativeError): self.call('attempt')
        self.assertEqual(self.call('report')['error'], 'Response lost')

    def test_setup_failure_preserves_generated_ids(self):
        with patch.object(native, 'rpc', side_effect=native.NativeError('Response lost')):
            result = self.call('setup')
        self.assertEqual(result['phase'], 'setup stopped')
        self.assertIn('source', result)
        with self.assertRaises(native.NativeError): self.call('setup')

    def test_active_test_is_rejected(self):
        self.call('setup')
        with patch.object(models, 'active_id', return_value=self.cid):
            with self.assertRaises(native.NativeError): self.call('attempt')
        self.assertFalse(any(m == 'UpdateProject' for m, _ in self.calls))

    def test_missing_history_prevents_project_update(self):
        self.call('setup')
        self.history = []
        result = self.call('attempt')
        self.assertEqual(result['phase'], 'history verification unavailable')
        self.assertFalse(any(m == 'UpdateProject' for m, _ in self.calls))


if __name__ == '__main__': unittest.main()
