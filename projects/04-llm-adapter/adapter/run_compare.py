"""比較ランナー CLI。"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

try:
    from .core.budgets import BudgetManager
    from .core.config import load_budget_book, load_provider_configs
    from .core.datasets import load_golden_tasks
    from .core.runners import CompareRunner
except ImportError:  # pragma: no cover - 直接実行時のフォールバック
    PACKAGE_ROOT = Path(__file__).resolve().parent.parent
    if str(PACKAGE_ROOT) not in sys.path:
        sys.path.insert(0, str(PACKAGE_ROOT))
    from adapter.core.budgets import BudgetManager
    from adapter.core.config import load_budget_book, load_provider_configs
    from adapter.core.datasets import load_golden_tasks
    from adapter.core.runners import CompareRunner

LOGGER = logging.getLogger(__name__)


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
        choices=["parallel", "serial"],
        default="parallel",
        help="実行モード",
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
    return parser.parse_args()


def _default_budgets_path() -> Path:
    return Path(__file__).resolve().parent / "config" / "budgets.yaml"


def _default_metrics_path() -> Path:
    return Path(__file__).resolve().parent.parent / "data" / "runs-metrics.jsonl"


def _run(
    provider_paths: list[Path],
    prompt_path: Path,
    budgets_path: Path,
    metrics_path: Path,
    *,
    repeat: int,
    mode: str,
    allow_overrun: bool,
    log_level: str,
) -> int:
    logging.basicConfig(level=getattr(logging, log_level.upper(), logging.INFO))

    provider_configs = load_provider_configs(provider_paths)
    tasks = load_golden_tasks(prompt_path)
    budget_book = load_budget_book(budgets_path)
    budget_manager = BudgetManager(budget_book)

    runner = CompareRunner(
        provider_configs,
        tasks,
        budget_manager,
        metrics_path,
        allow_overrun=allow_overrun,
    )
    results = runner.run(repeat=max(repeat, 1), mode=mode)
    LOGGER.info("%d 件の試行を記録しました", len(results))
    return 0


def run_batch(provider_specs: list[str], prompts_path: str) -> int:
    provider_paths = [Path(spec).expanduser().resolve() for spec in provider_specs if spec]
    if not provider_paths:
        raise ValueError("provider_specs must include at least one path")
    prompt_path = Path(prompts_path).expanduser().resolve()
    if not prompt_path.exists():
        raise FileNotFoundError(f"ゴールデンタスクが見つかりません: {prompt_path}")
    budgets_path = _default_budgets_path()
    metrics_path = _default_metrics_path()
    return _run(
        provider_paths,
        prompt_path,
        budgets_path,
        metrics_path,
        repeat=1,
        mode="parallel",
        allow_overrun=False,
        log_level="INFO",
    )


def main() -> int:
    args = _parse_args()

    provider_paths = [Path(p.strip()).expanduser().resolve() for p in args.providers.split(",") if p.strip()]
    if not provider_paths:
        raise SystemExit("--providers に有効なパスが指定されていません")
    prompt_path = Path(args.prompts).expanduser().resolve()
    if not prompt_path.exists():
        raise SystemExit(f"ゴールデンタスクが見つかりません: {prompt_path}")
    budgets_path = (
        Path(args.budgets).expanduser().resolve()
        if args.budgets
        else _default_budgets_path()
    )
    metrics_path = (
        Path(args.metrics).expanduser().resolve()
        if args.metrics
        else _default_metrics_path()
    )

    return _run(
        provider_paths,
        prompt_path,
        budgets_path,
        metrics_path,
        repeat=args.repeat,
        mode=args.mode,
        allow_overrun=args.allow_overrun,
        log_level=args.log_level,
    )


if __name__ == "__main__":  # pragma: no cover - CLI エントリポイント
    raise SystemExit(main())
