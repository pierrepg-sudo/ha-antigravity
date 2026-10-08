import os
from pathlib import Path
import tempfile
import unittest
from test_mobile import m
import sandbox_diagnostic as diag


class SandboxDiagnosticTests(unittest.TestCase):
    def test_allowlisted_fields_only(self):
        self.assertEqual(diag.summarize('sbox: mount tmpfs /dev/shm/setup/root: permission denied'),
                         'sbox: mount tmpfs /dev/shm/setup/root: permission denied')
        self.assertEqual(diag.summarize('sbox: mount tmpfs /private/secret-token: permission denied'),
                         'sbox: mount tmpfs [REDACTED]: permission denied')
        for line in ('sbox: token=secret-token', 'sbox: mount /dev/shm: secret-token',
                     'sbox: mount /dev/shm: permission denied token=secret-token',
                     'sbox: mount tmpfs /dev/shm\x1b: permission denied'):
            self.assertNotIn('secret-token', diag.summarize(line))
            self.assertNotIn('\x1b', diag.summarize(line))

    def test_latest_bounded_and_no_unrelated_log_output(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder); (base / 'log').mkdir()
            log = base / 'log/cli-20261008_080808.log'
            (base / 'cli.log').symlink_to('log/' + log.name)
            log.write_text('sbox: mount proc: permission denied\n' + 'secret-token\n' * 7000)
            self.assertIn('No sbox error', diag.latest(base)['message'])
            with log.open('a') as target:
                target.write('sbox: mount tmpfs /dev/shm/setup/root: permission denied\ncredential=secret-token\n')
            result = diag.latest(base)
            self.assertEqual(result['message'], 'sbox: mount tmpfs /dev/shm/setup/root: permission denied')
            self.assertNotIn('secret-token', str(result))
            self.assertIn('logModifiedUTC', result)

    def test_rejects_arbitrary_targets_symlinks_and_special_files(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder); (base / 'log').mkdir()
            link = base / 'cli.log'
            link.symlink_to('/etc/passwd')
            self.assertIn('unavailable', diag.latest(base)['message'])
            link.unlink(); link.symlink_to('log/cli-20261008_080808.log')
            log = base / 'log/cli-20261008_080808.log'
            log.symlink_to('/etc/passwd')
            self.assertIn('unavailable', diag.latest(base)['message'])
            log.unlink(); os.mkfifo(log)
            self.assertIn('unavailable', diag.latest(base)['message'])
            log.unlink(); log.write_text('sbox: mount proc: permission denied\n')
            link.unlink(); link.symlink_to(str(log))
            self.assertEqual(diag.latest(base)['message'], 'sbox: mount proc: permission denied')
