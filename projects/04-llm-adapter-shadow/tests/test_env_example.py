"""`.env.example` の必須キー検証。"""

from __future__ import annotations

from pathlib import Path
import tomllib

REQUIRED_KEYS: tuple[str, ...] = (
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "OPENROUTER_API_KEY",
    "OPENROUTER_BASE_URL",
)


def _load_env(path: Path) -> dict[str, object]:
    lines = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        key, value = stripped.split("=", maxsplit=1)
        lines.append(f"{key} = \"{value}\"")
    return tomllib.loads("\n".join(lines))


def test_env_example_contains_required_keys() -> None:
    env_path = Path(__file__).resolve().parent.parent / ".env.example"
    env_values = _load_env(env_path)

    missing_keys = sorted(key for key in REQUIRED_KEYS if key not in env_values)
    assert not missing_keys, f"missing keys: {', '.join(missing_keys)}"
