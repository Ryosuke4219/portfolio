from __future__ import annotations

from pathlib import Path


def test_weekly_summary_card_provides_locale_variants() -> None:
    include = Path("docs/_includes/weekly-summary-card.md").read_text(encoding="utf-8")

    assert "週次サマリを詳しく読む →" in include, "日本語版の週次カード文言が見つかりません"
    assert "/weekly-summary.html" in include, "日本語版の週次カードリンクが不正です"

    assert "Read the weekly summary →" in include, "英語版の週次カード文言が見つかりません"
    assert "/en/weekly-summary.html" in include, "英語版の週次カードリンクが不正です"


def test_ja_index_loads_japanese_weekly_summary_card() -> None:
    text = Path("docs/index.md").read_text(encoding="utf-8")
    expected = '{% include weekly-summary-card.md locale="ja" %}'
    assert (
        expected in text
    ), "日本語トップページが日本語ロケールの週次カードを読み込んでいません"


def test_en_index_loads_english_weekly_summary_card() -> None:
    text = Path("docs/en/index.md").read_text(encoding="utf-8")
    expected = '{% include weekly-summary-card.md locale="en" %}'
    assert (
        expected in text
    ), "英語トップページが英語ロケールの週次カードを読み込んでいません"
