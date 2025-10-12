# 04 LLMアダプタ 要件・仕様書（SRS v1.0 / 2025-09-30 JST）

## 1. 目的・範囲

* 複数LLMプロバイダを**共通SPI**で扱い、以下3機能を提供する。
  * **直列**（sequential）：優先順に試行し**最初の成功**を返す。
  * **並列**（parallel-any / parallel-all）：同時実行。anyは**最初の成功**を返し、allは**全結果収集**。
  * **合議制**（consensus）：複数結果を**戦略的に集約**して**単一結論**を返す。
* 実行ごとの**ロギング／メトリクス／コスト推定**を一元管理。**RPM**・**同時実行数**・**バックオフ**・**シャドー実行**に対応。

## 2. 用語（RFC2119準拠）

* MUST/SHOULD/MAY：必須／推奨／任意。
* Provider：LLM呼び出し実装。**ProviderSPI**を満たす。
* Shadow：採択に影響しない並行実行（計測・比較目的）。

## 3. 公開インターフェース（最小）

```python
# SPI
class ProviderSPI(Protocol):
    def name(self) -> str: ...
    def capabilities(self) -> set[str]: ...
    def invoke(self, request: ProviderRequest) -> ProviderResponse: ...

@dataclass
class ProviderRequest:
    model: str                # MUST: 非空
    prompt: str = ""
    messages: Sequence[Mapping[str, Any]] | None = None
    max_tokens: int | None = 256
    temperature: float | None = None
    top_p: float | None = None
    stop: tuple[str, ...] | None = None
    timeout_s: float | None = 30
    metadata: Mapping[str, Any] | None = None
    options: dict[str, Any] = field(default_factory=dict)

@dataclass
class TokenUsage:
    prompt: int = 0
    completion: int = 0
    @property
    def total(self) -> int: return self.prompt + self.completion

@dataclass
class ProviderResponse:
    text: str
    latency_ms: int
    token_usage: TokenUsage | None = None
    model: str | None = None
    finish_reason: str | None = None
    tokens_in: int | None = None      # deprecated alias
    tokens_out: int | None = None     # deprecated alias
    raw: Any | None = None            # 生レスポンス

# ランナーモード
class RunnerMode(Enum):
    SEQUENTIAL = "sequential"
    PARALLEL_ANY = "parallel_any"
    PARALLEL_ALL = "parallel_all"   # 内部用（consensusの前段）
    CONSENSUS = "consensus"
```

## 4. ランナー構成

### 4.1 RunnerConfig（例）

* MUST:
  * `mode: RunnerMode`
  * `max_concurrency: int`（例: 4）
  * `rpm: int | None`（全体レート。MVPではグローバル1分窓）
  * `backoff: BackoffPolicy`（rate-limit待機・リトライ遷移）
* SHOULD:
  * `shadow_provider: ProviderSPI | None`
  * `metrics_path: str | Path | None`（JSONL）
* ConsensusConfig（SHOULD）:
  * `strategy: "majority_vote" | "max_score" | "weighted_vote"`
  * `quorum: int`（既定=2）
  * `tie_breaker: "min_latency" | "min_cost" | "stable_order"`
  * `schema: JSONSchema | None`（JSONの整合確認）
  * `judge: Judge | None`（スコアラー）
  * `provider_weights: dict[str, float]`（weighted用）

### 4.2 BackoffPolicy（MUST）

* `rate_limit_sleep_s: float`（例: 0.05）
* `timeout_next_provider: bool`（Timeout時に次候補へ）
* `retryable_next_provider: bool`（Retriable時に次候補へ／リトライ方針）

## 5. 実行仕様

### 5.1 直列（sequential）MUST

* 優先順に `invoke()` を実行。成功で即返す。
* 例外分類：
  * 非再試行：`AuthError | ConfigError` → 次候補へ。
  * 再試行：`RateLimitError | RetriableError | TimeoutError` → Backoff適用後に再試行 or 次候補。
  * `ProviderSkip` → 次候補。
* 全滅時：`AllFailedError`。

### 5.2 並列（parallel_any / parallel_all）MUST

* **any**：全候補を同時実行。**最初の成功**で採択し**他Futureをキャンセル**。
* **all**：全候補の**成功/失敗**を収集（consensus前段）。
* `max_concurrency` と `rpm` を遵守（共有トークンバケット＋Semaphore）。
* キャンセル時の`CancelledError`は握り潰さず記録（SHOULD）。

### 5.3 合議制（consensus）MUST

* 前段で `parallel_all` により**全候補**（成功/失敗）を収集。
* 候補：`{provider_id, response|error, latency_ms, token_usage, cost_estimate?}`
* **戦略**：
  * **majority_vote**（MUST）：
    * 文字列：`trim→空白圧縮→小文字化`の**正規化**後、完全一致で投票。
    * JSON：`schema` があれば型整合→キー/値一致で投票。全キー一致を最優先。
  * **max_score**（SHOULD）：`judge` の `quality_score∈[0,1]` 最大を採択。
  * **weighted_vote**（MAY）：`provider_weights`で重み付き合算。
* **クォーラム**：`quorum`（既定2）に達すれば採択。未達時は `judge` → 同点は `tie_breaker`。
* **TieBreaker**（MUST）：`min_latency` → `min_cost` → `stable_order` の順で決定性を担保。
* **説明可能性**：戦略・投票/スコア・クォーラム・タイブレーク理由をメトリクスに残す。

## 6. シャドー実行（MUST）

* 指定あれば本系と**並行実行**。**採択へ影響を与えない**。
* メトリクス：`shadow_provider_id, shadow_latency_ms, shadow_outcome` を記録。

## 7. メトリクス／ロギング（JSONL推奨）

* MUST（各候補/採択）:
  * `run_id, mode, providers, provider_id, latency_ms, token_usage, cost_estimate, retries, outcome(success/skip/error)`
* MUST（合議）:
  * `strategy, quorum, votes|scores, chosen_provider, tie_breaker, reason`
* SHOULD：`shadow_*` フィールド、`error_type`、`attempts`

## 8. コマンドライン（CLI）

* MUST:
  * `--mode {sequential,parallel-any,parallel-all,consensus}`
  * `--max-concurrency N` / `--rpm R`
* `run_compare` 系 CLI（`python adapter/run_compare.py`）:
  * `--providers <path1.yaml,path2.yaml,...>` は**カンマ区切りの複数パス**（相対/絶対）を受け取り、指定順で Runner に渡す（MUST）。
  * `--prompts <tasks.jsonl>` を MUST で要求し、比較対象のゴールデンセットを読み込む。
  * `--metrics <path>` を指定しない場合は `data/runs-metrics.jsonl` に JSONL を追記する。明示指定時はそのパス配下（例：`out/metrics.jsonl`）に保存する（SHOULD）。
* `llm-adapter` 単体実行（`pip install -e .` 経由で提供されるエントリポイント）:
  * MUST で `--provider <provider.yaml>` を受け付け、単一プロバイダ構成ファイルを読み込む。
  * `--out <dir>` は任意指定（MAY）で、指定があれば未存在ディレクトリを作成して `metrics.jsonl` を生成・追記する。比較ランナーと同一フォーマット（JSONL）でメトリクスを出力する。
  * `--out` を省略した場合はカレントディレクトリに `metrics.jsonl` を生成・追記する（SHOULD）。
* Typer CLI は `run-compare` サブコマンドを提供しない。比較実行は `python adapter/run_compare.py` を介して行う。
* 合議関連（SHOULD）:
  * `--aggregate majority_vote|max_score|weighted_vote`
  * `--quorum K` / `--tie-breaker min_latency|min_cost|stable_order`
  * `--schema path.json` / `--judge name`
  * `--weights openai=1.0,gemini=0.9,...`
* I/O（SHOULD）：`--prompt-file path` / `--prompts text` / `--format text|json|jsonl` / `--out path` / `--metrics path`

## 9. エラーポリシー（MUST）

* 正規化された例外型：`AuthError, RateLimitError, RetriableError, TimeoutError, ProviderSkip, ConfigError, ParallelExecutionError, AllFailedError`
* 並列時の致命エラーは `ParallelExecutionError` に**個別失敗**を内包（SHOULD）。

## 10. 非機能要件

* **決定性**（MUST）：同一入力・同一候補集合→常に同じ最終出力。
* **性能**（SHOULD）：`max_concurrency`と`rpm`内でスループット最大化。
* **可観測性**（MUST）：JSONL出力は後処理（集計・可視化）可能な構造。
* **型・Lint・CI**（MUST）：`mypy(strict) / ruff / black / pytest / GitHub Actions`
* **セキュリティ**（MUST）：APIキーは秘匿。ログに出力しない。

## 11. 受け入れ基準（抜粋）

* **sequential**：優先1が`RateLimitError`で再試行後失敗→優先2が成功→**優先2の結果**。
* **parallel-any**：3プロバイダ同時実行→**最初の成功**を返し他はキャンセル。
* **consensus(majority, quorum=2)**：3候補中2が一致→**一致値**を返す。全バラけ→`judge`または`min_latency`で一意決定。
* **メトリクス**：戦略・投票数orスコア・タイブレーク理由が記録される。

## 12. テスト計画（要点）

* 単体：直列の再試行/Skip/例外分類、並列の早期採択/キャンセル/RPM、合議の多数決/クォーラム/同点/スキーマ、CLI引数伝播。
* プロパティ（任意）：合議の**決定性**。
* 統合：シャドーが採択に影響しない、メトリクス項目の完全性。

## 13. 既知制約（MVP）

* **ストリーミング合議**は未対応（将来対応）。
* **RPMは全体レート**のみ（プロバイダ別レートは将来拡張）。
* `Judge`はデフォルト無効（レイテンシ増対策）。
* `weighted_vote` は任意実装。

## 14. 互換性・移行

* 既存`ProviderResponse.tokens_in/out`は**非推奨エイリアス**。`token_usage`への移行を推奨。
* 既存Runnerは保持し、`RunnerMode`追加で**後方互換**を確保。

---

必要なら、このSRSを`docs/requirements/llm-adapter.md`として配置し、CLI実装・テスト項目と紐づけた**受け入れチェックリスト**（P0/P1/P2）を同梱します。
