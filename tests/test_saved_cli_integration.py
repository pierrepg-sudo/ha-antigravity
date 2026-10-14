"""Real-CLI regression: saved listing/deletion across restarts, with outbound networking denied."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parents[1]/'antigravity'))
import http.client
import json
import os
import pty
import re
import sqlite3
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch
from network_guard import block_outbound
import conversation_history as history
import native_connection as native
import saved_conversations as saved

@unittest.skipUnless(os.environ.get('ANTIGRAVITY_TEST_BINARY'),'Set ANTIGRAVITY_TEST_BINARY for live CLI checks')
class SavedCLITests(unittest.TestCase):
    def test_old_history_delete_survives_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);master,slave=pty.openpty();child=None;connection=None
            def stop():
                if child is not None and child.poll() is None:child.kill();child.wait(timeout=5)
            def start(number):
                nonlocal child,connection
                log=root/f'{number}.log'
                child=subprocess.Popen([os.environ['ANTIGRAVITY_TEST_BINARY'],'--gemini_dir='+directory,
                    '--csrf_token=history-test-token','--log-file='+str(log)],stdin=slave,stdout=slave,stderr=slave,
                    cwd=directory,start_new_session=True,preexec_fn=block_outbound,
                    env={'HOME':directory,'PATH':'/usr/bin:/bin','TERM':'xterm-256color'})
                deadline=time.monotonic()+15
                while time.monotonic()<deadline:
                    match=re.search(r'port at (\d+) for HTTP\b',log.read_text() if log.exists() else '')
                    if match:
                        connection=dict(pid=child.pid,started=str(number),host='127.0.0.1',port=int(match[1]),token='history-test-token');return
                    time.sleep(.1)
                self.fail('CLI local listener did not start')
            def create():
                # Test-only RPC; production deliberately cannot create/run conversations.
                client=http.client.HTTPConnection(connection['host'],connection['port'],timeout=8)
                client.request('POST',native.SERVICE+'StartCascade',json.dumps({'source':'CORTEX_TRAJECTORY_SOURCE_CLI'}),
                    {'Content-Type':'application/json','x-codeium-csrf-token':connection['token']})
                response=client.getresponse();body=response.read();client.close();self.assertEqual(response.status,200)
                return json.loads(body)['cascadeId']
            try:
                start(1);cid=create();keep=create();time.sleep(.3);stop()
                # Read the real CLI-created default project from its actual config path.
                with patch.object(saved,'ROOT',root/'antigravity-cli'):
                    self.assertEqual(saved.project_names()['default-cli-project'],'CLI Project')
                # CLI-created trajectory databases are real. Index metadata is a fixture,
                # since these empty test conversations were created without signing in.
                start(2)
                time.sleep(.3)
                db=root/'antigravity-cli/conversation_summaries.db'
                with sqlite3.connect(db) as con:
                    for value,title in [(cid,'Older saved conversation'),(keep,'Keep this conversation')]:
                        con.execute('INSERT OR REPLACE INTO conversation_summaries '
                            '(conversation_id,title,step_count,last_modified_time,workspace_uris,status,last_user_input_time) '
                            'VALUES (?,?,0,?,\'[]\',?,?)',
                            (value,title,'2026-10-01T12:00:00Z','CASCADE_RUN_STATUS_IDLE','2026-10-01T12:00:00Z'))
                # Adapt PID lookup only for the test runner's mismatched /proc namespace.
                def identity(pid):
                    if pid!=child.pid or child.poll() is not None:raise ProcessLookupError()
                    return os.getpid(),connection['started']
                with patch.object(saved,'ROOT',root/'antigravity-cli'),patch.object(native,'load',side_effect=lambda:connection),patch.object(native,'process',side_effect=identity):
                    self.assertEqual(native.summaries(connection),{})
                    rows=history.listing()['items'];self.assertEqual({r['id'] for r in rows},{cid,keep})
                    row=next(r for r in rows if r['id']==cid)
                    self.assertEqual(row['title'],'Older saved conversation')
                    row=history.prepare({'id':cid})['item']
                    checked=history.prepare({'id':cid})['item']
                    self.assertEqual(row['revision'],checked['revision'])
                    outcome=history.delete(dict(id=cid,revision=checked['revision'],confirm=True))
                    self.assertTrue(outcome['ok'])
                    self.assertFalse(saved.exists(cid));self.assertTrue(saved.exists(keep))
                    stop();start(3)
                    self.assertEqual([r['id'] for r in history.listing()['items']],[keep])
                    with self.assertRaises(native.NativeError):native.rpc(connection,native.LOAD,{'cascadeId':cid})
                    native.rpc(connection,native.LOAD,{'cascadeId':keep})
                    self.assertIn(keep,native.summaries(connection))
            finally:
                stop();os.close(master);os.close(slave)
