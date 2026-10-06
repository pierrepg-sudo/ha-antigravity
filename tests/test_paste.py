import subprocess
import unittest
from unittest.mock import patch
from test_mobile import m


class PasteTests(unittest.TestCase):
    def test_literal_text_and_no_enter(self):
        with patch.object(m, 'tmux') as run, patch.object(m.secrets, 'token_hex', return_value='abc'):
            self.assertTrue(m.send_input({'action':'paste','text':'café\r\n$(anything)\ttext'})['ok'])
            calls = run.call_args_list
            self.assertEqual(calls[0].args, ('load-buffer', '-b', 'mobile-abc', '-'))
            self.assertEqual(calls[0].kwargs['input'], 'café\n$(anything)    text'.encode())
            self.assertEqual(calls[1].args, ('if-shell', '-F', '-t', 'antigravity:0.0', '#{bracket_paste_flag}',
                'paste-buffer -p -r -d -b mobile-abc -t antigravity:0.0',
                "paste-buffer -s ' ' -d -b mobile-abc -t antigravity:0.0"))
            self.assertEqual(calls[2].args, ('delete-buffer', '-b', 'mobile-abc'))

    def test_reject_invalid_before_terminal_access(self):
        with patch.object(m, 'tmux') as run:
            for value in ('', None, '\x1b[201~', '\x00', '\x03', '\x7f', '\x85', 'é'*32769):
                with self.assertRaises(ValueError): m.paste_text(value)
            run.assert_not_called()

    def test_cleanup_after_paste_failure(self):
        with patch.object(m, 'tmux', side_effect=[None, subprocess.TimeoutExpired('tmux',5), None]) as run:
            with self.assertRaises(subprocess.TimeoutExpired): m.paste_text('example')
            self.assertEqual(run.call_args.args[0], 'delete-buffer')
