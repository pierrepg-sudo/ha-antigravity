import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import workspace_files as files


class ProjectRulesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / 'project').mkdir()
        self.token = files.ACTIVE_ROOT.set(str(self.root))

    def tearDown(self):
        files.ACTIVE_ROOT.reset(self.token)
        self.temp.cleanup()

    def rules(self, action='rules-read', **kwargs):
        return files.project_rules(dict(action=action, path='project', **kwargs))

    def test_create_edit_delete_and_conflict(self):
        state = self.rules()
        self.assertFalse(state['exists'])
        state = self.rules('rules-save', revision=state['revision'], text='# Rules\nRépondre en français.\n')
        self.assertEqual(self.rules()['text'], '# Rules\nRépondre en français.\n')
        target = self.root / 'project/AGENTS.md'
        target.write_text('External edit')
        for action in ('rules-save', 'rules-delete'):
            with self.assertRaisesRegex(files.FileOperationError, 'changed since'):
                self.rules(action, revision=state['revision'], text='Lost update')
        self.assertEqual(target.read_text(), 'External edit')
        state = self.rules('rules-save', revision=self.rules()['revision'], text='Updated')
        self.assertEqual(target.read_text(), 'Updated')
        self.rules('rules-delete', revision=state['revision'])
        self.assertFalse(target.exists())
        self.assertFalse(list((self.root / 'project').glob('.rules-*')))

    def test_symlink_binary_and_limits(self):
        target = self.root / 'project/AGENTS.md'
        outside = self.root / 'outside'
        outside.write_text('keep')
        target.symlink_to(outside)
        for action in ('rules-read', 'rules-save', 'rules-delete'):
            with self.assertRaises((OSError, ValueError)):
                self.rules(action, revision='missing', text='replace')
        self.assertEqual(outside.read_text(), 'keep')
        target.unlink()
        target.write_bytes(b'\xff')
        with self.assertRaisesRegex(files.FileOperationError, 'UTF-8'):
            self.rules()
        target.unlink()
        with patch.object(files, 'RULES_LIMIT', 2):
            with self.assertRaisesRegex(files.FileOperationError, 'limit'):
                self.rules('rules-save', revision='missing', text='abc')
        self.assertFalse(target.exists())
