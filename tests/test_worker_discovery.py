import json
import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch
import worker_mcp as mcp
import prepare_settings as policy


class WorkerDiscoveryTests(TestCase):
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
