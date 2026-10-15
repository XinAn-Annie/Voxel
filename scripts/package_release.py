"""Build a minimal, structured release and verify every ZIP member."""
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
import hashlib
import json

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED = {'node_modules', '__pycache__', '.venv', '.git', '.pytest_cache'}


def main():
    destination = ROOT.parent / 'adaptive-voxel-web_v3_自适应算法优化_测试通过.zip'
    paths = sorted(p for p in ROOT.rglob('*') if p.is_file() and not (set(p.relative_to(ROOT).parts) & EXCLUDED) and p.suffix not in {'.pyc','.zip'})
    with ZipFile(destination, 'w', ZIP_DEFLATED, compresslevel=8) as archive:
        for path in paths:
            archive.write(path, 'adaptive-voxel-web/' + path.relative_to(ROOT).as_posix())
    with ZipFile(destination) as archive:
        assert archive.testzip() is None
        for info in archive.infolist():
            assert not info.filename.startswith('/') and '..' not in Path(info.filename).parts
    print(json.dumps({'zip': str(destination), 'files':len(paths), 'bytes':destination.stat().st_size, 'sha256':hashlib.sha256(destination.read_bytes()).hexdigest()}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
