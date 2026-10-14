import json
from pathlib import Path
import tempfile
import unittest
import nibabel as nib
import numpy as np
from audit import audit, main, write_reports
from make_demo import create_demo


class AuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.manifest = create_demo(self.root / 'data')

    def update_case(self, data=None, affine=None, name='t1', unit='mm'):
        image = nib.Nifti1Image(data if data is not None else np.ones((12, 14, 10), dtype=np.float32), affine if affine is not None else np.eye(4))
        image.header.set_xyzt_units(unit)
        nib.save(image, self.manifest.parent / 'healthy_input' / (name + '.nii.gz'))

    def first(self):
        return audit(self.manifest)['cases'][0]

    def test_demo_expected_outcomes(self):
        report = audit(self.manifest)
        self.assertEqual(report['summary'], {'pass': 1, 'warn': 1, 'fail': 3})
        self.assertEqual([x['status'] for x in report['cases']], ['pass', 'fail', 'fail', 'fail', 'warn'])

    def test_missing_file(self):
        (self.manifest.parent / 'healthy_input' / 't1.nii.gz').unlink()
        self.assertIn('t1:missing_file', self.first()['errors'])

    def test_corrupt_file(self):
        (self.manifest.parent / 'healthy_input' / 't1.nii.gz').write_bytes(b'invalid')
        self.assertTrue(any('unreadable_nifti' in x for x in self.first()['errors']))

    def test_4d_is_rejected(self):
        self.update_case(np.zeros((12, 14, 10, 2), dtype=np.float32))
        self.assertIn('t1:expected_3d_volume', self.first()['errors'])

    def test_shape_mismatch(self):
        self.update_case(np.ones((11, 14, 10), dtype=np.float32), name='t2')
        self.assertIn('shape_mismatch:t2:t1', self.first()['errors'])

    def test_flip_is_detected(self):
        affine = np.eye(4)
        affine[0, 0] = -1
        self.update_case(affine=affine, name='t2')
        self.assertIn('affine_mismatch:t2:t1', self.first()['errors'])

    def test_unknown_units_warn(self):
        self.update_case(unit='unknown')
        self.assertIn('t1:unknown_spatial_unit', self.first()['warnings'])

    def test_voxel_limit(self):
        self.assertIn('t1:voxel_limit_exceeded', audit(self.manifest, max_voxels=1)['cases'][0]['errors'])

    def test_duplicate_case_rejected(self):
        document = json.loads(self.manifest.read_text())
        document['cases'].append(document['cases'][0])
        self.manifest.write_text(json.dumps(document))
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            audit(self.manifest)

    def test_invalid_manifest(self):
        self.manifest.write_text('{"cases": []}')
        self.assertEqual(main([str(self.manifest), '--out', str(self.root / 'out')]), 2)

    def test_html_escape_and_strict_json(self):
        report = audit(self.manifest)
        report['cases'][0]['id'] = '<script>alert(1)</script>'
        out = self.root / 'report'
        write_reports(report, out)
        self.assertNotIn('<script>', (out / 'report.html').read_text())
        self.assertIn('&lt;script&gt;', (out / 'report.html').read_text())
        json.loads((out / 'report.json').read_text(), parse_constant=lambda x: self.fail('nonstandard JSON'))

    def test_cli_writes_reports_and_returns_fail(self):
        out = self.root / 'report'
        self.assertEqual(main([str(self.manifest), '--out', str(out)]), 1)
        self.assertTrue((out / 'report.html').exists())

    def test_unknown_modality_name_reported(self):
        self.assertIn('missing_modality:adc', audit(self.manifest, expected=('adc',))['cases'][0]['errors'])

    def test_path_traversal_rejected(self):
        self.manifest.write_text(json.dumps({'cases': [{'id': 'x', 'modalities': {'t1': '../outside.nii'}}]}))
        with self.assertRaises(ValueError):
            audit(self.manifest)

    def test_qform_sform_disagreement(self):
        path = self.manifest.parent / 'healthy_input' / 't1.nii.gz'
        img = nib.load(path)
        shifted = np.eye(4)
        shifted[0, 3] = 10
        img.set_qform(shifted, code=1)
        nib.save(img, path)
        self.assertIn('t1:qform_sform_disagree', self.first()['warnings'])


if __name__ == '__main__':
    unittest.main()
