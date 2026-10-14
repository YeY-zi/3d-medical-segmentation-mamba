"""Generate synthetic volumes only; no patient or BraTS data included."""
import json
from pathlib import Path
import sys
import nibabel as nib
import numpy as np


def create_demo(output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(42)
    cases = []
    for name in ['healthy_input', 'missing_flair', 'shifted_geometry', 'nonfinite_data', 'constant_image']:
        modalities = {}
        for modality in ['t1', 't1ce', 't2', 'flair']:
            if name == 'missing_flair' and modality == 'flair':
                continue
            data = rng.normal(size=(12, 14, 10)).astype(np.float32)
            affine = np.eye(4)
            if name == 'shifted_geometry' and modality == 't2':
                affine[0, 3] = 5.0
            if name == 'nonfinite_data' and modality == 't1':
                data[0, 0, 0] = np.nan
            if name == 'constant_image' and modality == 't1':
                data.fill(0)
            image = nib.Nifti1Image(data, affine)
            image.header.set_xyzt_units('mm')
            path = output / name / (modality + '.nii.gz')
            path.parent.mkdir(exist_ok=True)
            nib.save(image, path)
            modalities[modality] = path.relative_to(output).as_posix()
        cases.append({'id': name, 'modalities': modalities})
    (output / 'manifest.json').write_text(json.dumps({'cases': cases}, indent=2) + '\n', encoding='utf-8')
    return output / 'manifest.json'


if __name__ == '__main__':
    print(create_demo(sys.argv[1] if len(sys.argv) > 1 else 'demo-data'))
