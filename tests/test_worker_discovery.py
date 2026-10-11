import json
import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch, MagicMock
import worker_mcp as mcp
import prepare_settings as policy


class WorkerDiscoveryTests(TestCase):
    def dispatch_response(self, response, name='run', args=None):
        connection = MagicMock()
        connection.makefile.return_value.__enter__.return_value.readline.return_value = json.dumps(response).encode()+b'\n'
        with patch.object(mcp.socket, 'socket') as factory:
            factory.return_value.__enter__.return_value = connection
            result = mcp.dispatch({'method': 'tools/call', 'params': {
                'name': name, 'arguments': args if args is not None else {'command': 'example-command'}}})
        connection.sendall.assert_called_once()
        return result, json.loads(result['content'][0]['text'])

    def test_timeout_guidance_preserves_result_without_retry(self):
        source = {'exitCode': -9, 'timedOut': True, 'truncated': False, 'output': 'partial output'}
        result, detail = self.dispatch_response(source)
        self.assertTrue(result['isError'])
        self.assertEqual({k: detail[k] for k in source}, source)
        for phrase in ('status with {}', 'managed foreground job', 'partial work', 'never automatically replay', 'already authorized'):
            self.assertIn(phrase, detail['guidance'])

    def test_application_failure_requires_diagnosis(self):
        for output in ('setsid: Operation not permitted', 'ModuleNotFoundError', 'invalid credentials'):
            result, detail = self.dispatch_response({'exitCode': 1, 'output': output})
            self.assertTrue(result['isError'])
            self.assertIn('exit code alone does not identify the cause', detail['guidance'])
            self.assertIn('need their own fixes', detail['guidance'])
            self.assertEqual(detail['output'], output)

    def test_failed_managed_job_gets_guidance_on_status_and_logs(self):
        for name in ('status', 'logs'):
            result, detail = self.dispatch_response({'id': 'a'*32, 'state': 'failed', 'exitCode': 1}, name, {'job_id': 'a'*32})
            self.assertTrue(result['isError'])
            self.assertIn('never automatically replay', detail['guidance'])

    def test_worker_error_never_proposes_another_job(self):
        result, detail = self.dispatch_response({'error': 'Restricted worker isolation checks failed'})
        self.assertTrue(result['isError'])
        self.assertIn('Do not launch another job', detail['guidance'])
        self.assertNotIn('always propose', detail['guidance'])

    def test_success_unchanged(self):
        source = {'exitCode': 0, 'timedOut': False, 'output': 'ok'}
        result, detail = self.dispatch_response(source)
        self.assertFalse(result['isError'])
        self.assertEqual(detail, source)

    def test_uncertain_transport_never_claims_not_run(self):
        with patch.object(mcp.socket, 'socket') as factory:
            connection = factory.return_value.__enter__.return_value
            connection.makefile.return_value.__enter__.return_value.readline.side_effect = TimeoutError()
            result = mcp.dispatch({'method': 'tools/call', 'params': {
                'name': 'start', 'arguments': {'command': 'example', 'name': 'example'}}})
            connection.sendall.assert_called_once()
        self.assertTrue(result['isError'])
        self.assertIn('outcome may be unknown', result['content'][0]['text'])
        self.assertNotIn('No command was run', result['content'][0]['text'])

    def test_export_matches_live_contract(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root/'AGENTS.md').write_text('Existing instructions\n')
            mcp.export_docs(root)
            exported = json.loads((root/'WORKER_TOOLS.json').read_text())
            self.assertEqual(exported['tools'], mcp.dispatch({'method': 'tools/list'})['tools'])
            self.assertEqual(exported['instructions'], mcp.dispatch({'method':'initialize'})['instructions'])
            self.assertTrue((root/'AGENTS.md').read_text().startswith('Existing instructions'))
            self.assertIn('"job_id"', (root/'AGENTS.md').read_text())
            self.assertIn(mcp.RECOVERY_GUIDANCE, exported['instructions'])
            self.assertIn(mcp.RECOVERY_GUIDANCE, (root/'AGENTS.md').read_text())

    def test_invalid_call_gives_schema_without_broker_or_secrets(self):
        with patch.object(mcp.socket, 'socket') as connect:
            for args in ({'id':'secret-value'}, {'name':'paper-trader'}, {'job_id':'c358bd53...'}, {'job_id':'z'*32}):
                result = mcp.dispatch({'method':'tools/call', 'params':{'name':'logs','arguments':args}})
                self.assertTrue(result['isError'])
                text = result['content'][0]['text']
                detail = json.loads(text)
                self.assertFalse(detail['requestSent'])
                self.assertIn('job_id', detail['inputSchema']['required'])
                self.assertIn('status with {}', detail['error'])
                self.assertNotIn('secret-value', text)
            connect.assert_not_called()
        mcp.validate('logs', {'job_id':'a'*32})
        mcp.validate('status', {})

    def test_read_grant_does_not_remove_denies(self):
        self.assertIn('read_file(/opt/antigravity-workspace)', policy.ALLOW)
        for rule in ('write_file(/opt/antigravity-workspace)', 'read_file(/data/home/.gemini/antigravity-cli)', 'command(*)', 'unsandboxed(*)'):
            self.assertIn(rule, policy.DENY)
