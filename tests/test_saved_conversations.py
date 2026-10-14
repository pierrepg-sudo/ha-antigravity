import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parents[1]/'antigravity'))
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
import saved_conversations as saved
import conversation_history as history
import native_connection as native

CID = '12345678-1234-1234-1234-123456789012'
CONNECTION = dict(pid=42,started='1',host='127.0.0.1',port=42,token='test')
SCHEMA = '''CREATE TABLE conversation_summaries (conversation_id TEXT PRIMARY KEY, title TEXT,
step_count INTEGER, last_modified_time TEXT, status TEXT, not_fully_idle INTEGER,
parent_conversation_id TEXT)'''

def seed(root, cid=CID, busy=0):
    directory=root/'conversations';directory.mkdir(exist_ok=True)
    (directory/(cid+'.db')).touch()
    with sqlite3.connect(root/'conversation_summaries.db') as db:
        db.execute(SCHEMA.replace('CREATE TABLE','CREATE TABLE IF NOT EXISTS'))
        db.execute('INSERT OR REPLACE INTO conversation_summaries VALUES (?,?,?,?,?,?,?)',
            (cid,'Saved title',12,'2026-10-01T12:00:00Z','CASCADE_RUN_STATUS_IDLE',busy,''))

class SavedTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.patch=patch.object(saved,'ROOT',self.root);self.patch.start()
    def tearDown(self):self.patch.stop();self.temp.cleanup()
    def test_all_22_saved_entries_are_listed_without_loading_or_writing(self):
        for i in range(22):seed(self.root,f'{i:08x}-1234-1234-1234-123456789012')
        before=(self.root/'conversation_summaries.db').read_bytes()
        phantom='ffffffff-1234-1234-1234-123456789012'
        with patch.object(native,'load',return_value=CONNECTION),patch.object(native,'summaries',return_value={phantom:{'status':'CASCADE_RUN_STATUS_IDLE'}}),patch.object(native,'rpc') as rpc:
            rows=history.listing()['items']
            self.assertEqual(len(rows),22);self.assertTrue(all(r['title']=='Saved title' and r['steps']==12 for r in rows));rpc.assert_not_called()
        self.assertEqual(before,(self.root/'conversation_summaries.db').read_bytes())
    def test_stale_index_row_cannot_resurrect_deleted_file(self):
        seed(self.root);(self.root/'conversations'/f'{CID}.db').unlink()
        self.assertEqual(saved.read(),{})
    def test_busy_or_unindexed_files_cannot_be_deleted(self):
        seed(self.root,busy=1)
        self.assertTrue(history.item(CONNECTION,CID,saved.read()[CID])['blocked'])
        (self.root/'conversation_summaries.db').unlink()
        self.assertTrue(history.item(CONNECTION,CID,saved.read()[CID])['blocked'])
    def test_symlink_and_unsupported_schema_fail_closed(self):
        seed(self.root);db=self.root/'conversation_summaries.db';db.unlink();db.symlink_to(self.root/'conversations'/f'{CID}.db')
        with self.assertRaises(native.NativeError):saved.read()
        db.unlink()
        with sqlite3.connect(db) as con:con.execute('CREATE TABLE incompatible (id TEXT)')
        with self.assertRaises(native.NativeError):saved.read()
    def test_saved_delete_loads_checks_idle_and_requires_file_absence(self):
        seed(self.root)
        with patch.object(native,'load',return_value=CONNECTION),patch.object(native,'summaries',return_value={}) as summaries,patch.object(native,'rpc') as rpc:
            row=history.listing()['items'][0];payload=dict(id=CID,revision=row['revision'],confirm=True)
            summaries.side_effect=[{}, {CID:{'status':'CASCADE_RUN_STATUS_IDLE'}}, {}, {}]
            with self.assertRaisesRegex(native.NativeError,'still listed'):history.delete(payload)
            self.assertEqual([c.args[1] for c in rpc.call_args_list],[native.LOAD,native.DELETE])
    def test_load_failure_or_busy_state_never_deletes(self):
        seed(self.root)
        with patch.object(native,'load',return_value=CONNECTION),patch.object(native,'summaries',return_value={}) as summaries,patch.object(native,'rpc') as rpc:
            row=history.listing()['items'][0];payload=dict(id=CID,revision=row['revision'],confirm=True)
            rpc.side_effect=native.NativeError('load failed')
            with self.assertRaises(native.NativeError):history.delete(payload)
            self.assertEqual(rpc.call_args.args[1],native.LOAD)
            rpc.reset_mock();rpc.side_effect=None
            summaries.side_effect=[{},{CID:{'status':'CASCADE_RUN_STATUS_RUNNING'}}]
            with self.assertRaises(native.NativeError):history.delete(payload)
            self.assertEqual([c.args[1] for c in rpc.call_args_list],[native.LOAD])
    def test_changed_file_invalidates_confirmation(self):
        seed(self.root)
        with patch.object(native,'load',return_value=CONNECTION),patch.object(native,'summaries',return_value={}),patch.object(native,'rpc') as rpc:
            row=history.listing()['items'][0]
            (self.root/'conversations'/f'{CID}.db').write_bytes(b'changed')
            with self.assertRaises(native.NativeError):history.delete(dict(id=CID,revision=row['revision'],confirm=True))
            rpc.assert_not_called()

    def test_prepare_refreshes_after_load_without_deleting(self):
        seed(self.root)
        with patch.object(native,'load',return_value=CONNECTION),patch.object(native,'summaries',return_value={CID:{'status':'CASCADE_RUN_STATUS_IDLE'}}),patch.object(native,'rpc') as rpc:
            old=history.listing()['items'][0]
            rpc.side_effect=lambda *args:(self.root/'conversations'/f'{CID}.db').write_bytes(b'migrated')
            current=history.prepare({'id':CID})['item']
            self.assertNotEqual(old['revision'],current['revision'])
            self.assertEqual(current['revision'],history.listing()['items'][0]['revision'])
            self.assertEqual([c.args[1] for c in rpc.call_args_list],[native.LOAD])
            self.assertTrue(saved.exists(CID))

    def test_prepare_rejects_missing_busy_and_invalid(self):
        with patch.object(native,'load',return_value=CONNECTION),patch.object(native,'summaries',return_value={}),patch.object(native,'rpc') as rpc:
            for payload in ({'id':CID},{'id':'bad'},{'id':CID,'confirm':True}):
                with self.assertRaises(native.NativeError):history.prepare(payload)
            seed(self.root,busy=1)
            with self.assertRaises(native.NativeError):history.prepare({'id':CID})
            rpc.assert_not_called()

    def test_project_names_and_archive_metadata_survive_unloaded_history(self):
        seed(self.root)
        projects=self.root/'projects';projects.mkdir()
        (projects/'project-a.json').write_text('{"id":"project-a","name":"Home Assistant"}')
        with sqlite3.connect(self.root/'conversation_summaries.db') as db:
            db.execute('ALTER TABLE conversation_summaries ADD COLUMN project_id TEXT')
            db.execute('ALTER TABLE conversation_summaries ADD COLUMN raw_summary BLOB')
            # Summary field 15 contains annotations; archive bool is field 4.
            db.execute('UPDATE conversation_summaries SET project_id=?,raw_summary=?',
                       ('project-a',b'\x7a\x02\x20\x01'))
        with patch.object(native,'load',return_value=CONNECTION),patch.object(native,'summaries',return_value={}):
            row=history.listing()['items'][0]
            self.assertEqual(row['projectName'],'Home Assistant')
            self.assertEqual(row['projectId'],'project-a')
            self.assertIs(row['archived'],True)
        with patch.object(native,'load',return_value=CONNECTION),patch.object(native,'summaries',return_value={CID:{'annotations':{'archived':False},'status':'CASCADE_RUN_STATUS_IDLE'}}):
            self.assertIs(history.listing()['items'][0]['archived'],False)

    def test_archive_parser_handles_defaults_unknown_fields_and_corruption(self):
        self.assertIs(saved.archived(b'\x7a\x02\x20\x00'),False)
        self.assertIs(saved.archived(b'\x0a\x01x'),False)
        self.assertIs(saved.archived(b'\x7a\x04\x28\x01\x20\x01'),True)
        for value in (None,b'',b'\x7a\x05x',b'\x7a\x02\x20\x03',b'\x80'*11):
            self.assertIsNone(saved.archived(value))

    def test_project_files_are_read_only_and_symlinks_ignored(self):
        projects=self.root/'projects';projects.mkdir()
        (projects/'valid.json').write_text('{"name":"Valid"}')
        (projects/'invalid.json').write_text('not json')
        (projects/'link.json').symlink_to(projects/'valid.json')
        self.assertEqual(saved.project_names(),{'valid':'Valid'})
