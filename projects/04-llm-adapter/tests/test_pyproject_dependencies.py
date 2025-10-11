from __future__ import annotations

from pathlib import Path
import re

try:  # Python 3.11+
    import tomllib  # type: ignore[attr-defined]
except ModuleNotFoundError:  # pragma: no cover - fallback for older runtimes
    import tomli as tomllib  # type: ignore[assignment]


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PYPROJECT_PATH = PROJECT_ROOT / "pyproject.toml"
REQUIREMENTS_PATH = PROJECT_ROOT / "requirements.txt"


def _normalize_requirement(requirement: str) -> str:
    head = re.split(r"[<>=!~]", requirement, maxsplit=1)[0]
    package = head.split("[", 1)[0]
    return package.strip().lower()


def _load_pyproject_packages() -> tuple[set[str], dict[str, set[str]]]:
    data = tomllib.loads(PYPROJECT_PATH.read_text(encoding="utf-8"))
    project = data.get("project", {})
    base_deps = {
        _normalize_requirement(item)
        for item in project.get("dependencies", [])
    }
    optional_raw = project.get("optional-dependencies", {})
    optional: dict[str, set[str]] = {}
    for extra, entries in optional_raw.items():
        optional[extra] = {_normalize_requirement(item) for item in entries}
    return base_deps, optional


def _load_requirements_packages() -> set[str]:
    packages: set[str] = set()
    for line in REQUIREMENTS_PATH.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        packages.add(_normalize_requirement(stripped))
    return packages


def test_requirements_covered_by_pyproject() -> None:
    base_deps, optional = _load_pyproject_packages()
    optional_union: set[str] = set().union(*optional.values()) if optional else set()
    declared_packages = base_deps | optional_union
    requirements_packages = _load_requirements_packages()

    missing = sorted(requirements_packages - declared_packages)
    assert not missing, (
        "requirements.txt に含まれるライブラリが pyproject.toml で宣言されていません: "
        f"{', '.join(missing)}"
    )
