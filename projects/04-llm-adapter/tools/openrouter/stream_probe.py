"""OpenRouter のストリーミングレスポンスを検証するプローブ。"""
from __future__ import annotations

import argparse
import datetime as dt
import logging
from pathlib import Path
from typing import Any, Iterable

from adapter.core import ProviderFactory, load_provider_config
from adapter.core.errors import ProviderSkip
from adapter.core.provider_spi import ProviderRequest
from adapter.core.providers.openrouter import SessionProtocol

LOGGER = logging.getLogger(__name__)
_DEFAULT_PROMPT = "Hello from llm-adapter OpenRouter probe."
_DRY_RUN_MESSAGE = "Dry-run: set OPENROUTER_API_KEY and re-run to invoke OpenRouter probe."

def _wrap_response(response: Any, logger: logging.Logger) -> Any:
    iter_lines = getattr(response, "iter_lines", None)
    if not callable(iter_lines):
        return response

    def _iter_lines(*args: Any, **kwargs: Any) -> Iterable[Any]:
        for raw in iter_lines(*args, **kwargs):
            text = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)
            chunk = text.strip()
            if chunk and chunk != "[DONE]":
                if chunk.startswith("data:"):
                    chunk = chunk[5:].strip()
                stamp = dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="milliseconds")
                logger.info("%s chunk: %s", stamp, chunk)
            yield raw

    setattr(response, "iter_lines", _iter_lines)
    return response

def _wrap_session(session: SessionProtocol, logger: logging.Logger) -> SessionProtocol:
    post = getattr(session, "post", None)
    if not callable(post):
        return session

    def _post(*args: Any, **kwargs: Any) -> Any:
        result = post(*args, **kwargs)
        return _wrap_response(result, logger) if kwargs.get("stream") else result

    setattr(session, "post", _post)
    return session

def _attach_logging(provider: Any, logger: logging.Logger) -> None:
    session = getattr(provider, "_session", None)
    if session is not None:
        provider._session = _wrap_session(session, logger)


def run_probe(
    *,
    provider_path: Path,
    prompt: str,
    session: SessionProtocol | None = None,
    logger: logging.Logger | None = None,
) -> int:
    """OpenRouter プロバイダをストリーミングモードで実行する。"""

    active_logger = logger or LOGGER
    config = load_provider_config(provider_path)
    config.raw = {**dict(config.raw or {}), **({"session": session} if session is not None else {})}
    provider = ProviderFactory.create(config)
    _attach_logging(provider, active_logger)
    request = ProviderRequest(model=config.model, messages=[{"role": "user", "content": prompt}], options={"stream": True})
    try:
        response = provider.invoke(request)
    except ProviderSkip as exc:
        active_logger.info("Skipping OpenRouter probe: %s", exc)
        return 0
    active_logger.info(
        "OpenRouter latency: %sms (tokens in=%s out=%s)",
        response.latency_ms,
        response.tokens_in,
        response.tokens_out,
    )
    active_logger.info("OpenRouter completion: %s", response.text.strip())
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--provider",
        default=Path(__file__).resolve().parents[2] / "adapter" / "config" / "providers" / "openrouter.yaml",
        type=Path,
        help="プロバイダ設定ファイル",
    )
    parser.add_argument("--prompt", default=_DEFAULT_PROMPT, help="送信するユーザプロンプト")
    parser.add_argument("--dry-run", action="store_true", help="接続確認のみを行い実行をスキップする")
    args = parser.parse_args(argv)
    if args.dry_run:
        LOGGER.info(_DRY_RUN_MESSAGE)
        return 0
    return run_probe(provider_path=Path(args.provider).expanduser().resolve(), prompt=str(args.prompt or _DEFAULT_PROMPT))


if __name__ == "__main__":  # pragma: no cover - CLI entrypoint
    raise SystemExit(main())
