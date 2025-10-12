from collections.abc import Callable
from typing import cast

import pytest
from src.llm_adapter.provider_spi import ProviderResponse, TokenUsage
from src.llm_adapter.runner_parallel.models import ConsensusObservation


@pytest.fixture
def make_response() -> Callable[..., ProviderResponse]:
    def _make_response(
        text: str,
        latency: int,
        *,
        tokens_in: int = 1,
        tokens_out: int = 1,
        score: float | None = None,
    ) -> ProviderResponse:
        raw: dict[str, object] | None = None
        if score is not None:
            raw = {"score": float(score)}
        return ProviderResponse(
            text=text,
            latency_ms=latency,
            token_usage=TokenUsage(prompt=tokens_in, completion=tokens_out),
            raw=raw,
        )

    return _make_response


@pytest.fixture
def make_observation(
    make_response: Callable[..., ProviderResponse],
) -> Callable[..., ConsensusObservation]:
    def _make_observation(
        provider_id: str,
        text: str,
        latency: int,
        *extra_cost: float,
        tokens_in: int = 1,
        tokens_out: int = 1,
        cost_estimate: float | None = None,
    ) -> ConsensusObservation:
        observation_type = cast(type[ConsensusObservation], ConsensusObservation)
        annotations = cast(
            dict[str, object], getattr(observation_type, "__annotations__", {})
        )
        response = make_response(
            text,
            latency,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
        )
        token_usage = TokenUsage(prompt=tokens_in, completion=tokens_out)
        kwargs: dict[str, object] = {
            "provider_id": provider_id,
            "response": response,
        }
        latency_field = next(
            (name for name in ("latency", "latency_ms") if name in annotations), None
        )
        assert latency_field is not None, "ConsensusObservation missing latency field"
        kwargs[latency_field] = latency
        if tokens_field := next(
            (name for name in ("tokens", "token_usage") if name in annotations), None
        ):
            kwargs[tokens_field] = token_usage
        if (
            (
                cost_field := next(
                    (name for name in ("cost_estimate", "cost") if name in annotations),
                    None,
                )
            )
            or cost_estimate is not None
            or extra_cost
        ):
            estimate = (
                cost_estimate
                if cost_estimate is not None
                else extra_cost[0]
                if extra_cost
                else None
            )
            kwargs[cost_field or "cost_estimate"] = (
                float(estimate) if estimate is not None else float(tokens_in + tokens_out)
            )
        if "error" in annotations:
            kwargs.setdefault("error", None)
        observation_factory = cast(Callable[..., ConsensusObservation], observation_type)
        return observation_factory(**kwargs)

    return _make_observation
