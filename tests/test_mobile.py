import sys
sys.path.insert(0, str(__import__("pathlib").Path(__file__).parents[1] / "antigravity"))
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
    def test_navigation_only(self):
        with patch.object(m, 'tmux') as run:
            for key in m.KEYS:
                m.send_input({'key': key})
                self.assertEqual(run.call_args.args, ('send-keys', '-t', 'antigravity:0.0', key))
            with self.assertRaises(ValueError): m.send_input({'text': 'removed'})
            with self.assertRaises(ValueError): m.send_input({'key': 'C-c'})

    def test_http_controls_and_csrf(self):
        server=m.ThreadingHTTPServer(('127.0.0.1',0),m.Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        base='http://127.0.0.1:'+str(server.server_port)
        try:
            with urlopen(base+'/controls') as r:
                body=r.read().decode()
                self.assertIn(m.CSRF,body)
                self.assertIn('Shift+Tab',body)
                self.assertIn('Delete conversation (F4)',body)
                self.assertIn('/resume',body)
                self.assertIn('id="pasteDialog"',body)
                self.assertIn('id="paste"',body)
                self.assertNotIn('type="file"',body)
                self.assertEqual(r.headers['Cache-Control'],'no-store')
            with self.assertRaises(HTTPError) as gone:
                urlopen(Request(base+'/upload',data=b'{}'))
            self.assertEqual(gone.exception.code,404)
            with urlopen(base+'/conversations') as r:
                menu=r.read().decode()
                self.assertIn('Delete conversation?',menu)
                self.assertIn(m.CSRF,menu)
            with patch.object(m.conversation_history,'listing',return_value={'items':[]}) as listing:
                with urlopen(base+'/conversation-list') as r:
                    self.assertEqual(json.load(r)['items'],[])
                    self.assertEqual(r.headers['Cache-Control'],'no-store')
                listing.assert_called_once()
            deletion=json.dumps({'id':'12345678-1234-1234-1234-123456789012','revision':'example','confirm':True}).encode()
            with patch.object(m.conversation_history,'delete',return_value={'ok':True}) as delete:
                with self.assertRaises(HTTPError) as forbidden:
                    urlopen(Request(base+'/conversation-delete',data=deletion,headers={'Content-Type':'application/json'}))
                self.assertEqual(forbidden.exception.code,403);delete.assert_not_called()
                with urlopen(Request(base+'/conversation-delete',data=deletion,headers={'Content-Type':'application/json','X-Antigravity-CSRF':m.CSRF})) as response:
                    self.assertTrue(json.load(response)['ok'])
                delete.assert_called_once_with(json.loads(deletion))
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
