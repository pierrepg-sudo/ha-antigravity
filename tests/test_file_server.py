import base64
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from test_mobile import m
import file_server


class FileServerTests(unittest.TestCase):
    def test_project_sections_and_server_side_folder_guards(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            for name in ('Active','Archived','Loose'):
                (root/name).mkdir();(root/name/'keep.txt').write_text('preserve')
            projects={'Active':{'id':'p1','name':'Active','folder':'Active','archived':False},
                      'Archived':{'id':'p2','name':'Archived','folder':'Archived','archived':True}}
            server=file_server.ThreadingHTTPServer(('127.0.0.1',0),file_server.Handler)
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            base='http://127.0.0.1:'+str(server.server_port)
            headers={'X-Antigravity-File-Key':'test','X-Antigravity-CSRF':file_server.CSRF,'Content-Type':'application/json'}
            try:
                with patch.dict(file_server.AREAS,{'outputs':folder,'archived':folder}),patch.object(file_server,'PROXY_KEY','test'),patch.object(file_server,'project_folders',return_value=projects) as lookup:
                    def listing(area=''):
                        with urlopen(Request(base+'/file-list'+area,headers=headers)) as response:return json.load(response)['entries']
                    self.assertEqual({e['name'] for e in listing()},{'Active','Loose'})
                    self.assertEqual({e['name'] for e in listing('?area=archived')},{'Archived'})
                    projects['Active']['archived']=True
                    self.assertEqual({e['name'] for e in listing('?area=archived')},{'Active','Archived'})
                    projects['Active']['archived']=False
                    for payload in [
                        {'action':'delete','name':'Active','kind':'folder','confirm':True},
                        {'action':'rename','name':'Active','newName':'Other'},
                        {'action':'move','sourceArea':'outputs','source':'Active','path':'Loose','name':'Active'}]:
                        with self.assertRaises(HTTPError) as denied:
                            urlopen(Request(base+'/file-action?area=outputs',data=json.dumps(payload).encode(),headers=headers))
                        self.assertEqual(denied.exception.code,400)
                        self.assertTrue((root/'Active/keep.txt').exists())
                    lookup.side_effect=file_server.workspace_files.FileOperationError('Unavailable')
                    with self.assertRaises(HTTPError):
                        urlopen(Request(base+'/file-action?area=outputs',data=json.dumps({'action':'delete','name':'Loose','kind':'folder','confirm':True}).encode(),headers=headers))
                    self.assertTrue((root/'Loose/keep.txt').exists())
            finally:
                server.shutdown();server.server_close();thread.join()

    def test_areas_csrf_upload_and_removed_area(self):
        with tempfile.TemporaryDirectory() as folder:
            areas = {key: str(Path(folder) / key) for key in ('inputs', 'outputs')}
            for root in areas.values():
                Path(root).mkdir()
            server = file_server.ThreadingHTTPServer(('127.0.0.1', 0), file_server.Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True);thread.start()
            base = 'http://127.0.0.1:' + str(server.server_port)
            body = json.dumps({'action': 'upload', 'name': 'hello.c', 'data': base64.b64encode(b'hello').decode()}).encode()
            headers = {'Content-Type': 'application/json', 'X-Antigravity-CSRF': file_server.CSRF, 'X-Antigravity-File-Key': 'test-proxy'}
            try:
                with patch.dict(file_server.AREAS, areas), patch.object(file_server, 'PROXY_KEY', 'test-proxy'):
                    with self.assertRaises(HTTPError) as denied:
                        urlopen(Request(base + '/file-action', data=body, headers={'Content-Type': 'application/json'}))
                    self.assertEqual(denied.exception.code, 403)
                    with self.assertRaises(HTTPError) as denied:
                        urlopen(base + '/files')
                    self.assertEqual(denied.exception.code, 403)
                    with self.assertRaises(HTTPError) as denied:
                        urlopen(Request(base + '/file-action', data=body, headers={'X-Antigravity-File-Key': 'test-proxy', 'Content-Type': 'application/json'}))
                    self.assertEqual(denied.exception.code, 403)
                    with urlopen(Request(base + '/file-action?area=inputs', data=body, headers=headers)) as r:
                        self.assertTrue(json.load(r)['ok'])
                    self.assertEqual((Path(areas['inputs']) / 'hello.c').read_text(), 'hello')
                    self.assertFalse((Path(areas['outputs']) / 'hello.c').exists())
                    with urlopen(Request(base + '/file-list?area=inputs', headers=headers)) as r:
                        self.assertEqual(json.load(r)['root'], areas['inputs'])
                    with urlopen(Request(base + '/file-download?area=inputs&path=hello.c', headers=headers)) as r:
                        self.assertEqual(r.read(), b'hello')
                        self.assertIn('attachment', r.headers['Content-Disposition'])
                    for query, expected in (('area=legacy', 400), ('area=../../home', 400), ('area=inputs&area=outputs', 400)):
                        with self.assertRaises(HTTPError) as denied:
                            urlopen(Request(base + '/file-action?' + query, data=body, headers=headers))
                        self.assertEqual(denied.exception.code, expected)
                    with self.assertRaises(HTTPError) as removed:
                        urlopen(Request(base + '/file-list?area=legacy', headers=headers))
                    self.assertEqual(removed.exception.code, 400)
            finally:
                server.shutdown();server.server_close();thread.join()

    def test_file_routes_fully_removed_from_terminal_service(self):
        server = m.ThreadingHTTPServer(('127.0.0.1', 0), m.Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True);thread.start()
        try:
            for route in ('/files', '/file-list', '/file-download'):
                with self.assertRaises(HTTPError) as error:
                    urlopen('http://127.0.0.1:' + str(server.server_port) + route)
                self.assertEqual(error.exception.code, 404)
        finally:
            server.shutdown();server.server_close();thread.join()
