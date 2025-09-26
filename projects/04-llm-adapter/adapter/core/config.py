"""設定ファイルの読み込みロジック。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Optional, Tuple, Union

try:  # pragma: no cover - 依存がある場合はこちらを利用
    import yaml  # type: ignore
except Exception:  # pragma: no cover - フォールバックで処理
    yaml = None


@dataclass
class RetryConfig:
    """API 呼び出しの再試行設定。"""

    max: int = 0
    backoff_s: float = 0.0


@dataclass
class PricingConfig:
    """1k トークンあたりの料金設定。"""

    prompt_usd: float = 0.0
    completion_usd: float = 0.0
    input_per_million: float = 0.0
    output_per_million: float = 0.0


@dataclass
class RateLimitConfig:
    """レートリミットのしきい値。"""

    rpm: int = 0
    tpm: int = 0


@dataclass
class QualityGatesConfig:
    """決定性ゲートのしきい値。"""

    determinism_diff_rate_max: float = 0.0
    determinism_len_stdev_max: float = 0.0


@dataclass
class ProviderConfig:
    """プロバイダ設定。"""

    path: Path
    provider: str
    endpoint: Optional[str]
    model: str
    auth_env: Optional[str]
    seed: int
    temperature: float
    top_p: float
    max_tokens: int
    timeout_s: int
    retries: RetryConfig
    persist_output: bool
    pricing: PricingConfig
    rate_limit: RateLimitConfig
    quality_gates: QualityGatesConfig
    raw: Mapping[str, Any]


@dataclass
class BudgetRule:
    """プロバイダごとの予算ルール。"""

    run_budget_usd: float
    daily_budget_usd: float
    stop_on_budget_exceed: bool


@dataclass
class BudgetBook:
    """予算設定全体。"""

    default: BudgetRule
    overrides: Mapping[str, BudgetRule]


def _load_yaml(path: Union[str, Path]) -> MutableMapping[str, Any]:
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    if yaml is not None:
        data = yaml.safe_load(text)
        if not isinstance(data, MutableMapping):
            raise ValueError(f"YAML の内容が辞書ではありません: {path}")
        return data
    return _load_yaml_without_dependency(text, path)


def _load_yaml_without_dependency(text: str, path: Path) -> MutableMapping[str, Any]:
    """PyYAML が無い環境向けの簡易 YAML パーサ。"""

    def convert(value: str) -> Any:
        value = value.strip()
        if value == "":
            return ""
        lowered = value.lower()
        if lowered in {"true", "false"}:
            return lowered == "true"
        if lowered in {"null", "none"}:
            return None
        try:
            if "." in value:
                return float(value)
            return int(value)
        except ValueError:
            if (value.startswith('"') and value.endswith('"')) or (
                value.startswith("'") and value.endswith("'")
            ):
                return value[1:-1]
            return value

    root: MutableMapping[str, Any] = {}
    stack: List[Tuple[MutableMapping[str, Any], int]] = [(root, 0)]
    for raw_line in text.splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        line = raw_line.strip()
        if ":" not in line:
            raise ValueError(f"サポート外の YAML 構文です: {path}: {line}")
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()
        while stack and indent < stack[-1][1]:
            stack.pop()
        if not stack:
            raise ValueError(f"インデントが不正です: {path}: {line}")
        current = stack[-1][0]
        if value == "":
            new_dict: MutableMapping[str, Any] = {}
            current[key] = new_dict
            stack.append((new_dict, indent + 2))
        else:
            current[key] = convert(value)
    return root


def load_provider_config(path: Union[str, Path]) -> ProviderConfig:
    """単一のプロバイダ設定を読み込む。"""

    path = Path(path)
    data = _load_yaml(path)
    retries = data.get("retries", {})
    pricing = data.get("pricing", {})
    rate_limit = data.get("rate_limit", {})
    quality = data.get("quality_gates", {})
    return ProviderConfig(
        path=path,
        provider=str(data.get("provider")),
        endpoint=data.get("endpoint"),
        model=str(data.get("model")),
        auth_env=data.get("auth_env"),
        seed=int(data.get("seed", 0)),
        temperature=float(data.get("temperature", 0.0)),
        top_p=float(data.get("top_p", 1.0)),
        max_tokens=int(data.get("max_tokens", 0)),
        timeout_s=int(data.get("timeout_s", 0)),
        retries=RetryConfig(
            max=int(retries.get("max", 0)),
            backoff_s=float(retries.get("backoff_s", 0.0)),
        ),
        persist_output=bool(data.get("persist_output", False)),
        pricing=PricingConfig(
            prompt_usd=float(pricing.get("prompt_usd", 0.0)),
            completion_usd=float(pricing.get("completion_usd", 0.0)),
            input_per_million=float(pricing.get("input_per_million", 0.0)),
            output_per_million=float(pricing.get("output_per_million", 0.0)),
        ),
        rate_limit=RateLimitConfig(
            rpm=int(rate_limit.get("rpm", 0)),
            tpm=int(rate_limit.get("tpm", 0)),
        ),
        quality_gates=QualityGatesConfig(
            determinism_diff_rate_max=float(
                quality.get("determinism_diff_rate_max", 0.0)
            ),
            determinism_len_stdev_max=float(
                quality.get("determinism_len_stdev_max", 0.0)
            ),
        ),
        raw=data,
    )


def load_provider_configs(paths: Iterable[Path]) -> List[ProviderConfig]:
    """複数のプロバイダ設定を読み込む。"""

    return [load_provider_config(path) for path in paths]


def load_budget_book(path: Path) -> BudgetBook:
    """予算設定を読み込む。"""

    data = _load_yaml(path)
    default_raw = data.get("default", {})
    overrides_raw = data.get("overrides", {})
    default_rule = BudgetRule(
        run_budget_usd=float(default_raw.get("run_budget_usd", 0.0)),
        daily_budget_usd=float(default_raw.get("daily_budget_usd", 0.0)),
        stop_on_budget_exceed=bool(default_raw.get("stop_on_budget_exceed", False)),
    )
    overrides: Dict[str, BudgetRule] = {}
    for provider_name, rule_raw in overrides_raw.items():
        overrides[provider_name] = BudgetRule(
            run_budget_usd=float(rule_raw.get("run_budget_usd", default_rule.run_budget_usd)),
            daily_budget_usd=float(
                rule_raw.get("daily_budget_usd", default_rule.daily_budget_usd)
            ),
            stop_on_budget_exceed=bool(
                rule_raw.get("stop_on_budget_exceed", default_rule.stop_on_budget_exceed)
            ),
        )
    return BudgetBook(default=default_rule, overrides=overrides)
