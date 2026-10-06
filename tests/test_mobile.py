import base64
import importlib.util
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.request import Request, urlopen
from urllib.error import HTTPError

spec = importlib.util.spec_from_file_location('helper', Path(__file__).parents[1] / 'antigravity/signin.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

class MobileTests(unittest.TestCase):
    def test_keys_and_literal_paste(self):
        with patch.object(m, 'tmux') as run:
            for key in m.KEYS:
                m.send_input({'key': key})
                self.assertEqual(run.call_args.args, ('send-keys', '-t', 'antigravity:0.0', key))
            run.reset_mock()
            text = 'printf "$(echo literal)"\nsecond line'
            m.send_input({'text': text})
            self.assertEqual(run.call_args_list[0].kwargs['input'], text.encode())
            self.assertIn('-p', run.call_args_list[1].args)
            self.assertFalse(any('Enter' in c.args for c in run.call_args_list))
            for bad in [{'key':'C-c'}, {'text':'\x1b[31m'}, {'text':''}, {'text':'x'*16385}]:
                with self.assertRaises(ValueError): m.send_input(bad)

    def test_c_upload_bytes_and_isolation(self):
        with tempfile.TemporaryDirectory() as d, patch.object(m, 'WORKSPACE', Path(d)):
            content = b'#include <stdio.h>\nint main(void) { return 0; }\n'
            payload = {'name':'example.c','data':base64.b64encode(content).decode()}
            a = Path(m.upload_file(payload)['path'])
            b = Path(m.upload_file(payload)['path'])
            self.assertEqual(a.read_bytes(), content)
            self.assertNotEqual(a,b)
            self.assertEqual(a.suffix,'.c')
            for name in ['../escape.c','/absolute.c','a\\b.c']:
                with self.assertRaises(ValueError): m.upload_file(dict(payload,name=name))
            with self.assertRaises(ValueError):m.upload_file(dict(payload,data=base64.b64encode(b'\0binary').decode()))
            with self.assertRaises(ValueError):m.upload_file(dict(payload,data=base64.b64encode(b'x'*(2097153)).decode()))

    def test_http_controls_and_csrf(self):
        server=m.ThreadingHTTPServer(('127.0.0.1',0),m.Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        base='http://127.0.0.1:'+str(server.server_port)
        try:
            with urlopen(base+'/controls') as r:
                body=r.read().decode()
                self.assertIn(m.CSRF,body)
                self.assertIn('Shift+Tab',body)
                self.assertEqual(r.headers['Cache-Control'],'no-store')
            data=json.dumps({'key':'Tab'}).encode()
            with self.assertRaises(HTTPError) as ctx:
                urlopen(Request(base+'/input',data=data,headers={'Content-Type':'application/json'}))
            self.assertEqual(ctx.exception.code,403)
            with patch.object(m,'tmux') as run:
                with urlopen(Request(base+'/input',data=data,headers={'Content-Type':'application/json','X-Antigravity-CSRF':m.CSRF})) as r:
                    self.assertTrue(json.load(r)['ok'])
                run.assert_called_once_with('send-keys','-t','antigravity:0.0','Tab')
        finally: server.shutdown();server.server_close();thread.join()

if __name__=='__main__':unittest.main()
