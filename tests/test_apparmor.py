from pathlib import Path
import tempfile
import unittest
from test_mobile import m  # Adds the add-on source directory to sys.path.
import verify_profile


class AppArmorStartupTests(unittest.TestCase):
    def test_exact_enforced_identity_and_supervisor_hostname_mapping(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'current'
            for name in ('5500fdef_antigravity_remote', 'local_antigravity_remote'):
                path.write_text(name + ' (enforce)\n')
                self.assertEqual(verify_profile.verify(path, name.replace('_', '-')), name + ' (enforce)')

    def test_fallback_complain_other_profile_and_stacking_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'current'
            for current in ('unconfined', 'docker-default (enforce)',
                            '5500fdef_antigravity_remote (complain)',
                            'other_profile (enforce)',
                            '5500fdef_antigravity_remote//child (enforce)'):
                path.write_text(current)
                with self.assertRaises(RuntimeError):
                    verify_profile.verify(path, '5500fdef-antigravity-remote')
            with self.assertRaises(RuntimeError):
                verify_profile.verify(path, 'unexpected-container')
            path.unlink()
            with self.assertRaises(RuntimeError):
                verify_profile.verify(path, '5500fdef-antigravity-remote')
