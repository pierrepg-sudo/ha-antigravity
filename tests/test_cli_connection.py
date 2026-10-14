"""Optional integration: ANTIGRAVITY_TEST_BINARY points to Google's real CLI."""
import os
from pathlib import Path
import pty
import tempfile
import threading
import unittest
from unittest.mock import patch
import native_connection as native
import launch_cli
from network_guard import block_outbound
import conversation_history


@unittest.skipUnless(os.environ.get('ANTIGRAVITY_TEST_BINARY'), 'Set ANTIGRAVITY_TEST_BINARY for live CLI checks')
class RealCLITests(unittest.TestCase):
    def test_authenticated_startup_without_hooks_or_login(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            with patch.object(native, 'STATE', root/'connection.json'):
                master, slave=pty.openpty()
                child, token=launch_cli.start(os.environ['ANTIGRAVITY_TEST_BINARY'], ['--gemini_dir='+str(root/'gemini')], root/'cli.log', stdin=slave, stdout=slave, stderr=slave, cwd=directory, start_new_session=True, preexec_fn=block_outbound, env={'HOME':directory,'PATH':'/usr/bin:/bin','TERM':'xterm-256color'})
                os.close(slave)
                # Some test runners mount host /proc inside a nested PID namespace.
                # In that case only identity lookup is adapted; launcher, CLI, token,
                # HTTP authentication and on-disk persistence remain real.
                process_patch = None
                if int(Path('/proc/self/stat').read_text().split(' ', 1)[0]) != os.getpid():
                    def child_identity(pid):
                        if pid != child.pid or child.poll() is not None:
                            raise ProcessLookupError()
                        return os.getpid(), 'live-test-child'
                    process_patch = patch.object(native, 'process', side_effect=child_identity)
                    process_patch.start()
                    self.addCleanup(process_patch.stop)
                try:
                    self.assertTrue(launch_cli.connect(child, token, root/'cli.log', threading.Event(), timeout=30))
                    connection=native.load()
                    self.assertEqual(connection['pid'], child.pid)
                    self.assertEqual(native.STATE.stat().st_mode & 0o777, 0o600)
                    self.assertIsInstance(conversation_history.listing()['items'], list)
                    self.assertNotIn(token, (root/'cli.log').read_text())
                    self.assertNotIn(token, str(conversation_history.listing()))
                    with self.assertRaisesRegex(native.NativeError, '401'):
                        native.summaries(dict(connection, token='incorrect-integration-test-token'))
                finally:
                    child.terminate()
                    try:child.wait(timeout=5)
                    except Exception:child.kill();child.wait()
                    os.close(master)
                with self.assertRaises(native.NativeError):native.load()


class StartupTests(unittest.TestCase):
    def test_failed_verification_does_not_publish_connection(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);log=root/'cli.log'
            log.write_text('Starting language server process with pid 42\nLanguage server listening on random port at 1234 for HTTP\n')
            with patch.object(native,'STATE',root/'connection.json'), patch.object(native,'process',return_value=(1,'123')), patch.object(native,'summaries',side_effect=native.NativeError('rejected')), patch.object(launch_cli.time,'monotonic',side_effect=[0,0,61]):
                child=unittest.mock.Mock(pid=42);child.poll.return_value=None
                self.assertFalse(launch_cli.connect(child,'private-test-token',log,threading.Event()))
                self.assertFalse(native.STATE.exists())
                self.assertIn('[connection:unavailable]',native.connection_diagnostic())
                self.assertNotIn('private-test-token', native.STATE.with_name('ha-native-status.json').read_text())
