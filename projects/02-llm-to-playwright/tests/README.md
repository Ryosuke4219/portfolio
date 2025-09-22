# 自動生成E2Eテストの堅牢化メモ

## セレクタ・ガード方針
- **data-testid を最優先**: 生成ステップでもテスト実装でも、DOM変動に強い data-testid 属性を必須とする。
- **ARIA / ロールでのフェイルセーフ**: data-testid が与えられない要素は role / aria-label の利用を検討し、最後の手段としてテキスト照合を許可。
- **XPath 禁止**: メンテナンスコストと brittleness を避けるため XPath は生成対象から除外。
- **Form 操作は locator 経由**: `page.getByTestId()` で locator を作り、その API 経由で `fill` / `click` を実行。CSS セレクタを直接使うのは一時的なデバッグ用途に限定。

## ビジュアル差分（スモーク）
- `projects/02-llm-to-playwright/tests/generated/__snapshots__/` にゴールデンファイルを保持。
- スモーク用途としてダッシュボード1枚のみを対象とし、最小限の差分検知にとどめる。
- 変更が正当な場合はゴールデンファイルを更新し、差分は `test-results/snapshot-diffs/` にテキスト形式で出力される。

## a11y スキャン
- `axe-core` スタブを組み込み、img の `alt` 欠如や landmark 不在などの初歩的な欠陥を検知。
- `a11y-pages.csv` に列挙したページを一括で走査し、`violations` が空であることを保証。

## Data-driven 実行
- `login-cases.json` に成功 / 失敗パターンを定義し、ループで Playwright テストを生成。
- CSV (`a11y-pages.csv`) も読み込み、ファイル形式に依存しないパラメトリック実行の例を示す。
- テスト追加時は JSON/CSV のみを編集すればよく、コード変更を最小化できる構造とした。
