from __future__ import annotations

from pathlib import Path


def test_en_index_overrides_weekly_summary_card_link() -> None:
    text = Path("docs/en/index.md").read_text(encoding="utf-8")
    expected = (
        "{% include weekly-summary-card.md link_text=\"Read the weekly summary\" "
        "link_url=\"/en/weekly-summary.html\" %}"
    )
    assert expected in text, "英語版トップページで週次カードリンクが英語表記になっていません"


def test_weekly_summary_card_default_link_is_japanese() -> None:
    include = Path("docs/_includes/weekly-summary-card.md").read_text(encoding="utf-8")
    assert "週次サマリを詳しく読む →" in include, "週次カードのデフォルト文言が日本語ではありません"
    assert "/weekly-summary.html" in include, "週次カードのデフォルトリンクが日本語版を指していません"


def test_ja_index_uses_default_weekly_summary_card() -> None:
    text = Path("docs/index.md").read_text(encoding="utf-8")
    assert "{% include weekly-summary-card.md %}" in text, "日本語版トップページで週次カードがデフォルト呼び出しではありません"
