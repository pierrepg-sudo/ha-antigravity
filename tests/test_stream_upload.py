import io
import tempfile
from pathlib import Path
import threading
import unittest
from unittest.mock import patch
from urllib.request import Request, urlopen
from urllib.error import HTTPError
import workspace_files as files
import file_server


class StreamUploadTests(unittest.TestCase):
    def test_stream_limits_truncation_collisions_and_cleanup(self):
        with tempfile.TemporaryDirectory() as root:
            token=files.ACTIVE_ROOT.set(root)
            try:
                self.assertEqual(files.UPLOAD_LIMIT,500*1024*1024)
                class Bounded(io.BytesIO):
                    def read(self,n=-1):
                        assert 0 < n <= 65536
                        return super().read(n)
                data=b'x'*(9*1024*1024)
                files.upload_stream('', 'large', Bounded(data),len(data))
                self.assertEqual((Path(root)/'large').read_bytes(),data)
                with self.assertRaises(FileExistsError):files.upload_stream('','large',io.BytesIO(b'new'),3)
                self.assertEqual((Path(root)/'large').stat().st_size,len(data))
                with self.assertRaises(files.FileOperationError):files.upload_stream('','short',io.BytesIO(b'x'),2)
                with self.assertRaises(files.FileOperationError):files.upload_stream('','huge',io.BytesIO(),files.UPLOAD_LIMIT+1)
                with self.assertRaises(ValueError):files.upload_stream('','../escape',io.BytesIO(),0)
                (Path(root)/'link').symlink_to('/tmp')
                with self.assertRaises(OSError):files.upload_stream('link','escape',io.BytesIO(),0)
                self.assertFalse((Path(root)/'short').exists())
                self.assertFalse(list(Path(root).glob('.upload-*')))
            finally:files.ACTIVE_ROOT.reset(token)

    def test_http_upload_auth_permissions_and_large_file(self):
        with tempfile.TemporaryDirectory() as root:
            server=file_server.ThreadingHTTPServer(('127.0.0.1',0),file_server.Handler)
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            url='http://127.0.0.1:'+str(server.server_port)+'/file-upload?area=inputs&path=&name=large'
            headers={'X-Antigravity-File-Key':'test','X-Antigravity-CSRF':file_server.CSRF,'Content-Type':'application/octet-stream'}
            try:
                with patch.dict(file_server.AREAS,inputs=root),patch.object(file_server,'PROXY_KEY','test'):
                    data=b'x'*(9*1024*1024)
                    with urlopen(Request(url,data=data,headers=headers)) as response:self.assertEqual(response.status,200)
                    self.assertEqual((Path(root)/'large').read_bytes(),data)
                    self.assertEqual((Path(root)/'large').stat().st_mode & 0o777,0o640)
                    for changed in ({**headers,'X-Antigravity-CSRF':'bad'},{**headers,'X-Antigravity-File-Key':'bad'}):
                        with self.assertRaises(HTTPError) as error:urlopen(Request(url,data=b'x',headers=changed))
                        self.assertEqual(error.exception.code,403)
                    with self.assertRaises(HTTPError) as error:urlopen(Request(url.replace('area=inputs','area=legacy'),data=b'x',headers=headers))
                    self.assertEqual(error.exception.code,403)
            finally:server.shutdown();server.server_close();thread.join()
