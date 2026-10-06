import base64
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).parents[1] / 'antigravity'))
import workspace_files as files

class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / 'workspace'
        self.root.mkdir()
        self.patch = patch.object(files, 'ROOT', str(self.root)); self.patch.start()
    def tearDown(self):
        self.patch.stop(); self.temp.cleanup()
    def test_roundtrip_and_no_overwrite(self):
        files.change({'action':'mkdir','name':'source','path':''})
        data=b'int main(void) { return 0; }\n'
        payload={'action':'upload','path':'source','name':'hello.c','data':base64.b64encode(data).decode()}
        files.change(payload)
        self.assertEqual(files.read_file('source/hello.c')[0],data)
        self.assertEqual(files.read_file('source/hello.c',True)['text'],data.decode())
        self.assertEqual(files.listing('source')['entries'][0]['name'],'hello.c')
        with self.assertRaises(FileExistsError):files.change(payload)
        self.assertEqual((self.root/'source/hello.c').read_bytes(),data)
        self.assertFalse(list((self.root/'source').glob('.upload-*')))
    def test_traversal_and_symlinks(self):
        outside=Path(self.temp.name)/'private';outside.mkdir();(outside/'secret').write_text('private')
        (self.root/'link').symlink_to(outside,target_is_directory=True)
        (self.root/'filelink').symlink_to(outside/'secret')
        for path in ['../private','/etc','source/../..','link']:
            with self.assertRaises((ValueError,OSError)):files.listing(path)
        with self.assertRaises(OSError):files.read_file('filelink')
        with self.assertRaises(OSError):files.change({'action':'mkdir','path':'link','name':'blocked'})
        with self.assertRaises(ValueError):files.change({'action':'mkdir','path':'','name':'../escape'})
    def test_binary_and_preview_limits(self):
        (self.root/'data.bin').write_bytes(b'\0\1\2')
        self.assertEqual(files.read_file('data.bin')[0],b'\0\1\2')
        with self.assertRaises(ValueError):files.read_file('data.bin',True)
        (self.root/'large.txt').write_bytes(b'a'*(256*1024+1))
        self.assertTrue(files.read_file('large.txt',True)['truncated'])
        with patch.object(files,'UPLOAD_LIMIT',2):
            with self.assertRaises(ValueError):files.change({'action':'upload','path':'','name':'large','data':'YWJj'})

if __name__=='__main__':unittest.main()
