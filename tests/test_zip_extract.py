import stat
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch
import workspace_files as files


class ExtractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.token = files.ACTIVE_ROOT.set(str(self.root))

    def tearDown(self):
        files.ACTIVE_ROOT.reset(self.token)
        self.temp.cleanup()

    def archive(self, entries):
        with zipfile.ZipFile(self.root / 'project.zip', 'w') as archive:
            for name, data in entries:
                archive.writestr(name, data)

    def extract(self):
        return files.extract_zip({'path': '', 'name': 'project.zip'})

    def test_hidden_empty_nested_and_original_preserved(self):
        self.archive([('.deps/package/file', b'content'), ('.env', b'hidden'), ('empty/', b'')])
        original = (self.root / 'project.zip').read_bytes()
        self.extract()
        self.assertEqual((self.root / 'project/.deps/package/file').read_bytes(), b'content')
        self.assertEqual((self.root / 'project/.env').read_bytes(), b'hidden')
        self.assertTrue((self.root / 'project/empty').is_dir())
        self.assertEqual((self.root / 'project.zip').read_bytes(), original)
        with self.assertRaises(FileExistsError):
            self.extract()
        self.assertFalse(list(self.root.glob('.extract-*')))

    def test_unsafe_members_leave_no_partial_output(self):
        link = zipfile.ZipInfo('link')
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        for name in ['../escape', '/absolute', 'C:/absolute', 'bad\\path', 'x/../../escape', link]:
            with self.subTest(name=name):
                self.archive([('good', b'ok'), (name, b'bad')])
                with self.assertRaises((ValueError, OSError)):
                    self.extract()
                self.assertEqual(sorted(p.name for p in self.root.iterdir()), ['project.zip'])

    def test_corruption_and_limits_cleanup(self):
        (self.root / 'project.zip').write_bytes(b'not a zip')
        with self.assertRaises(files.FileOperationError):
            self.extract()
        self.archive([('nested/file', b'1234')])
        for setting, limit in [('TREE_LIMIT', 3), ('ENTRY_LIMIT', 1), ('DEPTH_LIMIT', 1)]:
            with patch.object(files, setting, limit), self.assertRaises(files.FileOperationError):
                self.extract()
            self.assertFalse((self.root / 'project').exists())
            self.assertFalse(list(self.root.glob('.extract-*')))
        self.archive([('file', b'1234')])
        data = (self.root / 'project.zip').read_bytes().replace(b'1234', b'1235')
        (self.root / 'project.zip').write_bytes(data)
        with self.assertRaises(files.FileOperationError):
            self.extract()
        self.assertFalse((self.root / 'project').exists())
