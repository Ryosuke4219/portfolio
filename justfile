set shell := ["bash", "-c"]

# デフォルトは利用可能なレシピ一覧を表示
default:
	just --list

# 依存関係とブラウザスタブをまとめて初期化
setup:
	set -euo pipefail
	if [ "${OS:-}" = "Windows_NT" ]; then
		if command -v pwsh >/dev/null 2>&1; then
			pwsh -NoProfile -File scripts/bootstrap.ps1
		else
			powershell.exe -NoProfile -File scripts/bootstrap.ps1
		fi
	else
		bash scripts/bootstrap.sh
	fi

node-test:
        set -euo pipefail
        npm run spec:validate
        npm run e2e:gen
        bash scripts/run-node-suite.sh
        npm run ci:analyze
        npm run ci:issue
        node --test tests/e2e-shadow.test.mjs

python-test:
        set -euo pipefail
        PYTHONPATH=projects/04-llm-adapter \
        ./.venv/bin/pytest -q projects/04-llm-adapter/tests

# Node と Python のテストスイートを一括実行
test: node-test python-test

# JS 構文チェックと Python バイトコード検証
lint:
        set -euo pipefail
        JS_FILES=$(find . -type f \( -name '*.mjs' -o -name '*.js' \))
        if [ -n "${JS_FILES}" ]; then
                for file in ${JS_FILES}; do
                        node --check "${file}"
                done
        else
                echo "No JavaScript modules found"
        fi
        PYTHONPATH=projects/04-llm-adapter \
        ./.venv/bin/python -m compileall projects/04-llm-adapter/adapter

# 週次サマリ生成
weekly-summary:
        set -euo pipefail
        PYTHONPATH=projects/04-llm-adapter \
        ./.venv/bin/python - <<'PY'
from pathlib import Path

from tools.report.metrics.data import (
    build_failure_summary,
    build_openrouter_http_failures,
    load_metrics,
)
from tools.report.metrics.weekly_summary import update_weekly_summary

metrics_path = Path("artifacts/runs-metrics.jsonl")
weekly_path = Path("docs/weekly-summary.md")

if metrics_path.exists():
    metrics = load_metrics(metrics_path)
else:
    metrics = []

failure_total, failure_summary = build_failure_summary(metrics)
_, openrouter_http_failures = build_openrouter_http_failures(metrics)
update_weekly_summary(
    weekly_path,
    failure_total,
    failure_summary,
    openrouter_http_failures=openrouter_http_failures,
)
PY

# Python プロジェクトのカバレッジ付きレポート生成
report:
        set -euo pipefail
        just test
        PYTHONPATH=projects/04-llm-adapter \
        ./.venv/bin/pytest --cov=adapter --cov-report=xml --cov-report=term-missing projects/04-llm-adapter/tests
        just weekly-summary
