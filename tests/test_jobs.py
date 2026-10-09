import json
import subprocess
import tempfile
import time
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch
import command_worker as worker
import worker_mcp as mcp


class ManagedJobsTests(TestCase):
    def wait_done(self, jobs, job_id):
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            state = jobs.request('status', {'job_id': job_id})
            if state['state'] not in ('starting', 'running', 'stopping'):
                return state
            time.sleep(.03)
        self.fail('Job did not finish')

    def test_lifecycle_logs_duplicate_capacity_stop_and_cleanup(self):
        real_spawn = subprocess.Popen
        def spawn(argv, **kwargs):
            self.assertEqual(argv[3], 'outer//command_worker')
            self.assertEqual(argv[6], 'managed')
            return real_spawn(['/bin/bash', '-c', argv[5]], **kwargs)
        with tempfile.TemporaryDirectory() as d, patch.object(worker, 'TMP', Path(d)), patch.object(worker.subprocess, 'Popen', side_effect=spawn):
            jobs = worker.Jobs('outer//command_worker')
            try:
                first = jobs.start("printf 'started\\n'; sleep 60", 'first')
                duplicate = jobs.start("printf 'started\\n'; sleep 60", 'another-name')
                self.assertEqual(first['id'], duplicate['id'])
                self.assertTrue(duplicate['alreadyRunning'])
                second = jobs.start('trap "" TERM; sleep 61', 'second')
                with self.assertRaisesRegex(ValueError, 'Two managed'):
                    jobs.start('sleep 62', 'third')
                time.sleep(.2)
                logs = jobs.request('logs', {'job_id': first['id']})
                self.assertIn('started', logs['output'])
                self.assertNotIn('command', logs)
                self.assertEqual(jobs.request('stop', {'job_id': first['id']})['state'], 'stopping')
                self.assertEqual(self.wait_done(jobs, first['id'])['state'], 'stopped')
                ended = jobs.start("python3 -c 'print(\"x\"*300000); print(\"END\")'", 'output')
                self.assertEqual(self.wait_done(jobs, ended['id'])['exitCode'], 0)
                tail = jobs.request('logs', {'job_id': ended['id']})
                self.assertTrue(tail['truncated'])
                self.assertLessEqual(len(tail['output']), worker.MAX_OUTPUT)
                self.assertTrue(tail['output'].endswith('END\n'))
            finally:
                jobs.close()
            self.assertEqual(jobs.request('status', {'job_id': second['id']})['state'], 'stopped')
            self.assertEqual(list(Path(d).iterdir()), [])
            with self.assertRaisesRegex(ValueError, 'shutting down'):
                jobs.start('true', 'closed')

    def test_leader_exit_cleans_descendants_holding_output_open(self):
        real_spawn = subprocess.Popen
        def spawn(argv, **kwargs):
            return real_spawn(['/bin/bash', '-c', argv[5]], **kwargs)
        with tempfile.TemporaryDirectory() as d, patch.object(worker, 'TMP', Path(d)), patch.object(worker.subprocess, 'Popen', side_effect=spawn):
            jobs = worker.Jobs('label')
            try:
                item = jobs.start('sleep 60 & echo leader-exit', 'descendants')
                self.assertEqual(self.wait_done(jobs, item['id'])['exitCode'], 0)
                self.assertEqual(list(Path(d).iterdir()), [])
            finally:
                jobs.close()

    def test_no_arbitrary_pid_control_or_bad_arguments(self):
        jobs = worker.Jobs('label')
        for args in ({'pid': 1}, {'job_id': 1}, {'job_id': 'unknown'}):
            with self.assertRaises(ValueError): jobs.request('stop', args)
        for name in ('', '../escape', 'space name', 'x'*65):
            with self.assertRaises(ValueError): jobs.start('true', name)
        self.assertEqual(jobs.request('status', {}), {'jobs': []})

    def test_mcp_tools_validation_and_managed_grants(self):
        import prepare_settings
        names = {t['name'] for t in mcp.dispatch({'method': 'tools/list'})['tools']}
        self.assertEqual(names, {'run', 'start', 'stop', 'status', 'logs'})
        for name in names:
            self.assertIn('mcp(ha-restricted-worker/'+name+')', prepare_settings.ALLOW)
        for name, args in [('start', {'command': 'true'}), ('stop', {'pid': 42}), ('logs', {}), ('start', {'command': 'true', 'name': '../bad'})]:
            with self.assertRaises(ValueError): mcp.validate(name, args)
        mcp.validate('status', {})
        mcp.validate('start', {'command': 'python3 -u script.py', 'name': 'agent'})

    def test_start_failure_is_reported_and_temp_removed(self):
        with tempfile.TemporaryDirectory() as d, patch.object(worker, 'TMP', Path(d)), patch.object(worker.subprocess, 'Popen', side_effect=OSError):
            jobs = worker.Jobs('label')
            item = jobs.start('true', 'broken')
            self.assertEqual(self.wait_done(jobs, item['id'])['state'], 'failed')
            self.assertEqual(list(Path(d).iterdir()), [])
            jobs.close()
