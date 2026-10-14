"""CPU-only NIfTI input audit. Run python audit.py --help."""
import argparse
from html import escape
import json
from pathlib import Path
import sys

import nibabel as nib
import numpy as np


def validate_manifest(document):
    if not isinstance(document, dict) or not isinstance(document.get('cases'), list) or not document['cases']:
        raise ValueError('manifest must contain a non-empty cases list')
    seen = set()
    for case in document['cases']:
        if not isinstance(case, dict) or not isinstance(case.get('id'), str) or not case['id'].strip():
            raise ValueError('each case requires a non-empty string id')
        if case['id'] in seen:
            raise ValueError('duplicate case id: ' + case['id'])
        seen.add(case['id'])
        modalities = case.get('modalities')
        if not isinstance(modalities, dict) or any(not isinstance(k, str) or not isinstance(v, str) or not v for k, v in modalities.items()):
            raise ValueError('modalities must map modality names to non-empty paths')
        for filename in modalities.values():
            p = Path(filename)
            if p.is_absolute() or '..' in p.parts:
                raise ValueError('use relative paths below the manifest directory')
    return document['cases']


def inspect_image(path, max_voxels):
    result = {'shape': None, 'spacing': None, 'orientation': None, 'spatial_unit': None,
              'affine': None, 'finite_fraction': None, 'errors': [], 'warnings': []}
    if not path.is_file():
        result['errors'].append('missing_file')
        return result
    if not (path.name.lower().endswith('.nii') or path.name.lower().endswith('.nii.gz')):
        result['errors'].append('unsupported_format')
        return result
    try:
        img = nib.load(str(path))
        shape = tuple(int(x) for x in img.shape)
        result['shape'] = list(shape)
        if len(shape) != 3 or any(x <= 0 for x in shape):
            result['errors'].append('expected_3d_volume')
            return result
        affine = np.asarray(img.affine, dtype=float)
        if not np.isfinite(affine).all() or abs(np.linalg.det(affine[:3, :3])) < 1e-12:
            result['errors'].append('invalid_affine')
            return result
        result['affine'] = affine.tolist()
        spacing = nib.affines.voxel_sizes(affine)
        result['spacing'] = spacing.tolist()
        result['orientation'] = list(nib.aff2axcodes(affine))
        result['spatial_unit'] = img.header.get_xyzt_units()[0]
        if result['spatial_unit'] == 'unknown':
            result['warnings'].append('unknown_spatial_unit')
        qform, qcode = img.get_qform(coded=True)
        sform, scode = img.get_sform(coded=True)
        if qcode and scode and not np.allclose(qform, sform, atol=1e-4, rtol=0):
            result['warnings'].append('qform_sform_disagree')
        if not qcode and not scode:
            result['warnings'].append('no_coded_spatial_transform')
        if int(np.prod(shape, dtype=np.int64)) > max_voxels:
            result['errors'].append('voxel_limit_exceeded')
            return result
        data = img.get_fdata(dtype=np.float32)
        finite = np.isfinite(data)
        result['finite_fraction'] = float(finite.mean())
        if not finite.all():
            result['errors'].append('nonfinite_voxels')
        if finite.any():
            values = data[finite]
            if float(values.max()) == float(values.min()):
                result['warnings'].append('constant_intensity')
    except Exception as exc:
        # Do not include absolute input paths or patient metadata in reports.
        result['errors'].append('unreadable_nifti:' + type(exc).__name__)
    return result


def audit(manifest_path, expected=('t1', 't1ce', 't2', 'flair'), max_voxels=50_000_000):
    manifest_path = Path(manifest_path)
    expected = tuple(expected)
    if not expected or any(not x for x in expected) or len(set(expected)) != len(expected):
        raise ValueError('expected modalities must be distinct non-empty names')
    if max_voxels <= 0:
        raise ValueError('max_voxels must be positive')
    cases = validate_manifest(json.loads(manifest_path.read_text(encoding='utf-8-sig')))
    root = manifest_path.parent.resolve()
    results = []
    for case in cases:
        item = {'id': case['id'], 'images': {}, 'errors': [], 'warnings': []}
        for modality in expected:
            if modality not in case['modalities']:
                item['errors'].append('missing_modality:' + modality)
        for modality, filename in sorted(case['modalities'].items()):
            path = (root / filename).resolve()
            if not path.is_relative_to(root):
                raise ValueError('resolved file path escapes manifest directory')
            inspected = inspect_image(path, max_voxels)
            item['images'][modality] = inspected
            item['errors'].extend(modality + ':' + issue for issue in inspected['errors'])
            item['warnings'].extend(modality + ':' + issue for issue in inspected['warnings'])
            if modality not in expected:
                item['warnings'].append('unexpected_modality:' + modality)
        reference = None
        for modality in expected:
            candidate = item['images'].get(modality)
            if candidate and candidate['affine'] is not None:
                if reference is None:
                    reference = (modality, candidate)
                    continue
                ref_name, ref = reference
                if candidate['shape'] != ref['shape']:
                    item['errors'].append('shape_mismatch:' + modality + ':' + ref_name)
                if candidate['spatial_unit'] != ref['spatial_unit']:
                    item['errors'].append('spatial_unit_mismatch:' + modality + ':' + ref_name)
                if not np.allclose(candidate['affine'], ref['affine'], atol=1e-4, rtol=0):
                    item['errors'].append('affine_mismatch:' + modality + ':' + ref_name)
        item['status'] = 'fail' if item['errors'] else 'warn' if item['warnings'] else 'pass'
        results.append(item)
    return {'schema_version': 1, 'expected_modalities': list(expected),
            'summary': {s: sum(c['status'] == s for c in results) for s in ('pass', 'warn', 'fail')},
            'cases': results,
            'limitations': 'Structural input audit only. A pass does not establish anatomical alignment, diagnostic quality, or model accuracy.'}


def write_reports(report, output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    rows = []
    for case in report['cases']:
        details = []
        for modality, img in case['images'].items():
            details.append(escape(modality) + ': ' + escape(str(img['shape'])) + ' / ' + escape(str(img['orientation'])))
        issues = ['ERROR ' + x for x in case['errors']] + ['WARN ' + x for x in case['warnings']]
        rows.append('<tr><td>' + escape(case['id']) + '</td><td class="' + case['status'] + '">' + case['status'].upper() + '</td><td>' + '<br>'.join(details) + '</td><td>' + '<br>'.join(escape(x) for x in issues) + '</td></tr>')
    summary = ' | '.join(s.upper() + ': ' + str(n) for s, n in report['summary'].items())
    page = '''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Medical Image QC Report</title>
<style>body{font:16px system-ui,sans-serif;color:#17324d;background:#f5f7fa;margin:0;padding:36px}main{max-width:1250px;margin:auto}h1{font-size:30px;margin-bottom:12px}.summary{padding:20px;background:#17324d;color:white;border-radius:10px;font-weight:600}table{width:100%;border-collapse:collapse;background:white;margin-top:24px}th,td{padding:15px;text-align:left;border-bottom:1px solid #dce4ec;vertical-align:top;overflow-wrap:anywhere}th{background:#e9eff5}.pass{color:#117348}.warn{color:#976400}.fail{color:#ba2929}footer{margin-top:25px;color:#53677b;font-size:14px}td:nth-child(2){font-weight:700}</style>
<main><h1>Medical Image QC Report</h1><p>NIfTI modality completeness, geometry and basic voxel checks.</p><div class="summary">''' + summary + '</div><table><thead><tr><th>Case</th><th>Status</th><th>Modality / shape / orientation</th><th>Findings</th></tr></thead><tbody>' + ''.join(rows) + '</tbody></table><footer>' + escape(report['limitations']) + '</footer></main></html>'
    (output / 'report.html').write_text(page, encoding='utf-8')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', type=Path)
    parser.add_argument('--out', type=Path, default=Path('reports'))
    parser.add_argument('--expected', default='t1,t1ce,t2,flair')
    parser.add_argument('--max-voxels', type=int, default=50_000_000)
    args = parser.parse_args(argv)
    try:
        report = audit(args.manifest, [x.strip() for x in args.expected.split(',')], args.max_voxels)
        write_reports(report, args.out)
    except (ValueError, OSError) as exc:
        print('Input/output error: ' + str(exc), file=sys.stderr)
        return 2
    print(json.dumps(report['summary']))
    return 1 if report['summary']['fail'] else 0


if __name__ == '__main__':
    sys.exit(main())
