import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from test_mobile import m
import prepare_settings


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

    def test_inline_defaults_preserve_user_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'settings.json'
            prepare_settings.prepare(path)
            self.assertEqual(json.loads(path.read_text()), {'altScreenMode': 'never'})
            for mode in ('default', 'always', 'never'):
                settings = {'altScreenMode': mode, 'toolPermission': 'strict', 'unknown': {'value': 5}}
                path.write_text(json.dumps(settings))
                prepare_settings.prepare(path)
                settings['altScreenMode'] = 'never' if mode == 'default' else mode
                self.assertEqual(json.loads(path.read_text()), settings)
            for invalid in ('broken json', '[]'):
                path.write_text(invalid)
                prepare_settings.prepare(path)
                self.assertEqual(path.read_text(), invalid)
