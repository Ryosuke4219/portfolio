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


def test_readme_llm_adapter_section_highlights_cli_usage() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")

    expected_snippets = (
        "4. **04: llm-adapter —",
        "### 4. llm-adapter —",
        "llm-adapter --provider adapter/config/providers/openai.yaml \\",
        "    --prompts examples/prompts/ja_one_liner.jsonl --out out/",
        "* `out/metrics.jsonl`",
    )

    for snippet in expected_snippets:
        assert (
            snippet in readme
        ), f"README.md に llm-adapter の CLI 手順が {snippet!r} 形式で記載されていません。"


def test_llm_adapter_readme_does_not_reference_missing_paths() -> None:
    readme = Path("projects/04-llm-adapter/README.md").read_text(encoding="utf-8")

    missing_examples = [
        "path/to/judge.yaml",
        "path/to/output_schema.json",
    ]

    offenders = [example for example in missing_examples if example in readme]

    assert not offenders, (
        "projects/04-llm-adapter/README.md に存在しないパスのプレースホルダーが残っています: {targets}"
    ).format(targets=", ".join(offenders))


def test_readme_shadow_references_stay_within_allowlist() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")

    for red_word in RED_WORDS:
        assert red_word not in readme, (
            "README.md に禁止ワード {word!r} が含まれています。"
            "shadow に関する説明は {allowed} などの表記に揃えてください。"
        ).format(word=red_word, allowed=", ".join(ALLOWED_SHADOW_TERMS))
