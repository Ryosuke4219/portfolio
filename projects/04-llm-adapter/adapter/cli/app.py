from __future__ import annotations

import sys
from functools import lru_cache
from importlib import import_module
from types import ModuleType
from typing import Iterable, List, Optional

try:  # pragma: no cover - optional dependency
    import typer
except ModuleNotFoundError:  # pragma: no cover - runtime fallback
    typer = None

from .doctor import run_doctor
from .prompts import run_prompts


@lru_cache(maxsize=1)
def _cli_namespace() -> ModuleType:
    return import_module(__name__.rsplit(".", 1)[0])


def _provider_factory() -> object:
    return getattr(_cli_namespace(), "ProviderFactory")


def _socket_module() -> ModuleType:
    return getattr(_cli_namespace(), "socket")


def _http_module() -> ModuleType:
    http_pkg = getattr(_cli_namespace(), "http")
    return getattr(http_pkg, "client")


def _run_prompts_from_iterable(args: Iterable[str]) -> int:
    return run_prompts(list(args), provider_factory=_provider_factory())


def _run_doctor_from_iterable(args: Iterable[str]) -> int:
    return run_doctor(list(args), socket_module=_socket_module(), http_module=_http_module())


if typer is not None:  # pragma: no branch - import-time decision
    _CONTEXT_SETTINGS = {"allow_extra_args": True, "ignore_unknown_options": True}

    app = typer.Typer(
        add_completion=False,
        context_settings=_CONTEXT_SETTINGS,
        help="LLM Adapter CLI",
    )

    def _exit_with(code: int) -> None:
        raise typer.Exit(code)

    @app.callback(invoke_without_command=True)
    def _root(ctx: typer.Context) -> None:
        if ctx.invoked_subcommand is None:
            _exit_with(_run_prompts_from_iterable(ctx.args))

    @app.command(context_settings=_CONTEXT_SETTINGS)
    def run(ctx: typer.Context) -> None:
        """プロンプトを実行し、メトリクスを出力します。"""

        _exit_with(_run_prompts_from_iterable(ctx.args))

    @app.command(context_settings=_CONTEXT_SETTINGS)
    def doctor(ctx: typer.Context) -> None:
        """実行環境の健全性を診断します。"""

        _exit_with(_run_doctor_from_iterable(ctx.args))

    def main(argv: Optional[List[str]] = None) -> int:
        try:
            app(args=list(argv) if argv is not None else None, standalone_mode=False)
        except typer.Exit as exc:  # pragma: no cover - Typer converts to Exit
            return int(exc.exit_code or 0)
        return 0

else:  # pragma: no cover - exercised when Typer is unavailable

    class _FallbackApp:
        def __call__(self, *args: object, **kwargs: object) -> None:
            raise RuntimeError("Typer is not installed; CLI app is unavailable")

    app = _FallbackApp()

    def run(argv: Optional[List[str]] = None) -> int:
        return _run_prompts_from_iterable(argv or [])

    def doctor(argv: Optional[List[str]] = None) -> int:
        return _run_doctor_from_iterable(argv or [])

    def main(argv: Optional[List[str]] = None) -> int:
        args = list((argv if argv is not None else sys.argv[1:]))
        if args and args[0] == "doctor":
            return doctor(args[1:])
        return run(args)


__all__ = ["app", "doctor", "main", "run"]

