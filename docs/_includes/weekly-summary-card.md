{% assign summary = site.data.weekly_summary %}
{% assign top_failure_labels = summary.top_failure_kinds | map: 'name' %}
{% assign locale = include.locale | default: page.lang | default: 'ja' %}
{% case locale %}
  {% when 'en' %}
    {% assign default_link_text = 'Read the weekly summary →' %}
    {% assign default_link_href = '/en/weekly-summary.html' %}
  {% else %}
    {% assign default_link_text = '週次サマリを詳しく読む →' %}
    {% assign default_link_href = '/weekly-summary.html' %}
{% endcase %}
{% assign card_link_text = include.link_text | default: default_link_text %}
{% assign card_link_href = include.link_url | default: default_link_href %}
### Weekly QA Snapshot — {{ summary.report_date }}
- TotalTests: {{ summary.total_tests }}
- PassRate: {{ summary.pass_rate_percent }}
- NewDefects: {{ summary.new_defects }}
- TopFailureKinds: {% if top_failure_labels and top_failure_labels.size > 0 %}{{ top_failure_labels | join: ', ' }}{% else %}-{% endif %}
[{{ card_link_text }}]({{ card_link_href | relative_url }})
