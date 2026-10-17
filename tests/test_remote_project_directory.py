import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import prepare_storage
import conversation_management as manager


class RemoteDirectoryTests(unittest.TestCase):
    def test_native_documents_alias_targets_outputs(self):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp);(base/'home').mkdir();(base/'workspace/outputs').mkdir(parents=True)
            prepare_storage.remote_project_directory(base)
            prepare_storage.remote_project_directory(base)
            alias=base/'home/Documents';(alias/'Example').mkdir()
            self.assertTrue((base/'workspace/outputs/Example').is_dir())
            with patch.object(manager,'OUTPUTS',base/'workspace/outputs'):
                record={'projectResources':{'resources':[{'folderUri':(alias/'Example').as_uri()}]}}
                self.assertEqual(manager.resource_folder(record),'Example')

    def test_existing_documents_preserved(self):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp);folder=base/'home/Documents';folder.mkdir(parents=True)
            (folder/'keep').write_text('keep')
            prepare_storage.remote_project_directory(base)
            self.assertFalse(folder.is_symlink())
            self.assertEqual((folder/'keep').read_text(),'keep')
