"""Build VectorViewer.exe as a Windows one-file release with Nuitka."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "vectorviewer.py"
ICON = ROOT / "icon.ico"
OUTPUT_DIR = ROOT / "dist"

REQUIRED_MODULES = ("nuitka", "geopandas", "pyogrio", "shapely", "pyproj")


def main() -> int:
    if sys.platform != "win32":
        print("이 빌드 스크립트는 Windows용입니다.", file=sys.stderr)
        return 2

    missing = [name for name in REQUIRED_MODULES if importlib.util.find_spec(name) is None]
    if missing:
        print("필수 패키지가 없습니다: " + ", ".join(missing), file=sys.stderr)
        print(
            "설치: python -m pip install nuitka geopandas pyogrio shapely pyproj ordered-set zstandard",
            file=sys.stderr,
        )
        return 2
    if not SOURCE.is_file():
        print(f"소스 파일이 없습니다: {SOURCE}", file=sys.stderr)
        return 2
    if not ICON.is_file():
        print(f"아이콘 파일이 없습니다: {ICON}", file=sys.stderr)
        return 2

    OUTPUT_DIR.mkdir(exist_ok=True)
    command = [
        sys.executable,
        "-m",
        "nuitka",
        "--mode=onefile",
        "--assume-yes-for-downloads",
        "--windows-console-mode=disable",
        f"--windows-icon-from-ico={ICON}",
        "--windows-product-name=VectorViewer",
        "--windows-file-description=Vector file browser viewer",
        "--windows-file-version=1.0.0.0",
        "--windows-product-version=1.0.0.0",
        "--output-filename=VectorViewer.exe",
        f"--output-dir={OUTPUT_DIR}",
        "--include-package=geopandas",
        "--include-package=pyogrio",
        "--include-package=shapely",
        "--include-package=pyproj",
        "--include-package-data=pyogrio",
        "--include-package-data=pyproj",
        "--nofollow-import-to=geopandas.tests",
        "--nofollow-import-to=numpy.tests",
        "--nofollow-import-to=pandas.tests",
        str(SOURCE),
    ]

    print("VectorViewer.exe 빌드를 시작합니다.")
    completed = subprocess.run(command, cwd=ROOT, check=False)
    if completed.returncode == 0:
        print(f"완료: {OUTPUT_DIR / 'VectorViewer.exe'}")
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
