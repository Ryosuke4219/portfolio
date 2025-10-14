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


def test_readme_quick_start_commands_are_scoped_to_section() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")

    heading = "### Quick Start (JA / EN)"
    assert readme.count(heading) == 1, "Quick Start セクション見出しを1箇所に統一してください。"

    heading_position = readme.index(heading)
    quick_start_commands = (
        "just setup",
        "just test",
        "just lint",
        "just report",
        "just openrouter-stream-probe",
        "just openrouter-stats",
    )

    for command in quick_start_commands:
        assert command in readme, f"Quick Start セクションから {command!r} が見つかりません。"
        assert (
            readme.index(command) > heading_position
        ), f"Quick Start コマンド {command!r} は {heading!r} セクション以外に記載しないでください。"
def test_readme_quick_start_is_single_section() -> None:
    readme_lines = Path("README.md").read_text(encoding="utf-8").splitlines()

    quick_start_headings = [
        line for line in readme_lines if line.lower().startswith("### quick start")
    ]

    assert (
        len(quick_start_headings) == 1
    ), "README.md の Quick Start 見出しは単一のセクションに揃えてください。"

    duplicate_quick_start_bullets = [
        line
        for line in readme_lines
        if line.startswith("- ") and "Quick Start" in line
    ]

    assert not duplicate_quick_start_bullets, (
        "Quick Start 情報は箇条書きではなく Quick Start セクションに集約してください。"
    )

    heading_index = next(
        index
        for index, line in enumerate(readme_lines)
        if line.strip().lower() == "### quick start (ja / en)"
    )

    intro_lines = readme_lines[:heading_index]
    assert any(
        "Quick Start はこちら" in line for line in intro_lines
    ), "README.md 冒頭に Quick Start セクションへの短い導線を記載してください。"
    intro_mentions = [
        line
        for line in intro_lines
        if "Quick Start" in line and line.strip().startswith("- ")
    ]

    assert not intro_mentions, (
        "README.md 冒頭は Quick Start 箇条書きではなく Quick Start セクションへの導線に統一してください。"
    )
