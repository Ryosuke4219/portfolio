# 04. LLM Adapter — Shadow Execution & Error Handling (Minimal)

**JP:** プライマリ結果はそのまま採用しつつ、裏で別プロバイダに“影実行”してメトリクスだけを記録する PoC。タイムアウト/レート制限/形式不正などの**異常系固定セット**も最小実装で再現します。

**EN:** Minimal adapter with **shadow execution** (primary result + background run on another provider, metrics-only) and a tiny **error-case suite** (timeout / rate limit / invalid JSON).

## Why
- 本番の意思決定は変えずに品質/レイテンシ差分を継続測定 → ベンダ選定や回帰検知に効く
- 異常系を**明示的に再現**できるため、フォールバックや再試行の動作確認が容易

## Layout
```
projects/04-llm-adapter-shadow/
  ├─ src/llm_adapter/
  │   ├─ __init__.py
  │   ├─ provider_spi.py
  │   ├─ errors.py
  │   ├─ metrics.py
  │   ├─ utils.py
  │   ├─ runner.py
  │   └─ providers/mock.py
  ├─ tests/
  │   ├─ test_err_cases.py
  │   └─ test_shadow.py
  ├─ demo_shadow.py
  ├─ pyproject.toml
  └─ requirements.txt
```

## Quick Start
```bash
# repo root
cd projects/04-llm-adapter-shadow
python3 -m venv .venv && source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python demo_shadow.py

# run tests
pytest -q
```

## What it demonstrates
- **Shadow execution:** `src/llm_adapter/shadow.py` — primaryを採用しつつ、影で別Providerを実行；差分は `artifacts/runs-metrics.jsonl` へ。
- **Fallback path:** `runner.py` — `TimeoutError / RateLimitError / RetriableError` を捕捉して**次のProviderに切替**。
- **Mocked errors:** `providers/mock.py` — プロンプトに `[TIMEOUT]`, `[RATELIMIT]`, `[INVALID_JSON]` を含めると異常を発火。

## Notes
- 実プロバイダ統合は意図的に含めていません（**軽量のまま**にするため）。
- メトリクスはJSONLで軽く残すだけ（ダッシュボードなし）。
- 後続のLLM Adapter OSS本体とは**独立**して動きます（ポートフォリオ用サンプル）。
