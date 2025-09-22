# 仕様 #1：仕様 → 構造化テスト（決定的生成）

## 目的と価値
確定した仕様（Markdown 等）を**機械可読なテストケース**へ変換し、CLI/CI で決定的に回せる状態を提供。
- **価値**：テスト設計の手戻り削減、再現性の担保、変更差分の明確化。

## 前提・入力
- 仕様は「機能単位の見出し」「前提条件」「入力」「期待結果」を備えたテンプレートで記述。
- 仕様はリポジトリ内でバージョン管理される（例：`projects/01-spec2cases/spec.md`）。

## 出力（データ契約）
- `cases.generated.json`：テスト ID、タグ、前提、手順、期待結果を持つ配列。
- `junit.xml`：各ケースの実行結果を JUnit 互換で出力（CI 収集用）。

## 受け入れ条件（AC）
- 仕様の**必須フィールド欠落**時に変換を拒否し、理由を明示。  
- JSON スキーマに適合（`id/string`、`tags/string[]`、`steps[]`、`expected[]` など）。  
- 同一 ID の重複検出（hard fail）。

## 非機能要件
- 仕様 1,000 行規模で 1 分未満の変換完了（ローカル基準）。
- 変換結果の差分は Git でレビュー可能な最小粒度。

## リスクと緩和
- 曖昧な仕様 → **Lint 的チェック**（必須節の欠落/曖昧語検出）を仕様側で導入。
- ID 設計の崩壊 → 自動採番ではなく**人間定義 + 静的重複検出**。

## 処理フロー（擬似コード）
```text
1. Markdown をパースし、機能ごとのセクションを抽出。
2. 必須フィールド（前提・入力・期待結果）の有無を検証。
3. ステップをシリアライズし、`steps[]` 配列へ整形。
4. 重複 ID をハッシュセットで検知し、エラーとして返却。
5. cases.generated.json と JUnit スタブを生成。
```

## エラー・バリデーション設計
- **MissingFieldError**：テンプレートに不足がある場合。原因セクションとヒントをメッセージに含める。
- **DuplicateIdError**：同一 ID を検出した場合。重複元のファイルパスと行番号を提示する。
- **SchemaMismatchError**：JSON スキーマ検証に失敗した場合。追加フィールドや型不整合を列挙。
- いずれも CLI 終了コード `1` とし、CI で早期検知できるようにする。

## CLI / API インターフェース例
```bash
$ spec2cases convert projects/01-spec2cases/spec.md \
    --out-json artifacts/cases.generated.json \
    --out-junit artifacts/junit.xml \
    --strict-template
```

- `--strict-template` でテンプレ違反を fail fast。
- `--lint` オプションで曖昧語の出現率を計測し、閾値超過時は警告（CI では warning として扱う）。
