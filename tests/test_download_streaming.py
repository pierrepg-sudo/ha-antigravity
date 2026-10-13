import io
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch
from test_mobile import m  # Ensures the app modules are on sys.path.
import workspace_files as files
import file_server


class StreamingTests(unittest.TestCase):
    def test_download_boundary_and_link_rejection(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'file').write_bytes(b'1234')
            (root/'link').symlink_to(root/'file')
            token = files.ACTIVE_ROOT.set(str(root))
            try:
                with patch.object(files, 'DOWNLOAD_LIMIT', 4):
                    with files.download_file('file') as (stream, name, length):
                        self.assertEqual((name, length), ('file', 4))
                        self.assertEqual(stream.read(), b'1234')
                with patch.object(files, 'DOWNLOAD_LIMIT', 3):
                    with self.assertRaises(files.FileOperationError):
                        with files.download_file('file'):
                            self.fail('Oversized download accepted')
                with self.assertRaises(OSError):
                    with files.download_file('link'):
                        self.fail('Link followed')
            finally:
                files.ACTIVE_ROOT.reset(token)

    def test_stream_does_not_read_growing_suffix(self):
        headers = {}
        response = SimpleNamespace(
            send_response=lambda code: None,
            send_header=lambda key, value: headers.update({key: value}),
            end_headers=lambda: None, wfile=io.BytesIO(), close_connection=False)
        source = io.BytesIO(b'original-appended')
        file_server.Handler.stream_download(response, source, 'file', 8)
        self.assertEqual(response.wfile.getvalue(), b'original')
        self.assertEqual(source.tell(), 8)
        self.assertEqual(headers['Content-Length'], '8')

    def test_truncated_source_closes_response(self):
        response = SimpleNamespace(
            send_response=lambda code: None, send_header=lambda *args: None,
            end_headers=lambda: None, wfile=io.BytesIO(), close_connection=False)
        file_server.Handler.stream_download(response, io.BytesIO(b'x'), 'file', 10)
        self.assertTrue(response.close_connection)
        self.assertEqual(response.wfile.getvalue(), b'x')

    def test_large_transfer_reads_bounded_chunks(self):
        reads = []
        class Source(io.BytesIO):
            def read(self, size=-1):
                reads.append(size)
                return super().read(size)
        response = SimpleNamespace(
            send_response=lambda code: None, send_header=lambda *args: None,
            end_headers=lambda: None, wfile=io.BytesIO(), close_connection=False)
        data = b'a' * (200 * 1024)
        file_server.Handler.stream_download(response, Source(data), 'file', len(data))
        self.assertEqual(response.wfile.getvalue(), data)
        self.assertLessEqual(max(reads), 64 * 1024)
