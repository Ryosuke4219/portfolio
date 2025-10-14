{% assign summary = site.data.weekly_summary %}
{% assign top_failure_labels = summary.top_failure_kinds | map: 'name' %}
{% assign card_link_text = include.link_text | default: '週次サマリを詳しく読む →' %}
{% assign card_link_href = include.link_url | default: '/weekly-summary.html' %}
### Weekly QA Snapshot — {{ summary.report_date }}
- TotalTests: {{ summary.total_tests }}
- PassRate: {{ summary.pass_rate_percent }}
- NewDefects: {{ summary.new_defects }}
- TopFailureKinds: {% if top_failure_labels and top_failure_labels.size > 0 %}{{ top_failure_labels | join: ', ' }}{% else %}-{% endif %}
[{{ card_link_text }}]({{ card_link_href | relative_url }})
