# 日報チェックリスト

日報作成時に、以下の項目を毎日1回レビューすること。

## 📌 Review Input
- 公開APIの変更有無
- Deprecation Warning の有無
- 300行超の大規模差分がないか
- SRS 3章 ProviderSPI 要件との乖離点

## Lint & Typing
- ruff / mypy ログの失敗箇所サマリ
- 「論理変更を伴う lint 修正」が混入していないか

## Feature Implementation
- 新機能が SRS（4,5,6,7,9章）の必須項目を満たすか
- CLI 引数の整合性（--weights / --tie-breaker / --aggregate）
- メトリクスに必須フィールドが揃っているか（providers[], retries, outcome, shadow_*）

## CI / Logs
- pytest の失敗ログ → 再現性あるか / flaky疑いか
- CI実行時間が異常に延びていないか
- 直列・並列ランナーが正しくキャンセル/再試行しているか

## Metrics Digest
- retry率の急増はないか
- shadow実行の成功/失敗の偏り
- token_usage の逸脱やコスト増加

## Documentation
- CHANGELOG に記録すべき差分（Added/Changed/Fixed）
- ADR に起こすべき決定（Context / Decision / Consequences）

## Meta / 校則監査
- PR単位で ≤300行に収まっているか
- commit メッセージが Conventional Commits に従っているか
- SRS準拠度チェックの残課題リスト
