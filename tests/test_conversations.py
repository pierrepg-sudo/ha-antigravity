import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parents[1]/'antigravity'))
import json
import os
import tempfile
import threading
import unittest
from unittest.mock import patch
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import conversation_history as h
import native_connection as n

CID='12345678-1234-1234-1234-123456789012'
OTHER='87654321-4321-4321-4321-210987654321'

class NativeTests(unittest.TestCase):
    def setUp(self):
        self.rows={CID:{'summary':'Disposable','status':'CASCADE_RUN_STATUS_IDLE','stepCount':1,'lastModifiedTime':'2026-10-07'},OTHER:{'summary':'Keep','status':'CASCADE_RUN_STATUS_RUNNING'}}
        self.calls=[];self.refuse=False;self.keep=False;self.redirect=False
        test=self
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                payload=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                test.calls.append((self.path,payload))
                self.assertions=None
                if test.redirect:
                    self.send_response(302);self.send_header('Location','http://example.com');self.end_headers();return
                if self.headers.get('x-codeium-csrf-token')!='private-test-token':
                    self.send_response(401);self.end_headers();return
                if self.path==n.SERVICE+n.LIST:
                    result={'trajectorySummaries':test.rows}
                elif self.path==n.SERVICE+n.DELETE:
                    if test.refuse:
                        self.send_response(404);self.end_headers();return
                    if not test.keep:test.rows.pop(payload['cascadeId'],None)
                    result={}
                else:self.send_response(404);self.end_headers();return
                body=json.dumps(result).encode();self.send_response(200);self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
            def log_message(self,*a):pass
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.connection={'host':'127.0.0.1','port':self.server.server_port,'pid':42,'started':'123','token':'private-test-token'}
        self.process=patch.object(n,'process',return_value=(1,'123','agy'));self.process.start()
        self.loader=patch.object(n,'load',return_value=self.connection);self.loader.start()
    def tearDown(self):
        self.loader.stop();self.process.stop();self.server.shutdown();self.server.server_close();self.thread.join()
    def payload(self):
        item=next(i for i in h.listing()['items'] if i['id']==CID)
        return {'id':CID,'revision':item['revision'],'confirm':True}
    def test_direct_delete_exact_id_and_verified_absence(self):
        result=h.delete(self.payload());self.assertTrue(result['ok']);self.assertNotIn(CID,self.rows);self.assertIn(OTHER,self.rows)
        mutations=[p for path,p in self.calls if path.endswith(n.DELETE)]
        self.assertEqual(mutations,[{'cascadeId':CID}]);self.assertTrue(self.calls[-1][0].endswith(n.LIST))
        self.assertNotIn('private-test-token',json.dumps(h.listing()))
    def test_running_and_stale_selection_make_no_delete_request(self):
        payload=self.payload();self.rows[CID]['status']='CASCADE_RUN_STATUS_RUNNING'
        with self.assertRaises(n.NativeError):h.delete(payload)
        self.rows[CID]['status']='CASCADE_RUN_STATUS_IDLE';self.rows[CID]['summary']='Renamed'
        with self.assertRaises(n.NativeError):h.delete(payload)
        self.assertFalse(any(path.endswith(n.DELETE) for path,_ in self.calls))
    def test_unknown_state_blocked(self):
        self.rows[CID].pop('status')
        with self.assertRaises(n.NativeError):h.delete(self.payload())
        self.assertFalse(any(path.endswith(n.DELETE) for path,_ in self.calls))
    def test_missing_confirmation_and_invalid_id_rejected(self):
        for payload in ({'id':CID,'revision':'x','confirm':False},{'id':'../x','revision':'x','confirm':True}):
            with self.assertRaises(n.NativeError):h.delete(payload)
        self.assertEqual(self.calls,[])
    def test_404_delete_is_not_retried(self):
        payload=self.payload();self.refuse=True
        with self.assertRaises(n.NativeError):h.delete(payload)
        self.assertEqual(sum(path.endswith(n.DELETE) for path,_ in self.calls),1)
        self.assertIn(CID,self.rows)
    def test_still_listed_not_reported_as_success(self):
        payload=self.payload();self.keep=True
        with self.assertRaisesRegex(n.NativeError,'still listed'):h.delete(payload)
    def test_process_restart_prevents_request(self):
        with patch.object(n,'process',return_value=(1,'999','agy')):
            with self.assertRaises(n.NativeError):h.listing()
        self.assertEqual(self.calls,[])
    def test_nonlocal_and_redirect_refused(self):
        connection=dict(self.connection,host='example.com')
        with self.assertRaises(n.NativeError):n.summaries(connection)
        self.assertEqual(self.calls,[])
        self.redirect=True
        with self.assertRaises(n.NativeError):n.summaries(self.connection)
        self.assertEqual(len(self.calls),1)
    def test_bad_auth_redacted(self):
        with self.assertRaises(n.NativeError) as caught:n.summaries(dict(self.connection,token='secret-wrong-token'))
        self.assertNotIn('secret-wrong-token',str(caught.exception))
        self.assertIn('401',str(caught.exception))
    def test_pairing_only_reads_and_writes_private_connection(self):
        with tempfile.TemporaryDirectory() as directory:
            state=Path(directory)/'connection.json'
            with patch.object(n,'STATE',state),patch.object(n,'cli_parent',return_value=(42,'123')),patch.dict(os.environ,{'ANTIGRAVITY_LS_ADDRESS':f'localhost:{self.server.server_port}','ANTIGRAVITY_CSRF_TOKEN':'private-test-token'}),patch('builtins.print') as output:
                n.pair()
                self.assertEqual(state.stat().st_mode&0o777,0o600)
                self.assertNotIn('private-test-token',str(output.call_args))
                self.loader.stop()
                try:self.assertEqual(n.load()['pid'],42)
                finally:self.loader.start()
            self.assertTrue(all(path.endswith(n.LIST) for path,_ in self.calls))
