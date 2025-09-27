# UTF-8 に統一
[Console]::InputEncoding  = [System.Text.UTF8Encoding]::new()
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$env:PYTHONIOENCODING = "utf-8"

# 仮想環境が未作成の場合は作成
if (-not (Test-Path .venv)) {
    python -m venv .venv
}

# 仮想環境を有効化
. .\.venv\Scripts\Activate.ps1

# 依存関係をインストール
pip install -e .

Write-Host "OpenAI/Gemini の API キーを .env に記入してください" -ForegroundColor Yellow
if (-not (Test-Path .env)) {
    @(
        "OPENAI_API_KEY=",
        "GEMINI_API_KEY="
    ) | Set-Content -Encoding UTF8 .env
}

Write-Host "サンプル実行:" -ForegroundColor Cyan
Write-Host "llm-adapter --provider examples/providers/openai.yml --prompt '日本語で1行、自己紹介して'"
