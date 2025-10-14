{% assign summary = site.data.weekly_summary %}
# LLM Adapter 週次サマリ

## {{ summary.report_date }} 時点の失敗サマリ

- 失敗総数: {{ summary.total_failures }}

| Rank | Failure Kind | Count |
| ---: | :----------- | ----: |
{% for failure in summary.top_failure_kinds %}| {{ forloop.index }} | {{ failure.name }} | {{ failure.count }} |
{% endfor %}

### OpenRouter HTTP Failures

| Rank | 種別 | Count | Rate% |
| ---: | :---- | ----: | ----: |
{% for failure in summary.openrouter_failures %}| {{ forloop.index }} | {{ failure.label }} | {{ failure.count }} | {{ failure.rate_percent }} |
{% endfor %}
