"""設定ファイルの読み込みユーティリティ。"""
from __future__ import annotations

from collections.abc import Iterable, MutableMapping
from numbers import Real
from pathlib import Path
from types import ModuleType
from typing import cast

from pydantic import ValidationError

from .errors import ConfigError as _ConfigErrorBase
from .models import (
    BudgetBook,
    BudgetRule,
    PricingConfig,
    ProviderConfig,
    QualityGatesConfig,
    RateLimitConfig,
    RetryConfig,
)
from .schema import ProviderConfigModel

yaml: ModuleType | None

try:  # pragma: no cover - 依存がある場合はこちらを利用
    import yaml as _yaml
except ImportError:  # pragma: no cover - フォールバックで処理
    yaml = None
else:  # pragma: no cover - 依存がある場合はこちらを利用
    yaml = _yaml

__all__ = [
    "ConfigError",
    "load_provider_config",
    "load_provider_configs",
    "load_budget_book",
]


class ConfigError(_ConfigErrorBase):
    """設定ファイルの検証エラー。"""


def _format_validation_error(path: Path, exc: ValidationError) -> str:
    details = []
    for error in exc.errors():
        location = ".".join(str(part) for part in error.get("loc", ()) if part is not None)
        message = error.get("msg", "未知のエラー")
        if location:
            details.append(f"{location}: {message}")
        else:
            details.append(message)
    summary = "; ".join(details)
    return f"設定ファイルの検証に失敗しました ({path}): {summary}"


def _load_yaml(path: str | Path) -> MutableMapping[str, object]:
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    if yaml is not None:
        data = yaml.safe_load(text)
        if not isinstance(data, MutableMapping):
            raise ValueError(f"YAML の内容が辞書ではありません: {path}")
        return cast(MutableMapping[str, object], data)
    return _load_yaml_without_dependency(text, path)


def _load_yaml_without_dependency(text: str, path: Path) -> MutableMapping[str, object]:
    """PyYAML が無い環境向けの簡易 YAML パーサ。"""

    def convert(value: str) -> object:
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

    root: dict[str, object] = {}
    stack: list[tuple[MutableMapping[str, object], int]] = [(root, 0)]
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
            new_dict: dict[str, object] = {}
            current[key] = new_dict
            stack.append((new_dict, indent + 2))
        else:
            current[key] = convert(value)
    return root


def load_provider_config(path: str | Path) -> ProviderConfig:
    """単一のプロバイダ設定を読み込む。"""

    path = Path(path)
    data = _load_yaml(path)
    try:
        model = ProviderConfigModel.model_validate(data)
    except ValidationError as exc:
        raise ConfigError(_format_validation_error(path, exc)) from None
    retries = model.retries
    pricing = model.pricing
    rate_limit = model.rate_limit
    quality = model.quality_gates
    raw_dump = model.model_dump(mode="python")
    if model.model_extra:
        raw_dump.update(model.model_extra)
    return ProviderConfig(
        path=path,
        schema_version=model.schema_version,
        provider=model.provider,
        endpoint=model.endpoint,
        model=model.model,
        auth_env=model.auth_env,
        seed=model.seed,
        temperature=model.temperature,
        top_p=model.top_p,
        max_tokens=model.max_tokens,
        timeout_s=model.timeout_s,
        retries=RetryConfig(max=retries.max, backoff_s=retries.backoff_s),
        persist_output=model.persist_output,
        pricing=PricingConfig(
            prompt_usd=pricing.prompt_usd,
            completion_usd=pricing.completion_usd,
            input_per_million=pricing.input_per_million,
            output_per_million=pricing.output_per_million,
        ),
        rate_limit=RateLimitConfig(rpm=rate_limit.rpm, tpm=rate_limit.tpm),
        quality_gates=QualityGatesConfig(
            determinism_diff_rate_max=quality.determinism_diff_rate_max,
            determinism_len_stdev_max=quality.determinism_len_stdev_max,
        ),
        raw=raw_dump,
    )


def load_provider_configs(paths: Iterable[Path]) -> list[ProviderConfig]:
    """複数のプロバイダ設定を読み込む。"""

    return [load_provider_config(path) for path in paths]


def load_budget_book(path: Path) -> BudgetBook:
    """予算設定を読み込む。"""

    data = _load_yaml(path)
    default_raw_obj = data.get("default", {})
    default_raw: MutableMapping[str, object]
    if isinstance(default_raw_obj, MutableMapping):
        default_raw = default_raw_obj
    else:
        default_raw = cast(MutableMapping[str, object], {})
    overrides_raw_obj = data.get("overrides", {})
    overrides_raw: MutableMapping[str, object]
    if isinstance(overrides_raw_obj, MutableMapping):
        overrides_raw = overrides_raw_obj
    else:
        overrides_raw = cast(MutableMapping[str, object], {})
    default_rule = BudgetRule(
        run_budget_usd=_coerce_budget_float(default_raw.get("run_budget_usd"), 0.0),
        daily_budget_usd=_coerce_budget_float(default_raw.get("daily_budget_usd"), 0.0),
        stop_on_budget_exceed=bool(default_raw.get("stop_on_budget_exceed", False)),
    )
    overrides: dict[str, BudgetRule] = {}
    for provider_name, rule_raw in overrides_raw.items():
        if not isinstance(provider_name, str) or not isinstance(rule_raw, MutableMapping):
            continue
        overrides[provider_name] = BudgetRule(
            run_budget_usd=_coerce_budget_float(
                rule_raw.get("run_budget_usd"), default_rule.run_budget_usd
            ),
            daily_budget_usd=_coerce_budget_float(
                rule_raw.get("daily_budget_usd"), default_rule.daily_budget_usd
            ),
            stop_on_budget_exceed=bool(
                rule_raw.get("stop_on_budget_exceed", default_rule.stop_on_budget_exceed)
            ),
        )
    return BudgetBook(default=default_rule, overrides=overrides)


def _coerce_budget_float(candidate: object, fallback: float) -> float:
    if isinstance(candidate, Real):
        try:
            return float(candidate)
        except (TypeError, ValueError):
            return fallback
    if isinstance(candidate, str):
        stripped = candidate.strip()
        if not stripped:
            return fallback
        try:
            return float(stripped)
        except ValueError:
            return fallback
    return fallback
