from __future__ import annotations

import hashlib
import importlib.metadata
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
LICENSE = ROOT / "LICENSE"
THIRD_PARTY = ROOT / "THIRD_PARTY_LICENSES.md"
HASH_WHEEL = ROOT / "scripts" / "hash_wheel.py"
AGENT_LOG = ROOT / "AGENT_LOG.md"
PYPROJECT = ROOT / "pyproject.toml"

README_SECTIONS = (
    "产品简介",
    "安装",
    "config",
    "auth",
    "run 与信封确认",
    "HITL approve/reject/resume",
    "apply/discard",
    "memory",
    "机制演示",
    "分发",
    "项目目录结构",
    "安全边界",
    "源码离机隐私",
    "凭据威胁模型",
    "已知限制",
    "开发与测试",
    "第三方依赖及许可证",
    "GitHub Release 与 SHA-256 校验",
)

README_KEYWORDS = (
    "Python 3.12",
    "系统 Git",
    "demos/mechanism_demo.py",
    "CLI-only",
    "无 WebUI",
    "无云部署",
    "无单文件 exe",
    "无 OS 网络/文件系统沙箱",
    "当前用户权限",
    "可信",
    "keyring",
    "不自动",
    ".env",
    "不静默截断",
    "发布声明",
    "失陷",
    "https://github.com/xinyue-L01/guardedcoder",
    "发布后填写",
    "pydantic",
    "httpx",
    "THIRD_PARTY_LICENSES.md",
)

REQUIRED_PACKAGES = (
    "pydantic",
    "httpx",
    "keyring",
    "defusedxml",
    "SecretStorage",
    "pytest",
    "pip-tools",
    "build",
    "setuptools",
)

_TASK_HEADING = re.compile(r"· T(\d{2})(?:[–-]T(\d{2}))?")
_IMPLEMENTED_TASKS = tuple(f"T{n:02d}" for n in range(1, 44))


def _read(path: Path) -> str:
    assert path.is_file(), f"missing {path.relative_to(ROOT).as_posix()}"
    text = path.read_text(encoding="utf-8")
    assert text.strip(), f"empty {path.relative_to(ROOT).as_posix()}"
    return text


def _logged_tasks(text: str) -> set[str]:
    found: set[str] = set()
    for match in _TASK_HEADING.finditer(text):
        start = int(match.group(1))
        end = int(match.group(2) or match.group(1))
        for number in range(start, end + 1):
            found.add(f"T{number:02d}")
    return found


def _metadata_license(dist: importlib.metadata.Distribution) -> str:
    meta = dist.metadata
    for key in ("License-Expression", "License"):
        value = meta.get(key)
        if value and value.strip() and value.strip().upper() != "UNKNOWN":
            return value.strip()
    classifiers = meta.get_all("Classifier") or []
    licenses = [
        item.split("::")[-1].strip()
        for item in classifiers
        if item.startswith("License ::")
    ]
    return " / ".join(licenses)


def test_readme_has_required_sections_and_security_statements() -> None:
    text = _read(README)
    missing = [item for item in README_SECTIONS if item not in text]
    assert not missing, f"README missing sections: {missing}"
    missing_kw = [item for item in README_KEYWORDS if item not in text]
    assert not missing_kw, f"README missing statements: {missing_kw}"
    assert "releases/download/" not in text
    assert "已存在的 Release" not in text


def test_license_exists_and_matches_pyproject() -> None:
    license_text = _read(LICENSE)
    pyproject = _read(PYPROJECT)
    assert "MIT" in license_text
    assert "MIT" in pyproject
    assert "license" in pyproject.lower()


def test_third_party_licenses_cover_installed_direct_dependencies() -> None:
    text = _read(THIRD_PARTY)
    assert "许可证" in text or "License" in text
    for name in REQUIRED_PACKAGES:
        assert name in text or name.lower() in text.lower()
        try:
            dist = importlib.metadata.distribution(name)
        except importlib.metadata.PackageNotFoundError:
            continue
        assert dist.metadata["Name"] in text or name in text
        assert dist.version in text
        license_text = _metadata_license(dist)
        if license_text:
            token = license_text.splitlines()[0].strip()
            if len(token) > 80:
                token = token[:40]
            license_words = ("MIT", "BSD", "Apache", "PSF", "ISC", "MPL", "LGPL")
            assert token in text or any(
                word in text for word in license_words if word in license_text
            ), f"{name} license {license_text!r} not disclosed"


def test_hash_wheel_writes_sha256_sidecar_for_temp_file(tmp_path: Path) -> None:
    assert HASH_WHEEL.is_file(), "missing scripts/hash_wheel.py"
    wheel = tmp_path / "guardedcoder-0.0.0-py3-none-any.whl"
    wheel.write_bytes(b"not-a-real-wheel; hashed as bytes")
    expected = hashlib.sha256(wheel.read_bytes()).hexdigest()

    result = subprocess.run(
        [sys.executable, str(HASH_WHEEL), str(wheel)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    sidecar = Path(str(wheel) + ".sha256")
    assert sidecar.is_file()
    sidecar_text = sidecar.read_text(encoding="utf-8")
    assert expected in sidecar_text
    assert expected in result.stdout
    source = HASH_WHEEL.read_text(encoding="utf-8")
    lowered = source.lower()
    assert "sha256" in lowered
    assert "不是签名" in source or "not a signature" in lowered
    assert "失陷" in source or "compromis" in lowered


def test_agent_log_has_an_entry_for_each_implemented_task() -> None:
    text = _read(AGENT_LOG)
    logged = _logged_tasks(text)
    missing = [task for task in _IMPLEMENTED_TASKS if task not in logged]
    assert not missing, (
        "AGENT_LOG missing factual entries for: "
        + ", ".join(missing)
        + " (T42 audits only; do not rewrite history)"
    )


def test_sha256_disclaimer_is_present() -> None:
    readme = _read(README)
    hash_src = _read(HASH_WHEEL)
    combined = readme + "\n" + hash_src
    assert "SHA-256" in combined or "sha256" in combined.lower()
    assert "发布声明" in combined
    assert "失陷" in combined
    assert "不是签名" in combined or "not a signature" in combined.lower()
