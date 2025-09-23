set shell := ["bash", "-c"]

# デフォルトは利用可能なレシピ一覧を表示
default:
	just --list

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
	./.venv/bin/pytest -q projects/04-llm-adapter-shadow/tests

test: node-test python-test

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
	./.venv/bin/python -m compileall projects/04-llm-adapter-shadow

report:
	set -euo pipefail
	./.venv/bin/pytest --cov=projects/04-llm-adapter-shadow --cov-report=xml --cov-report=term-missing projects/04-llm-adapter-shadow/tests
