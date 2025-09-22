# データ契約（スキーマの意図）

> 実装しない前提の**設計仕様**として、フィールド意図だけを定義。

## cases.json（#1）
| フィールド | 型 | 必須 | 説明 |
| --- | --- | --- | --- |
| `id` | string | ✅ | テストケース識別子。人間が命名し、重複禁止。 |
| `title` | string | ✅ | 仕様の見出しやシナリオ名をそのまま使用。 |
| `tags` | string[] | ✅ | `smoke`, `regression`, `a11y` などレビューに必要な分類。 |
| `preconditions` | string[] | ✅ | 実行前に満たすべき前提。複数可。 |
| `steps` | object[] | ✅ | `{ action: string, input?: any }` を要素とする実行手順。 |
| `expected` | string[] | ✅ | 確認ポイント。手順と同数でなくても可。 |
| `notes` | string[] | ⭕ | 任意メモ。曖昧な仕様や TODO を蓄積。 |

### サンプル
```jsonc
{
  "id": "TC-LOGIN-001",
  "title": "ログイン成功",
  "tags": ["smoke", "regression"],
  "preconditions": ["ユーザーが登録済み"],
  "steps": [
    { "action": "フォームにメールを入力", "input": "user@example.com" },
    { "action": "フォームにパスワードを入力", "input": "••••••" },
    { "action": "ログインボタンをクリック" }
  ],
  "expected": [
    "ダッシュボードにリダイレクトされる",
    "ヘッダーにユーザー名が表示される"
  ]
}
```

## junit.xml（共通）
| 要素 | 必須属性 | 補足 |
| --- | --- | --- |
| `testsuite` | `name`, `tests`, `failures`, `errors`, `skipped`, `time`, `timestamp`, `hostname` | 解析しやすいように UTC timestamp を ISO-8601 で記録。 |
| `testcase` | `classname`, `name`, `time` | `classname` はコンポーネント名、`name` は AC/仕様の痕跡を残す。 |
| `failure` / `error` / `skipped` | `message`, `type` | フレーク解析用に `type` を分類。長いログは `system-out` ではなく外部ファイルに。 |
| `system-out` | - | 主要な情報のみを要約。フルログは S3 / Artifacts へ退避。 |

## runs-metrics.jsonl（#4）
| フィールド | 型 | 説明 |
| --- | --- | --- |
| `ts` | string | ISO-8601 UTC。影実行と本番レスポンスを同期させる。 |
| `trace_id` | string | 呼び出しトレース。影実行とフォールバックを紐付け。 |
| `model` | string | 使用モデル名（`gpt-4.1-mini` 等）。 |
| `ok` | boolean | 成功判定。False なら `error_type` が必須。 |
| `latency_ms` | number | 呼び出しに要した時間。フォールバックを含む場合は合計。 |
| `tokens` | number | 入出力トークン合計。計測不能な場合は `null`。 |
| `fallbacks` | number | フォールバック段数。0 なら本番経路のみ。 |
| `error_type` | string? | `'timeout'`, `'rate_limit'`, `'parse'` など分類。 |
| `cost_estimate` | number? | ベンダに依存しない概算コスト（USD 等）。 |
| `shadow_delta` | number? | 本番と影実行の出力差異スコア。 |

### JSONL 例
```jsonl
{"ts":"2024-05-01T12:00:00Z","trace_id":"req-001","model":"gpt-4.1-mini","ok":true,"latency_ms":920,"tokens":1860,"fallbacks":0,"cost_estimate":0.12,"shadow_delta":0.04}
{"ts":"2024-05-01T12:00:02Z","trace_id":"req-002","model":"gpt-4.1-mini","ok":false,"latency_ms":3100,"tokens":960,"fallbacks":2,"error_type":"timeout","cost_estimate":0.18}
```
