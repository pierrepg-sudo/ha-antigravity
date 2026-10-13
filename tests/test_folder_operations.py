import io
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import zipfile
import workspace_files as files
import file_server


class FolderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)/'outputs'; self.root.mkdir()
        self.token = files.ACTIVE_ROOT.set(str(self.root))
        (self.root/'project/empty').mkdir(parents=True)
        (self.root/'project/sub').mkdir()
        (self.root/'project/sub/code.txt').write_text('hello')
        (self.root/'project/.hidden').write_text('hidden')

    def tearDown(self):
        files.ACTIVE_ROOT.reset(self.token)
        self.temp.cleanup()

    def transfer(self, action='copy', source='project', path='', name='duplicate'):
        return files.transfer(dict(action=action,source=source,path=path,name=name),str(self.root))

    def test_zip_nested_empty_and_hidden_files(self):
        archive,name=files.folder_zip('project')
        with archive, zipfile.ZipFile(archive) as z:
            self.assertEqual(name,'project.zip')
            self.assertEqual(z.read('project/sub/code.txt'),b'hello')
            self.assertIn('project/empty/',z.namelist())
            self.assertEqual(z.read('project/.hidden'),b'hidden')
        archive,name=files.folder_zip('')
        with archive, zipfile.ZipFile(archive) as z:
            self.assertEqual(name,'outputs.zip')
            self.assertIn('outputs/project/empty/',z.namelist())

    def test_copy_move_and_collision_preserve_source(self):
        self.transfer()
        self.assertEqual((self.root/'duplicate/sub/code.txt').read_text(),'hello')
        self.assertTrue((self.root/'duplicate/empty').is_dir())
        with self.assertRaises(FileExistsError):self.transfer()
        self.assertTrue((self.root/'project').is_dir())
        self.transfer('move',name='moved')
        self.assertFalse((self.root/'project').exists())
        self.assertEqual((self.root/'moved/sub/code.txt').read_text(),'hello')
        with self.assertRaises(FileExistsError):self.transfer('move','moved',name='duplicate')
        self.assertTrue((self.root/'moved').exists())
        self.assertFalse(list(self.root.glob('.copy-*')))

    def test_file_copy_and_move(self):
        self.transfer(source='project/.hidden',name='file')
        self.transfer('move',source='file',name='renamed')
        self.assertEqual((self.root/'renamed').read_text(),'hidden')
        self.assertFalse((self.root/'file').exists())

    def test_recursive_destinations_and_traversal_rejected(self):
        for action in ('copy','move'):
            with self.assertRaises(files.FileOperationError):self.transfer(action,path='project/sub')
            with self.assertRaises(ValueError):self.transfer(action,source='../outputs/project')
            with self.assertRaises(ValueError):self.transfer(action,name='../bad')
        # Legacy root can alias the ancestor of Outputs; compare inode ancestry.
        with self.assertRaises(files.FileOperationError):
            files.transfer({'action':'copy','source':'outputs','path':'','name':'bad'},self.temp.name)
        self.assertFalse((self.root/'bad').exists())

    def test_links_special_files_limits_and_cleanup(self):
        outside=Path(self.temp.name)/'secret';outside.write_text('private')
        (self.root/'project/link').symlink_to(outside)
        for operation in (lambda:files.folder_zip('project'),self.transfer):
            with self.assertRaises((ValueError,OSError)):operation()
        (self.root/'project/link').unlink()
        os.mkfifo(self.root/'project/pipe')
        for operation in (lambda:files.folder_zip('project'),self.transfer):
            with self.assertRaises(ValueError):operation()
        (self.root/'project/pipe').unlink()
        for constant in ('TREE_LIMIT','ENTRY_LIMIT','DEPTH_LIMIT'):
            with patch.object(files,constant,1):
                for operation in (lambda:files.folder_zip('project'),self.transfer):
                    with self.assertRaises(files.FileOperationError):operation()
        self.assertFalse((self.root/'duplicate').exists())
        self.assertFalse(list(self.root.glob('.copy-*')))
        self.assertEqual(outside.read_text(),'private')

    def test_copy_between_locations_uses_destination_permissions(self):
        inputs=Path(self.temp.name)/'inputs';inputs.mkdir()
        (inputs/'original').write_text('input')
        (inputs/'original').chmod(0o750)
        files.transfer({'action':'copy','source':'original','path':'','name':'copy'},str(inputs))
        self.assertEqual((self.root/'copy').read_text(),'input')
        self.assertEqual((inputs/'original').read_text(),'input')
        self.assertEqual((self.root/'copy').stat().st_mode & 0o110, 0o110)

    def test_source_change_aborts_copy(self):
        original=files.transfer_bytes
        def change(source,target,budget):
            original(source,target,budget)
            (self.root/'project/new').write_text('new')
        with patch.object(files,'transfer_bytes',side_effect=change):
            with self.assertRaises(files.FileOperationError):self.transfer()
        self.assertFalse((self.root/'duplicate').exists())
        self.assertFalse(list(self.root.glob('.copy-*')))

    def test_http_zip_copy_and_move_area_rules(self):
        areas={'outputs':str(self.root),'inputs':str(Path(self.temp.name)/'inputs'),'legacy':str(Path(self.temp.name)/'legacy')}
        for key in ('inputs','legacy'):Path(areas[key]).mkdir()
        (Path(areas['legacy'])/'old.txt').write_text('old')
        server=file_server.ThreadingHTTPServer(('127.0.0.1',0),file_server.Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        base='http://127.0.0.1:'+str(server.server_port)
        headers={'X-Antigravity-File-Key':'test','X-Antigravity-CSRF':file_server.CSRF,'Content-Type':'application/json'}
        try:
            with patch.dict(file_server.AREAS,areas),patch.object(file_server,'PROXY_KEY','test'):
                with urlopen(Request(base+'/folder-download?area=outputs&path=project',headers=headers)) as r:
                    self.assertEqual(r.headers['Content-Type'],'application/zip')
                    with zipfile.ZipFile(io.BytesIO(r.read())) as z:self.assertIn('project/empty/',z.namelist())
                payload={'action':'copy','sourceArea':'legacy','source':'old.txt','path':'','name':'new.txt'}
                with urlopen(Request(base+'/file-action?area=outputs',data=json.dumps(payload).encode(),headers=headers)) as r:
                    self.assertTrue(json.load(r)['ok'])
                self.assertEqual((self.root/'new.txt').read_text(),'old')
                for area,body,status in [('outputs',dict(payload,action='move'),400),('legacy',payload,403),('inputs',dict(payload,action='move',sourceArea='outputs',source='new.txt'),400)]:
                    with self.assertRaises(HTTPError) as error:
                        urlopen(Request(base+'/file-action?area='+area,data=json.dumps(body).encode(),headers=headers))
                    self.assertEqual(error.exception.code,status)
                with self.assertRaises(HTTPError) as error:
                    urlopen(Request(base+'/file-action?area=outputs',data=json.dumps(payload).encode(),headers={'Content-Type':'application/json','X-Antigravity-File-Key':'test'}))
                self.assertEqual(error.exception.code,403)
                deletion={'action':'delete','name':'project','path':'','kind':'folder','confirm':True}
                with self.assertRaises(HTTPError) as error:
                    urlopen(Request(base+'/file-action?area=legacy',data=json.dumps(deletion).encode(),headers=headers))
                self.assertEqual(error.exception.code,403)
                with self.assertRaises(HTTPError) as error:
                    urlopen(Request(base+'/file-action?area=outputs',data=json.dumps(dict(deletion,confirm=False)).encode(),headers=headers))
                self.assertEqual(error.exception.code,400)
                self.assertTrue((self.root/'project').exists())
                with urlopen(Request(base+'/file-action?area=outputs',data=json.dumps(deletion).encode(),headers=headers)) as response:
                    self.assertTrue(json.load(response)['ok'])
                self.assertFalse((self.root/'project').exists())
        finally:
            server.shutdown();server.server_close();thread.join()

    def test_recursive_delete_requires_folder_confirmation_and_preserves_link_targets(self):
        outside=Path(self.temp.name)/'outside';outside.mkdir();(outside/'secret').write_text('keep')
        (self.root/'project/link').symlink_to(outside,target_is_directory=True)
        payload={'action':'delete','path':'','name':'project','kind':'folder'}
        with self.assertRaises(ValueError):files.change(payload)
        with self.assertRaises(ValueError):files.change({'action':'delete','name':'project','confirm':True})
        self.assertTrue((self.root/'project/sub/code.txt').exists())
        files.change(dict(payload,confirm=True))
        self.assertFalse((self.root/'project').exists())
        self.assertEqual((outside/'secret').read_text(),'keep')

    def test_delete_blocks_root_traversal_and_selected_symlink(self):
        outside=Path(self.temp.name)/'outside';outside.mkdir()
        (self.root/'link').symlink_to(outside,target_is_directory=True)
        for name in ('','..','/','project/..','link'):
            with self.assertRaises((ValueError,OSError)):
                files.change({'action':'delete','path':'','name':name,'kind':'folder','confirm':True})
        self.assertTrue(outside.is_dir())
        self.assertTrue(self.root.is_dir())
        with self.assertRaises(ValueError):
            files.change({'action':'delete','name':'.hidden','path':'project','kind':'folder','confirm':True})

    def test_delete_failure_reports_possible_partial_deletion(self):
        with patch('shutil.rmtree',side_effect=PermissionError) as remove:
            remove.avoids_symlink_attacks=True
            with self.assertRaisesRegex(files.FileOperationError,'Some contents may have been removed'):
                files.change({'action':'delete','name':'project','kind':'folder','confirm':True})
