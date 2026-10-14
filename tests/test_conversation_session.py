import unittest
from unittest.mock import patch
import conversation_session as session
import native_connection as native

CID='12345678-1234-1234-1234-123456789abc'
class SessionTests(unittest.TestCase):
    def setUp(self):
        self.names=patch.object(session.saved,'project_names',return_value={'p1':'Project one'});self.names.start();self.addCleanup(self.names.stop)
        self.live=patch.object(native,'summaries',return_value={});self.summaries=self.live.start();self.addCleanup(self.live.stop)
    def test_new_and_project_validation(self):
        for project in ('','p1'):
            self.assertIsNone(session.launch_args({'action':'new','projectId':project,'confirm':True},{}))
        for payload in ({'action':'new','projectId':'missing','confirm':True},{'action':'new','projectId':'p1','confirm':False},{'action':'new','projectId':'p1','confirm':True,'args':['--unsafe']}):
            with self.assertRaises(native.NativeError):session.launch_args(payload,{})
    def test_busy_or_unknown_blocks_switch(self):
        for status in ('CASCADE_RUN_STATUS_RUNNING','unknown',None):
            self.summaries.return_value={CID:{'status':status}}
            with self.assertRaisesRegex(native.NativeError,'working'):
                session.launch_args({'action':'new','projectId':'','confirm':True},{})
    def test_open_requires_existing_id(self):
        with patch.object(session.history,'collect',return_value={CID:{}}):
            self.assertEqual(session.launch_args({'action':'open','id':CID,'confirm':True},{}),['--remote-control','--conversation='+CID])
            with self.assertRaises(native.NativeError):session.launch_args({'action':'open','id':'invalid','confirm':True},{})
    def test_creation_keeps_no_project_explicit(self):
        self.summaries.return_value={CID:{'trajectoryMetadata':{'projectId':'outside-of-project'}}}
        with patch.object(native,'rpc',return_value={'cascadeId':CID}) as rpc:
            args=session.materialize({'projectId':''},{},None)
            self.assertEqual(args,['--remote-control','--conversation='+CID])
            self.assertEqual(rpc.call_args.args[2]['projectEnvConfig'],{'projectId':'outside-of-project','defaultProjectEnvironment':{}})
    def test_mismatched_project_does_not_switch(self):
        with patch.object(native,'rpc',return_value={'cascadeId':CID}):
            with self.assertRaises(native.NativeError):session.materialize({'projectId':'p1'},{},None)


class HandoffTests(unittest.TestCase):
    def test_stale_session_cannot_stop_cli(self):
        import launch_cli
        from unittest.mock import Mock
        child=Mock(pid=123)
        with patch.object(native,'load',return_value={'pid':123,'started':'new'}):
            with self.assertRaises(native.NativeError):
                launch_cli.handoff({'payload':{},'pid':123,'started':'old'},child)
        child.terminate.assert_not_called()
    def test_verified_handoff_stops_child_without_kill(self):
        import launch_cli
        from unittest.mock import Mock
        child=Mock(pid=123)
        with patch.object(native,'load',return_value={'pid':123,'started':'same'}), patch.object(session,'launch_args',return_value=['--conversation='+CID]), patch.object(session,'materialize',return_value=['--conversation='+CID]):
            self.assertEqual(launch_cli.handoff({'payload':{},'pid':123,'started':'same'},child),['--conversation='+CID])
        child.terminate.assert_called_once();child.wait.assert_called_once_with(timeout=8);child.kill.assert_not_called()
