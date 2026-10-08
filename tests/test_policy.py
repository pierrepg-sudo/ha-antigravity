import json
from pathlib import Path
import tempfile
import unittest
from test_mobile import m
import prepare_settings as policy


class PolicyTests(unittest.TestCase):
    def test_migration_preserves_preferences_data_and_user_restrictions(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)/'.gemini/antigravity-cli/settings.json'
            path.parent.mkdir(parents=True)
            old = {'colorScheme': 'light', 'permissions': {'allow': ['command(*)'],
                   'ask': ['mcp(*)', 'read_url(*)', 'command(*)', 'read_file(/private)'],
                   'deny': ['read_file(/secret)']}}
            path.write_text(json.dumps(old))
            path.with_name('ha-managed-permissions.json').write_text(json.dumps({'addedAsk': ['mcp(*)','read_url(*)','command(*)']}))
            other = path.parent.parent/'config/mcp_config.json'
            other.parent.mkdir()
            other.write_text(json.dumps({'mcpServers': {'existing': {'command': 'existing'}}}))
            policy.prepare(path, domains=['docs.python.org'])
            result = json.loads(path.read_text())
            self.assertFalse(result['enableTerminalSandbox'])
            self.assertFalse(result['allowNonWorkspaceAccess'])
            self.assertEqual(result['toolPermission'], 'request-review')
            self.assertEqual(result['artifactReviewPolicy'], 'always-proceed')
            self.assertEqual(result['colorScheme'], 'light')
            self.assertEqual(result['permissions']['allow'], policy.ALLOW+['read_url(docs.python.org)'])
            self.assertIn('command(*)',result['permissions']['deny'])
            self.assertIn('unsandboxed(*)',result['permissions']['deny'])
            self.assertIn('read_file(/secret)', result['permissions']['deny'])
            self.assertIn('read_file(/private)', result['permissions']['ask'])
            self.assertNotIn('mcp(*)', result['permissions']['ask'])
            self.assertIn('existing',json.loads(other.read_text())['mcpServers'])
            self.assertEqual(json.loads(path.with_name('settings.before-restricted-worker.json').read_text()),old)
            policy.prepare(path)
            self.assertEqual(json.loads(path.read_text())['permissions']['allow'],policy.ALLOW)
            self.assertEqual(json.loads(path.with_name('settings.before-restricted-worker.json').read_text()),old)

    def test_user_mcp_review_is_not_removed(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'cli/settings.json';path.parent.mkdir()
            path.write_text(json.dumps({'permissions':{'ask':['mcp(*)']}}))
            policy.prepare(path)
            self.assertIn('mcp(*)',json.loads(path.read_text())['permissions']['ask'])

    def test_invalid_settings_and_domains_fail_closed(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'settings.json'
            for value in ([], {'permissions':[]}, {'permissions':{'allow':'*'}}):
                path.write_text(json.dumps(value))
                with self.assertRaises(ValueError):policy.prepare(path)
                self.assertEqual(json.loads(path.read_text()),value)
            for domains in (['*'], ['http://example.org'], ['127.0.0.1'], ['host.local'], ['example.org/path']):
                with self.assertRaises(ValueError):policy.trusted_domains(domains)

    def test_invalid_mcp_fails_before_settings_change(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'.gemini/antigravity-cli/settings.json';path.parent.mkdir(parents=True)
            path.write_text('{}')
            mcp=path.parent.parent/'config/mcp_config.json';mcp.parent.mkdir()
            mcp.write_text('{"mcpServers": null}')
            with self.assertRaisesRegex(policy.ConfigurationError, 'Global MCP configuration'):
                policy.prepare(path)
            self.assertEqual(path.read_text(),'{}')

    def test_diagnostics_never_include_configuration_contents(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'settings.json'
            path.write_text('{"SECRET_TOKEN": sensitive-value}')
            with self.assertRaisesRegex(policy.ConfigurationError, 'invalid JSON at line 1') as error:
                policy.read_config(path,'CLI settings')
            self.assertNotIn('SECRET_TOKEN',str(error.exception))
            self.assertNotIn('sensitive-value',str(error.exception))
            with patch.object(Path,'read_text',side_effect=PermissionError(13,'SECRET_TOKEN')):
                with self.assertRaisesRegex(policy.ConfigurationError, 'cannot read \\(errno=13\\)') as error:
                    policy.read_config(path,'CLI settings')
                self.assertNotIn('SECRET_TOKEN',str(error.exception))

    def test_invalid_encoding_is_redacted(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'settings.json'
            path.write_bytes(b'SECRET_TOKEN=\xff')
            with self.assertRaisesRegex(policy.ConfigurationError, 'not valid UTF-8') as error:
                policy.read_config(path,'CLI settings')
            self.assertNotIn('SECRET_TOKEN',str(error.exception))
