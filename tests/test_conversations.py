import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parents[1]/'antigravity'))
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
import conversation_history as h

class ConversationsTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.base=Path(self.tmp.name)
        self.bp=patch.object(h,'BASE',self.base);self.bp.start()
        self.running=patch.object(h,'cli_running',return_value=True);self.running.start()
        with sqlite3.connect(self.base/'conversation_summaries.db') as db:
            db.execute('CREATE TABLE conversation_summaries(conversation_id TEXT PRIMARY KEY,title TEXT,step_count INTEGER,last_modified_time TEXT)')
            db.executemany('INSERT INTO conversation_summaries VALUES(?,?,?,?)', [('older','Older',5,'2026-10-01'),('newer',None,10,'2026-10-06')])
    def tearDown(self):
        self.running.stop();self.bp.stop();self.tmp.cleanup()
    def test_listing_is_read_only_and_ignores_old_backups(self):
        path=self.base/'conversation_summaries.db';before=path.read_bytes()
        backup=self.base/'history-trash';backup.mkdir();(backup/'record.json').write_text('not valid json')
        result=h.listing()
        self.assertEqual([i['id'] for i in result['items']],['newer','older'])
        self.assertEqual(result['items'][0]['title'],'Untitled conversation')
        self.assertTrue(result['running']);self.assertEqual(path.read_bytes(),before)
        self.assertEqual((backup/'record.json').read_text(),'not valid json')
        with h.connect() as db:
            with self.assertRaises(sqlite3.OperationalError):
                db.execute('DELETE FROM conversation_summaries')
    def test_missing_database_is_not_created(self):
        path=self.base/'conversation_summaries.db';path.unlink()
        with self.assertRaises(h.HistoryError):h.listing()
        self.assertFalse(path.exists())
    def test_linked_database_is_rejected(self):
        path=self.base/'conversation_summaries.db';real=self.base/'original.db';path.rename(real);path.symlink_to(real)
        with self.assertRaises(h.HistoryError):h.listing()
