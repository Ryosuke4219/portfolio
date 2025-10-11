"""Guardrails for README shadow adapter references."""

from pathlib import Path

ALLOWED_SHADOW_TERMS: tuple[str, ...] = (
    "shadow 版",
    "shadow 実行",
    "shadow/fallback",
)

RED_WORDS: tuple[str, ...] = (
    "projects/04-llm-adapter-shadow",
    "04-llm-adapter-shadow",
)


def test_readme_shadow_references_stay_within_allowlist() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")

    for red_word in RED_WORDS:
        assert red_word not in readme, (
            "README.md に禁止ワード {word!r} が含まれています。"
            "shadow に関する説明は {allowed} などの表記に揃えてください。"
        ).format(word=red_word, allowed=", ".join(ALLOWED_SHADOW_TERMS))
