import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).parents[1] / 'antigravity'))
import prepare_settings as profiles
import prepare_storage


class ProfileTests(unittest.TestCase):
    def test_balanced_backup_and_narrow_grants(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'settings.json'
            original = {'altScreenMode': 'always', 'model': 'keep-me',
                        'permissions': {'allow': ['command(*)', 'unsandboxed(*)', 'write_file(*)'],
                                        'deny': ['command(sudo)'], 'ask': ['command(git push)']}}
            path.write_text(json.dumps(original))
            status = profiles.prepare(path, probe=lambda: {'passed': True})
            result = json.loads(path.read_text())
            self.assertEqual(result['permissions']['allow'], profiles.ALLOW)
            self.assertIn('command(sudo)', result['permissions']['deny'])
            self.assertIn('command(git push)', result['permissions']['ask'])
            self.assertIn('unsandboxed(*)', result['permissions']['ask'])
            self.assertNotIn('command(*)', result['permissions']['ask'])
            self.assertTrue(result['enableTerminalSandbox'])
            self.assertEqual(result['toolPermission'], 'proceed-in-sandbox')
            self.assertEqual(result['artifactReviewPolicy'], 'always-proceed')
            self.assertEqual(result['altScreenMode'], 'always')
            self.assertEqual(result['model'], 'keep-me')
            self.assertFalse(result['allowNonWorkspaceAccess'])
            self.assertFalse(status['nativeSandboxVerified'])
            backup = path.with_name('settings.before-balanced.json')
            self.assertEqual(json.loads(backup.read_text()), original)
            self.assertEqual(backup.stat().st_mode & 0o777, 0o600)
            profiles.prepare(path, probe=lambda: {'passed': True})
            self.assertEqual(json.loads(backup.read_text()), original)

    def test_failed_probe_and_explicit_review_never_auto_execute(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'settings.json'
            for requested in ('balanced', 'review'):
                status = profiles.prepare(path, requested, probe=lambda: {'passed': False})
                result = json.loads(path.read_text())
                self.assertEqual(status['effective'], 'review')
                self.assertFalse(result['enableTerminalSandbox'])
                self.assertEqual(result['toolPermission'], 'request-review')
                self.assertEqual(result['artifactReviewPolicy'], 'asks-for-review')
                self.assertIn('command(*)', result['permissions']['ask'])
            profiles.prepare(path, probe=lambda: {'passed': True})
            self.assertNotIn('command(*)', json.loads(path.read_text())['permissions']['ask'])

    def test_user_command_review_survives_profile_switch(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'settings.json'
            path.write_text(json.dumps({'permissions': {'ask': ['command(*)']}}))
            profiles.prepare(path, 'review')
            profiles.prepare(path, probe=lambda: {'passed': True})
            self.assertIn('command(*)', json.loads(path.read_text())['permissions']['ask'])

    def test_invalid_settings_stop_instead_of_using_permissive_defaults(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'settings.json'
            for invalid in ('broken json', '[]', '{"permissions":{"allow":"*"}}'):
                path.write_text(invalid)
                with self.assertRaises(ValueError):
                    profiles.prepare(path, probe=lambda: {'passed': True})
                self.assertEqual(path.read_text(), invalid)

    def test_probe_is_bounded_and_failure_is_conservative(self):
        for effect in (OSError(), subprocess.TimeoutExpired('unshare', 5)):
            with patch.object(profiles.subprocess, 'run', side_effect=effect):
                self.assertFalse(profiles.sandbox_prerequisites()['passed'])
        with patch.object(profiles.subprocess, 'run', return_value=subprocess.CompletedProcess([], 1)) as run:
            self.assertFalse(profiles.sandbox_prerequisites()['passed'])
            self.assertEqual(run.call_args.kwargs['timeout'], 5)

    def test_diagnostic_captures_error_without_inherited_secrets(self):
        result = subprocess.CompletedProcess([], 1, stderr=b'unshare: Operation not permitted\n')
        with patch.object(profiles.subprocess, 'run', return_value=result) as run, patch.dict(os.environ, {'SECRET_TOKEN': 'do-not-copy'}):
            report = profiles.sandbox_prerequisites()
        self.assertFalse(report['passed'])
        self.assertEqual(report['exitCode'], 1)
        self.assertEqual(report['error'], 'unshare: Operation not permitted')
        self.assertNotIn('SECRET_TOKEN', run.call_args.kwargs['env'])
        self.assertNotIn('do-not-copy', json.dumps(report))
        self.assertEqual(run.call_args.args[0][0], '/usr/bin/unshare')
        result.stderr = b'x' * 2000 + b'\x1b'
        with patch.object(profiles.subprocess, 'run', return_value=result):
            self.assertLessEqual(len(profiles.sandbox_prerequisites()['error']), 512)

    def test_storage_rejects_symlink_and_preserves_original_content(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(prepare_storage.os, 'chown'):
            base = Path(folder) / 'data';base.mkdir()
            runtime = Path(folder) / 'run'
            (base / 'workspace').mkdir()
            old = base / 'workspace/original.c';old.write_text('keep')
            outside = Path(folder) / 'outside';outside.mkdir()
            (base / 'workspace/link').symlink_to(outside)
            prepare_storage.prepare(base, runtime)
            self.assertEqual(old.read_text(), 'keep')
            self.assertEqual((base / 'workspace/outputs').stat().st_mode & 0o7777, 0o2770)
            self.assertEqual((base / 'inputs').stat().st_mode & 0o7777, 0o2750)
            (base / 'inputs').rmdir();(base / 'inputs').symlink_to(outside)
            with self.assertRaises(ValueError):
                prepare_storage.prepare(base, runtime)
