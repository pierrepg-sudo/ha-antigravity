import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch
import native_connection as native
import signin


class DiagnosticTests(unittest.TestCase):
    def test_only_directory_fields_logged(self):
        output=io.StringIO()
        responses=[{'defaultProjectDirUri':'file:///data/home/Documents','token':'secret'},
                   {'homeDirUri':'file:///data/home','token':'secret'}]
        with patch.object(native,'load',return_value={'token':'secret'}), patch.object(native,'rpc',side_effect=responses), redirect_stdout(output):
            signin.project_directory_diagnostics()
        self.assertIn('file:///data/home/Documents',output.getvalue())
        self.assertIn('GetLocalUserInfo',output.getvalue())
        self.assertNotIn('secret',output.getvalue())

    def test_rpc_errors_do_not_leak_or_stop_next_probe(self):
        output=io.StringIO()
        with patch.object(native,'load',return_value={}), patch.object(native,'rpc',side_effect=[native.NativeError('secret'),{'homeDirUri':'file:///data/home'}]), redirect_stdout(output):
            signin.project_directory_diagnostics()
        self.assertIn('GetDefaultProjectDir unavailable',output.getvalue())
        self.assertIn('file:///data/home',output.getvalue())
        self.assertNotIn('secret',output.getvalue())
