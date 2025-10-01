"""比較ランナー CLI。"""
from __future__ import annotations

import argparse
from enum import Enum
from pathlib import Path

try:
    from .core import runner_api
except ImportError:  # pragma: no cover - 直接実行時のフォールバック
    import sys

    PACKAGE_ROOT = Path(__file__).resolve().parent.parent
    if str(PACKAGE_ROOT) not in sys.path:
        sys.path.insert(0, str(PACKAGE_ROOT))
    from adapter.core import runner_api


class RunnerMode(str, Enum):
    """比較ランナーの実行モード."""

    SEQUENTIAL = "sequential"
    PARALLEL_ANY = "parallel_any"
    PARALLEL_ALL = "parallel_all"
    CONSENSUS = "consensus"

    @classmethod
    def from_raw(cls, raw: str) -> "RunnerMode":
        """CLI から渡された値を RunnerMode に変換する."""

        candidate = raw.strip().lower().replace("-", "_")
        return cls(candidate)

    @classmethod
    def cli_choices(cls) -> list[str]:
        """CLI に表示するモード選択肢."""

        values = {mode.value for mode in cls}
        hyphen_aliases = {value.replace("_", "-") for value in values}
        return sorted(values | hyphen_aliases)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="LLM Adapter 比較ランナー")
    parser.add_argument(
        "--providers",
        required=True,
        help="プロバイダ設定ファイル（カンマ区切り）",
    )
    parser.add_argument(
        "--prompts",
        required=True,
        help="ゴールデンタスク JSONL のパス",
    )
    parser.add_argument(
        "--repeat",
        type=int,
        default=1,
        help="各組み合わせの反復回数",
    )
    parser.add_argument(
        "--mode",
        choices=RunnerMode.cli_choices(),
        default="sequential",
        help="比較実行モード",
    )
    parser.add_argument(
        "--budgets",
        default=None,
        help="予算設定 YAML のパス",
    )
    parser.add_argument(
        "--metrics",
        default=None,
        help="メトリクス JSONL の出力先",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        help="ログレベル (INFO/DEBUG など)",
    )
    parser.add_argument(
        "--allow-overrun",
        action="store_true",
        help="予算超過時でも実行を継続する",
    )
    parser.add_argument(
        "--aggregate",
        help="複数応答の集約ストラテジ",
    )
    parser.add_argument(
        "--quorum",
        type=int,
        default=None,
        help="合意に必要な最小一致数 (consensus モード向け)",
    )
    parser.add_argument(
        "--tie-breaker",
        dest="tie_breaker",
        choices=["min_latency", "min_cost", "stable_order"],
        help="合意不能時のタイブレーク手法",
    )
    parser.add_argument(
        "--schema",
        default=None,
        help="構造化出力バリデーション用スキーマ JSON",
    )
    parser.add_argument(
        "--judge",
        default=None,
        help="判定プロバイダ設定ファイル (aggregate=judge など)",
    )
    parser.add_argument(
        "--weights",
        dest="weights",
        default=None,
        help="aggregate=weighted_vote 用の重み (例: openai=1.0,anthropic=0.5)",
    )
    parser.add_argument(
        "--max-concurrency",
        dest="max_concurrency",
        type=int,
        default=None,
        help="プロバイダ呼び出しの最大並列数",
    )
    parser.add_argument(
        "--rpm",
        type=int,
        default=None,
        help="1 分あたりの呼び出し上限",
    )
    return parser.parse_args()


def _parse_weights_arg(raw: str | None) -> dict[str, float] | None:
    if raw is None:
        return None
    items = [part.strip() for part in raw.split(",") if part.strip()]
    if not items:
        return None
    weights: dict[str, float] = {}
    for item in items:
        name, sep, value = item.partition("=")
        if sep != "=" or not name.strip():
            raise SystemExit("--weights は name=value,... 形式で指定してください")
        try:
            clean_value = value.strip()
            if not clean_value:
                raise ValueError
            weights[name.strip()] = float(clean_value)
        except ValueError as exc:  # pragma: no cover - argparse で捕捉
            raise SystemExit(f"--weights の値を数値に変換できません: {value}") from exc
    return weights


def _normalize_aggregate(raw: str | None) -> tuple[str | None, str | None]:
    if raw is None:
        return None, None
    candidate = raw.strip()
    if not candidate:
        return None, None
    normalized = candidate.lower().replace("-", "_")
    alias_map: dict[str, set[str]] = {
        "weighted_vote": {"weighted_vote", "weighted"},
        "majority_vote": {"majority_vote", "majority", "vote", "maj"},
        "max_score": {"max_score", "max", "score", "top"},
        "judge": {"judge", "llm_judge", "llmjudge"},
    }
    for key, aliases in alias_map.items():
        if normalized in aliases:
            return candidate, key
    return candidate, None


def main() -> int:
    args = _parse_args()
    aggregate_value, aggregate_kind = _normalize_aggregate(args.aggregate)

    provider_paths = [
        Path(p.strip()).expanduser().resolve()
        for p in args.providers.split(",")
        if p.strip()
    ]
    if not provider_paths:
        raise SystemExit("--providers に有効なパスが指定されていません")
    prompt_path = Path(args.prompts).expanduser().resolve()
    if not prompt_path.exists():
        raise SystemExit(f"ゴールデンタスクが見つかりません: {prompt_path}")
    budgets_path = (
        Path(args.budgets).expanduser().resolve()
        if args.budgets
        else runner_api.default_budgets_path()
    )
    metrics_path = (
        Path(args.metrics).expanduser().resolve()
        if args.metrics
        else runner_api.default_metrics_path()
    )

    schema_path = Path(args.schema).expanduser().resolve() if args.schema else None
    max_concurrency = (
        args.max_concurrency if args.max_concurrency and args.max_concurrency > 0 else None
    )
    rpm = args.rpm if args.rpm and args.rpm > 0 else None
    quorum = args.quorum if args.quorum and args.quorum > 0 else None
    provider_weights = _parse_weights_arg(args.weights)
    if aggregate_kind == "weighted_vote":
        if provider_weights is None:
            raise SystemExit(
                "aggregate=weighted_vote/weighted の場合は --weights を指定してください"
            )
    elif provider_weights is not None:
        raise SystemExit("--weights は aggregate=weighted_vote のときのみ利用できます")

    mode = RunnerMode.from_raw(args.mode)

    return runner_api.run_compare(
        provider_paths,
        prompt_path,
        budgets_path=budgets_path,
        metrics_path=metrics_path,
        repeat=args.repeat,
        mode=mode,
        allow_overrun=args.allow_overrun,
        log_level=args.log_level,
        aggregate=aggregate_value,
        quorum=quorum,
        tie_breaker=args.tie_breaker,
        provider_weights=provider_weights,
        schema=schema_path,
        judge=args.judge,
        max_concurrency=max_concurrency,
        rpm=rpm,
    )


run_batch = runner_api.run_batch


if __name__ == "__main__":  # pragma: no cover - CLI エントリポイント
    raise SystemExit(main())
