"""Compute SHA-256 hex digests for wheel files.

This uses the same hashlib.sha256(file_bytes).hexdigest() as a local checksum.
It is 不是签名, and cannot 抵御托管平台整体失陷. A matching digest only
means this file's bytes agree with a published 发布声明; it does not prove
the hosting platform is honest.
"""

from __future__ import annotations

import argparse
import glob
import hashlib
import sys
from collections.abc import Sequence
from pathlib import Path


def sha256_hex(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_sidecar(path: Path, digest: str) -> Path:
    sidecar = Path(str(path) + ".sha256")
    sidecar.write_text(f"{digest}  {path.name}\n", encoding="utf-8")
    return sidecar


def expand_inputs(values: Sequence[str]) -> list[Path]:
    paths: list[Path] = []
    for value in values:
        matches = [Path(item) for item in sorted(glob.glob(value))]
        paths.extend(matches if matches else [Path(value)])
    return paths


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Write a SHA-256 sidecar next to each wheel. "
            "Checksum only; 不是签名; cannot resist platform 失陷."
        )
    )
    parser.add_argument("wheels", nargs="+", help="wheel path or glob")
    args = parser.parse_args(argv)
    wheels = expand_inputs(args.wheels)
    if not wheels:
        print("no wheel files", file=sys.stderr)
        return 2
    for wheel in wheels:
        if not wheel.is_file():
            print(f"missing: {wheel}", file=sys.stderr)
            return 2
        digest = sha256_hex(wheel)
        sidecar = write_sidecar(wheel, digest)
        print(digest)
        print(sidecar)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
