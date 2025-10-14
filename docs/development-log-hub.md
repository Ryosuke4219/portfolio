---
layout: default
title: Development Log Hub
description: 開発進捗・QAテレメトリのログをカテゴリ別に集約したナビゲーション
hub_sections:
  - title: QA / CI レポート
    intro: CI の信頼性スナップショットやテレメトリ出力を自動生成ファイルと共に保管。
    path: docs/reports/
  - title: タスク・レトロログ
    intro: スプリントで発生したフォローアップや振り返りの記録。
    path: docs/tasks/
  - title: 検証エビデンス
    intro: 手動検証・影計測の観測ログや証跡のまとめ。
    path: docs/evidence/
---

# Development Log Hub

開発進捗や QA テレメトリに関する Markdown ログをカテゴリ単位で整理しました。以下の注目ログとカテゴリ別インデックスから最新の記録にアクセスできます。

## 注目ログ

- [週次サマリ](./weekly-summary.md): `just weekly-summary` で生成される障害サマリと KPI ハイライト。
- [最新の CI 信頼性レポート](./reports/latest.md): 直近 7 日間のパスレートとフレークテストランキング、ソース JSON へのリンク付き。
- [進捗レビュー（2025-10-04）](https://github.com/Ryosuke4219/portfolio/blob/main/04/progress-2025-10-04.md): Provider 統合や影計測の検証ログをまとめた進捗ノート。
- [コミットサマリ 610-776](./reports/commit-summary-610-776.md): 直近 PR 群の変更要約とフォローアップタスク。

## カテゴリ別インデックス

{% assign all_pages = site.pages | where: "extname", ".md" %}
{% assign filtered_pages = all_pages | where_exp: "p", "p.path != 'docs/development-log-hub.md'" %}
{% for section in page.hub_sections %}
  {% assign entries = filtered_pages | where_exp: "p", "p.path contains section.path" | sort: "path" | reverse %}
  {% if entries.size > 0 %}
### {{ section.title }}
{{ section.intro }}

<ul>
  {% for entry in entries %}
    {% assign label = entry.data.title | default: entry.basename %}
    <li><a href="{{ entry.url | relative_url }}">{{ label }}</a>{% if entry.data.description %}<br /><small>{{ entry.data.description }}</small>{% endif %}</li>
  {% endfor %}
</ul>
  {% endif %}
{% endfor %}

---

### 外部配置ログ

- [Shadow Roadmap](./04-llm-adapter-shadow-roadmap.md): LLM Adapter のマイルストーンとリスク整理。
- [Daily Review Checklist](./daily-review-checklist.md): 日次レビュー用のチェックリスト。
- [04 LLM Adapter 進捗レビュー（2025-10-04）](https://github.com/Ryosuke4219/portfolio/blob/main/04/progress-2025-10-04.md): レポジトリ外配置のため外部参照で提供。
