import subprocess
import unittest
from unittest.mock import patch

from test_mobile import m


class HistoryTests(unittest.TestCase):
    def test_history_capture_and_errors(self):
        with patch.object(m.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, 'old line\nnew line\n')) as run:
            self.assertEqual(m.send_input({'action': 'history'})['text'], 'old line\nnew line\n')
            self.assertEqual(run.call_args.args[0], ['tmux', 'capture-pane', '-p', '-J', '-S', '-20000', '-t', 'antigravity:0.0'])
        with patch.object(m.subprocess, 'run', side_effect=subprocess.TimeoutExpired('tmux', 5)):
            with self.assertRaises(subprocess.TimeoutExpired):
                m.send_input({'action': 'history'})
        for value in ({'action': 'history', 'command': 'anything'}, {'action': 'unknown'}):
            with self.assertRaises(ValueError):
                m.send_input(value)
