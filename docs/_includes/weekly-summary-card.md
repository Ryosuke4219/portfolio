{% assign summary = site.data.weekly_summary %}
{% assign top_failure_labels = summary.top_failure_kinds | map: 'name' %}
### Weekly QA Snapshot — {{ summary.report_date }}

- TotalTests: {{ summary.total_tests }}
- PassRate: {{ summary.pass_rate_percent }}
- NewDefects: {{ summary.new_defects }}
- TopFailureKinds: {% if top_failure_labels and top_failure_labels.size > 0 %}{{ top_failure_labels | join: ', ' }}{% else %}-{% endif %}

[週次サマリを詳しく読む →]({{ '/weekly-summary.html' | relative_url }})
