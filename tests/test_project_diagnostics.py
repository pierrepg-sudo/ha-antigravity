import io
import json
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

    def test_diagnostics_use_real_rpc_wrapper(self):
        from unittest.mock import MagicMock
        output = io.StringIO()
        connection = {'host': '127.0.0.1', 'port': 1234, 'token': 'secret'}
        client = MagicMock()
        response = client.getresponse.return_value
        response.status = 200
        response.read.side_effect = [json.dumps({'defaultProjectDirUri': 'file:///data/home/Documents'}).encode(),
                                     json.dumps({'homeDirUri': 'file:///data/home'}).encode()]
        with patch.object(native, 'load', return_value=connection), patch.object(native, 'validate'), patch.object(native.http.client, 'HTTPConnection', return_value=client), redirect_stdout(output):
            signin.project_directory_diagnostics()
        self.assertEqual([call.args[1] for call in client.request.call_args_list],
                         [native.SERVICE + 'GetDefaultProjectDir', native.SERVICE + 'GetLocalUserInfo'])
        self.assertIn('file:///data/home/Documents', output.getvalue())
        self.assertNotIn('unavailable', output.getvalue())
        self.assertNotIn('secret', output.getvalue())

    def test_unknown_rpc_remains_rejected(self):
        with self.assertRaises(native.NativeError):
            native.rpc({}, 'UnknownOperation', {})
