import json
import os
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch, MagicMock
import command_worker as worker
import worker_mcp as mcp


class RestartRecoveryTests(TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)
        self.store = worker.ResumeStore(self.directory)
        self.jobs = worker.Jobs('label', self.store)
        self.entered = threading.Event()

    def tearDown(self):
        self.jobs.close()
        self.store.close()
        self.temp.cleanup()

    def running(self, command, label, timeout=None, stop=None, capture=None):
        self.entered.set()
        stop.wait(5)
        return {'exitCode': -15, 'interrupted': stop.is_set()}

    def reboot(self):
        self.jobs.close()
        self.store.close()
        self.store = worker.ResumeStore(self.directory)
        self.jobs = worker.Jobs('label', self.store)
        self.entered.clear()
        self.jobs.restore()

    def test_opt_in_survives_shutdown_with_same_id_and_no_command_leak(self):
        with patch.object(worker, 'execute', side_effect=self.running) as run:
            item = self.jobs.start('python3 script.py', 'agent', True)
            self.assertTrue(self.entered.wait(1))
            self.assertNotIn('command', item)
            self.reboot()
            self.assertTrue(self.entered.wait(1))
            result = self.jobs.request('status', {'job_id': item['id']})
            self.assertEqual(result['state'], 'running')
            self.assertEqual(result['recovery_count'], 1)
            self.assertEqual(run.call_count, 2)
            self.assertEqual(self.store.records[item['id']]['cwd'], worker.CWD)
            self.assertEqual((self.directory/'jobs.json').stat().st_mode & 0o777, 0o600)

    def test_default_and_explicit_stop_never_resume(self):
        with patch.object(worker, 'execute', side_effect=self.running) as run:
            default = self.jobs.start('one', 'default')
            opted = self.jobs.start('two', 'opted', True)
            self.jobs.request('stop', {'job_id': opted['id']})
            self.assertNotIn(opted['id'], self.store.records)
            self.reboot()
            self.assertEqual(self.jobs.request('status', {}), {'jobs': []})
            self.assertLessEqual(run.call_count, 2)
            self.assertFalse(default['resume_after_restart'])

    def test_completion_failure_and_launch_exception_clear_intent(self):
        for outcome in ({'exitCode': 0}, {'exitCode': 1}, OSError()):
            with patch.object(worker, 'execute', side_effect=[outcome]):
                item = self.jobs.start('one', 'agent', True)
                self.jobs.items[item['id']]['thread'].join(1)
                self.assertNotIn(item['id'], self.store.records)
                self.assertFalse(self.jobs.items[item['id']]['resume_after_restart'])

    def test_policy_toggle_and_duplicate_do_not_restart(self):
        with patch.object(worker, 'execute', side_effect=self.running) as run:
            item = self.jobs.start('one', 'agent')
            self.assertTrue(self.entered.wait(1))
            duplicate = self.jobs.start('one', 'agent', True)
            self.assertFalse(duplicate['resume_after_restart'])
            args = {'job_id': item['id'], 'resume_after_restart': True}
            self.jobs.request('restart_policy', args)
            self.assertIn(item['id'], self.store.records)
            self.jobs.request('restart_policy', dict(args, resume_after_restart=False))
            self.assertEqual(self.store.records, {})
            self.assertEqual(run.call_count, 1)
            with self.assertRaises(ValueError):
                self.jobs.request('restart_policy', dict(args, resume_after_restart='true'))

    def test_reboot_loop_suspends_after_three_attempts(self):
        with patch.object(worker, 'execute', side_effect=self.running) as run:
            item = self.jobs.start('one', 'agent', True)
            self.assertTrue(self.entered.wait(1))
            for _ in range(3):
                self.reboot()
                self.assertTrue(self.entered.wait(1))
            self.reboot()
            self.assertEqual(self.jobs.items[item['id']]['state'], 'recovery_suspended')
            self.assertFalse(self.store.records[item['id']]['pending'])
            self.assertEqual(run.call_count, 4)
            self.reboot()
            self.assertEqual(run.call_count, 4)

    def test_stale_attempt_window_allows_recovery(self):
        with patch.object(worker, 'execute', side_effect=self.running):
            item = self.jobs.start('one', 'agent', True)
            self.assertTrue(self.entered.wait(1))
            self.jobs.items[item['id']]['attempts'] = [time.time()-700]*3
            self.jobs.record(self.jobs.items[item['id']])
            self.reboot()
            self.assertTrue(self.entered.wait(1))
            self.assertEqual(self.jobs.items[item['id']]['recovery_count'], 1)

    def test_crash_intent_recovers_without_clean_close(self):
        # Persisted before spawn: simulates a power loss at any time after intent commit.
        ident = 'a'*32
        self.store.put(ident, {'name': 'agent', 'command': 'one', 'cwd': worker.CWD,
                               'attempts': [], 'pending': True})
        with patch.object(worker, 'execute', side_effect=self.running) as run:
            self.reboot()
            self.assertTrue(self.entered.wait(1))
            self.assertEqual(run.call_count, 1)
            self.assertIn(ident, self.jobs.items)

    def test_persistence_failure_prevents_start_and_does_not_confirm_stop(self):
        with patch.object(self.store, 'write', side_effect=OSError()), patch.object(worker, 'execute') as run:
            with self.assertRaises(OSError): self.jobs.start('one', 'agent', True)
            run.assert_not_called()
        with patch.object(worker, 'execute', side_effect=self.running):
            item = self.jobs.start('one', 'agent', True)
            self.assertTrue(self.entered.wait(1))
            with patch.object(self.store, 'write', side_effect=OSError()):
                with self.assertRaises(OSError): self.jobs.request('stop', {'job_id': item['id']})
                self.assertFalse(self.jobs.items[item['id']]['stop'].is_set())

    def test_exclusive_lock_and_corrupt_store_fail_closed(self):
        with self.assertRaises(BlockingIOError): worker.ResumeStore(self.directory)
        self.store.close()
        (self.directory/'jobs.json').write_text('{bad json')
        with self.assertRaises(ValueError): worker.ResumeStore(self.directory)
        (self.directory/'jobs.json').write_text('{"version":1,"jobs":{}}')
        self.store = worker.ResumeStore(self.directory)
        self.jobs.store = self.store

    def test_strict_schema_and_policy_permissions(self):
        import prepare_settings
        for args in ({'command': 'x', 'name': 'agent', 'resume_after_restart': 1},
                     {'command': 'x', 'name': 'agent', 'recovered': {}}):
            with self.assertRaises(ValueError): mcp.validate('start', args)
            with self.assertRaises(ValueError): self.jobs.request('start', args)
        mcp.validate('restart_policy', {'job_id': 'a'*32, 'resume_after_restart': True})
        self.assertIn('read_file(/data/worker-state)', prepare_settings.DENY)
        self.assertIn('write_file(/data/worker-state)', prepare_settings.DENY)
        self.assertIn('mcp(ha-restricted-worker/restart_policy)', prepare_settings.ALLOW)

    def test_no_persistent_store_cannot_enable(self):
        jobs = worker.Jobs('label')
        with self.assertRaises(ValueError): jobs.start('one', 'agent', True)

    def test_real_foreground_process_recovers_then_explicit_stop_persists(self):
        real_spawn = subprocess.Popen
        def spawn(argv, **kwargs):
            return real_spawn(['/bin/bash', '-c', argv[5]], **kwargs)
        tmp = self.directory/'temporary'
        tmp.mkdir()
        with patch.object(worker, 'TMP', tmp), patch.object(worker.subprocess, 'Popen', side_effect=spawn):
            item = self.jobs.start('echo ready; sleep 60', 'real', True)
            def wait_output():
                deadline = time.monotonic()+3
                while time.monotonic() < deadline:
                    if 'ready' in self.jobs.request('logs', {'job_id': item['id']})['output']:
                        return
                    time.sleep(.02)
                self.fail('No process output')
            wait_output()
            self.reboot()
            wait_output()
            self.assertEqual(self.jobs.items[item['id']]['recovery_count'], 1)
            self.jobs.request('stop', {'job_id': item['id']})
            self.jobs.close()
            self.assertEqual(self.store.records, {})
            self.assertEqual(list(tmp.iterdir()), [])

    def test_restore_is_idempotent(self):
        with patch.object(worker, 'execute', side_effect=self.running) as run:
            item = self.jobs.start('one', 'agent', True)
            self.assertTrue(self.entered.wait(1))
            self.reboot()
            self.assertTrue(self.entered.wait(1))
            self.jobs.restore()
            self.assertEqual(run.call_count, 2)
            self.assertEqual(self.jobs.items[item['id']]['recovery_count'], 1)

    def test_main_never_recovers_before_successful_isolation(self):
        for ready in (False, True):
            store, jobs, server = MagicMock(), MagicMock(), MagicMock()
            events = []
            jobs.restore.side_effect = lambda: events.append('restore')
            def check(label):
                events.append('isolation')
                return ready, ''
            with patch.object(worker.os, 'getuid', return_value=1002), \
                 patch.object(worker.Path, 'read_text', return_value='outer (enforce)'), \
                 patch.object(worker, 'ResumeStore', return_value=store), \
                 patch.object(worker, 'self_test', side_effect=check), \
                 patch.object(worker, 'STATUS', MagicMock()), \
                 patch.object(worker, 'Server') as server_class, \
                 patch.object(worker, 'Jobs', return_value=jobs), \
                 patch.object(worker.os, 'chmod'), patch.object(worker.signal, 'signal'):
                server_class.return_value.__enter__.return_value = server
                worker.main()
            self.assertEqual(events, ['isolation', 'restore'] if ready else ['isolation'])
            jobs.close.assert_called_once()
            store.close.assert_called_once()

    def test_completed_during_shutdown_is_not_recovered(self):
        entered, finish = threading.Event(), threading.Event()
        def complete(command, label, timeout=None, stop=None, capture=None):
            entered.set()
            stop.wait(2)
            return {'exitCode': 0, 'interrupted': False}
        with patch.object(worker, 'execute', side_effect=complete):
            item = self.jobs.start('one', 'agent', True)
            self.assertTrue(entered.wait(1))
            self.jobs.close()
            self.assertNotIn(item['id'], self.store.records)
