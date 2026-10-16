import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock
import conversation_management as manager
import conversation_history as history
import conversation_models as models
import native_connection as native
import workspace_files as files
import worker_mcp


class ManagementTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        for target,key,value in [(native,'STATE',self.root/'connection.json'),(manager,'OUTPUTS',self.root),(files,'ROOT',str(self.root))]:
            p=patch.object(target,key,value);p.start();self.addCleanup(p.stop)

    def test_folder_created_and_collision_never_adopted(self):
        with patch.object(manager,'project',return_value={'id':'p1','name':'Project One'}):
            folder=manager.ensure_folder({},'p1')
            self.assertEqual(folder,str(self.root/'Project One'))
            self.assertTrue(Path(folder).is_dir())
            self.assertEqual(manager.ensure_folder({},'p1'),folder)
            with self.assertRaises(native.NativeError):manager.ensure_folder({},'p2')

    def test_rejects_unsafe_names(self):
        for name in ['../outside','a/b','a\\b','.hidden','a\ncommand',' x','',None]:
            with self.assertRaises(native.NativeError):manager.valid_name(name)

    def test_file_and_folder_rename_without_overwrite(self):
        (self.root/'old').write_text('preserve')
        files.change({'action':'rename','path':'','name':'old','newName':'new'})
        self.assertEqual((self.root/'new').read_text(),'preserve')
        (self.root/'folder').mkdir()
        files.change({'action':'rename','name':'folder','newName':'renamed'})
        self.assertTrue((self.root/'renamed').is_dir())
        with self.assertRaises(FileExistsError):files.change({'action':'rename','name':'new','newName':'renamed'})
        with self.assertRaises(ValueError):files.change({'action':'rename','name':'new','newName':'../escape'})
        (self.root/'link').symlink_to('new')
        with self.assertRaises(ValueError):files.change({'action':'rename','name':'link','newName':'other'})

    def test_management_requires_fresh_confirmation(self):
        with patch.object(native,'load',return_value={}),patch.object(manager,'selection',return_value=({},[],'new')),patch.object(native,'rpc') as rpc:
            with self.assertRaises(native.NativeError):manager.action({'confirm':True,'revision':'old','action':'delete'})
            rpc.assert_not_called()

    def test_model_preferences_are_per_conversation(self):
        models.remember('one','model-a');models.remember('two','model-b')
        self.assertEqual(models.preferences(),{'one':'model-a','two':'model-b'})
        models.remember('one','')
        self.assertEqual(models.preferences(),{'two':'model-b'})

    def test_model_catalog_uses_cli_slugs(self):
        with patch.object(models,'_catalog',(0,[])),patch.object(models.subprocess,'run',return_value=Mock(returncode=0,stdout='gemini-example-high    Gemini Example (High)\nclaude-example    Claude Example\n')):
            result=models.catalog()
            self.assertEqual([r['id'] for r in result],['gemini-example-high','claude-example'])

    def test_reset_model_requires_confirmation_and_preserves_other_preferences(self):
        models.remember('one','model-a');models.remember('two','model-b')
        with patch.object(native,'load',return_value={}),patch.object(manager,'selection',return_value=(None,[],'current')):
            request={'id':'one','action':'reset-model','revision':'current'}
            with self.assertRaises(native.NativeError):manager.action(request)
            self.assertEqual(models.preferences()['one'],'model-a')
            manager.action(dict(request,confirm=True))
            self.assertEqual(models.preferences(),{'two':'model-b'})

    def test_worker_scope_is_per_process_environment(self):
        with patch.dict(os.environ,{'HA_PROJECT_OUTPUT':'/data/workspace/outputs/Project One'}):
            self.assertEqual(worker_mcp.project_output(),'/data/workspace/outputs/Project One')
            self.assertIn('Project One',worker_mcp.dispatch({'method':'initialize'})['instructions'])
        with patch.dict(os.environ,{'HA_PROJECT_OUTPUT':'/data/workspace/outputs/../private'}):
            with self.assertRaises(ValueError):worker_mcp.project_output()
