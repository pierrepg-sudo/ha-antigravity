import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parents[1]/'antigravity'))
import fcntl
import json
import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
import conversation_history as h

CID='12345678-1234-1234-1234-123456789012'
CHILD='87654321-4321-4321-4321-210987654321'

class ConversationsTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.base=Path(self.tmp.name)
        self.bp=patch.object(h,'BASE',self.base);self.bp.start()
        self.running=patch.object(h,'cli_running',return_value=False);self.running.start()
        (self.base/'conversations').mkdir()
        with sqlite3.connect(self.base/'conversation_summaries.db') as db:
            db.execute('CREATE TABLE conversation_summaries(conversation_id TEXT PRIMARY KEY,title TEXT,step_count INTEGER,last_modified_time TEXT,parent_conversation_id TEXT,not_fully_idle NUMERIC,raw_summary BLOB)')
            db.execute('INSERT INTO conversation_summaries VALUES(?,?,?,?,?,?,?)',(CID,'Example <title>',12,'2026-10-06',None,0,b'\x00\xffsummary'))
        with sqlite3.connect(self.base/'conversations'/(CID+'.db')) as db:
            db.execute('CREATE TABLE steps(idx INTEGER,data BLOB)');db.execute('INSERT INTO steps VALUES(1,?)',(b'transcript',))
    def tearDown(self):
        self.running.stop();self.bp.stop();self.tmp.cleanup()
    def delete(self):return h.change({'action':'delete','id':CID,'confirm':True})
    def test_list_delete_and_restore_exact_data(self):
        before=(self.base/'conversation_summaries.db').read_bytes()
        self.assertEqual(h.listing()['items'][0]['title'],'Example <title>')
        self.assertEqual(before,(self.base/'conversation_summaries.db').read_bytes())
        self.delete();data=h.listing();self.assertEqual(data['items'],[]);self.assertEqual(len(data['trash']),1)
        self.assertFalse((self.base/'conversations'/(CID+'.db')).exists())
        h.change({'action':'restore','backup':data['trash'][0]['backup'],'confirm':True})
        self.assertEqual(len(h.listing()['items']),1)
        with h.connect() as db:self.assertEqual(db.execute('SELECT raw_summary FROM conversation_summaries').fetchone()[0],b'\x00\xffsummary')
        with sqlite3.connect(self.base/'conversations'/(CID+'.db')) as db:self.assertEqual(db.execute('SELECT data FROM steps').fetchone()[0],b'transcript')
        self.delete();self.assertEqual(len(h.listing()['trash']),1)
    def test_active_cli_and_shared_lock_block_changes(self):
        with patch.object(h,'cli_running',return_value=True):
            with self.assertRaises(h.HistoryError):self.delete()
        with open(self.base/'history.lock','w') as lock:
            fcntl.flock(lock,fcntl.LOCK_SH)
            with self.assertRaises(h.HistoryError):self.delete()
        self.assertTrue((self.base/'conversations'/(CID+'.db')).exists())
    def test_confirmation_and_traversal(self):
        for payload in ({'action':'delete','id':CID},{'action':'delete','id':'../../etc/passwd','confirm':True},{'action':'restore','backup':'bad','confirm':True}):
            with self.assertRaises(h.HistoryError):h.change(payload)
    def test_children_and_busy_rows_blocked(self):
        with sqlite3.connect(self.base/'conversation_summaries.db') as db:
            db.execute('INSERT INTO conversation_summaries VALUES(?,?,?,?,?,?,?)',(CHILD,'Child',1,'2026',CID,0,b''))
        with self.assertRaises(h.HistoryError):self.delete()
        with sqlite3.connect(self.base/'conversation_summaries.db') as db:
            db.execute('DELETE FROM conversation_summaries WHERE conversation_id=?',(CHILD,));db.execute('UPDATE conversation_summaries SET not_fully_idle=1')
        with self.assertRaises(h.HistoryError):self.delete()
    def test_move_failure_rolls_back(self):
        real=os.rename;count=0
        def fail_once(source,target):
            nonlocal count
            count+=1
            if count==1:raise OSError('simulated failure')
            return real(source,target)
        with patch.object(h.os,'rename',side_effect=fail_once):
            with self.assertRaises(OSError):self.delete()
        self.assertEqual(len(h.listing()['items']),1)
        self.assertTrue((self.base/'conversations'/(CID+'.db')).exists())
    def test_recovery_after_commit_before_restore_move(self):
        self.delete();folder,data=h.entries()[0]
        with sqlite3.connect(self.base/'conversation_summaries.db') as db:
            row=data['row'];db.execute('INSERT INTO conversation_summaries VALUES(?,?,?,?,?,?,?)',[h.unpack(v) for v in row.values()])
        h.recover()
        self.assertTrue((self.base/'conversations'/(CID+'.db')).is_file())
        self.assertFalse((folder/'conversation.db').exists())
    def test_recovery_before_delete_commit(self):
        self.delete();folder,data=h.entries()[0]
        with sqlite3.connect(self.base/'conversation_summaries.db') as db:
            db.execute('INSERT INTO conversation_summaries VALUES(?,?,?,?,?,?,?)',[h.unpack(v) for v in data['row'].values()])
        # Same state as moving the DB before an uncommitted delete rolls back.
        h.recover();self.assertEqual(len(h.listing()['items']),1)
    def test_symlink_database_is_not_moved(self):
        path=self.base/'conversations'/(CID+'.db');path.unlink();outside=self.base/'outside.db';outside.write_bytes(b'untouched');path.symlink_to(outside)
        with self.assertRaises(h.HistoryError):self.delete()
        self.assertEqual(outside.read_bytes(),b'untouched')
