import json
import os
import subprocess
import sys
import types
from pathlib import Path

from adapter import cli as cli_module
from adapter.core import providers as provider_module


def test_cli_help_smoke() -> None:
    env = os.environ.copy()
    project_root = Path(__file__).resolve().parents[1]
    env["PYTHONPATH"] = str(project_root) + os.pathsep + env.get("PYTHONPATH", "")
    out = subprocess.check_output(
        [sys.executable, "-m", "adapter.cli", "-h"], text=True, env=env
    )
    assert "llm-adapter" in out


def test_cli_fake_provider(monkeypatch, tmp_path: Path, capfd) -> None:
    class FakeProvider:
        def __init__(self, config):
            self.config = config

        def generate(self, prompt):
            return provider_module.ProviderResponse(
                output_text=f"echo:{prompt}",
                input_tokens=1,
                output_tokens=1,
                latency_ms=1,
            )

    factory = type("Factory", (), {"create": staticmethod(lambda cfg: FakeProvider(cfg))})
    monkeypatch.setattr(provider_module, "ProviderFactory", factory)
    monkeypatch.setattr(cli_module, "ProviderFactory", factory)

    config_path = tmp_path / "provider.yml"
    config_path.write_text(
        "provider: fake\nmodel: dummy\nauth_env: NONE\n",
        encoding="utf-8",
    )

    exit_code = cli_module.main([
        "--provider",
        str(config_path),
        "--prompt",
        "hello",
    ])
    captured = capfd.readouterr()
    assert exit_code == 0
    assert "echo:hello" in captured.out


def test_cli_json_log_prompts(monkeypatch, tmp_path: Path, capfd) -> None:
    class FakeProvider:
        def __init__(self, config):
            self.config = config

        def generate(self, prompt):
            return provider_module.ProviderResponse(
                output_text=f"echo:{prompt}",
                input_tokens=1,
                output_tokens=1,
                latency_ms=1,
            )

    factory = type("Factory", (), {"create": staticmethod(lambda cfg: FakeProvider(cfg))})
    monkeypatch.setattr(provider_module, "ProviderFactory", factory)
    monkeypatch.setattr(cli_module, "ProviderFactory", factory)

    config_path = tmp_path / "provider.yml"
    config_path.write_text(
        "provider: fake\nmodel: dummy\nauth_env: NONE\n",
        encoding="utf-8",
    )

    exit_code = cli_module.main(
        [
            "--provider",
            str(config_path),
            "--prompt",
            "hello",
            "--format",
            "json",
            "--log-prompts",
        ]
    )
    captured = capfd.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 0
    assert payload[0]["prompt"] == "hello"


def test_cli_json_without_prompts(monkeypatch, tmp_path: Path, capfd) -> None:
    class FakeProvider:
        def __init__(self, config):
            self.config = config

        def generate(self, prompt):
            return provider_module.ProviderResponse(
                output_text=f"echo:{prompt}",
                input_tokens=1,
                output_tokens=1,
                latency_ms=1,
            )

    factory = type("Factory", (), {"create": staticmethod(lambda cfg: FakeProvider(cfg))})
    monkeypatch.setattr(provider_module, "ProviderFactory", factory)
    monkeypatch.setattr(cli_module, "ProviderFactory", factory)

    config_path = tmp_path / "provider.yml"
    config_path.write_text(
        "provider: fake\nmodel: dummy\nauth_env: NONE\n",
        encoding="utf-8",
    )

    exit_code = cli_module.main(
        [
            "--provider",
            str(config_path),
            "--prompt",
            "hello",
            "--format",
            "json",
        ]
    )
    captured = capfd.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 0
    assert "prompt" not in payload[0]


def test_cli_missing_api_key_en(monkeypatch, tmp_path: Path, capfd) -> None:
    config_path = tmp_path / "provider.yml"
    config_path.write_text(
        "provider: fake\nmodel: dummy\nauth_env: TEST_KEY\n",
        encoding="utf-8",
    )

    exit_code = cli_module.main(
        [
            "--provider",
            str(config_path),
            "--prompt",
            "hello",
            "--lang",
            "en",
        ]
    )
    captured = capfd.readouterr()
    assert exit_code == 3
    assert "API key is missing" in captured.err


def test_cli_unknown_provider(tmp_path: Path, capfd) -> None:
    config_path = tmp_path / "provider.yml"
    config_path.write_text(
        "provider: unknown\nmodel: dummy\nauth_env: NONE\n",
        encoding="utf-8",
    )

    exit_code = cli_module.main(
        [
            "--provider",
            str(config_path),
            "--prompt",
            "hello",
        ]
    )
    captured = capfd.readouterr()
    assert exit_code == 2
    assert "未対応" in captured.err


def test_cli_rate_limit_exit_code(monkeypatch, tmp_path: Path, capfd) -> None:
    class FailingProvider:
        def __init__(self, config):
            self.config = config

        def generate(self, prompt):  # pragma: no cover - 呼ばれない
            raise RuntimeError("429 rate limit exceeded")

    factory = type("Factory", (), {"create": staticmethod(lambda cfg: FailingProvider(cfg))})
    monkeypatch.setattr(provider_module, "ProviderFactory", factory)
    monkeypatch.setattr(cli_module, "ProviderFactory", factory)

    config_path = tmp_path / "provider.yml"
    config_path.write_text(
        "provider: fake\nmodel: dummy\nauth_env: NONE\n",
        encoding="utf-8",
    )

    exit_code = cli_module.main(
        [
            "--provider",
            str(config_path),
            "--prompt",
            "hello",
            "--lang",
            "ja",
        ]
    )
    captured = capfd.readouterr()
    assert exit_code == 6
    assert "レート" in captured.err or "rate" in captured.err.lower()


def test_cli_doctor(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("OPENAI_API_KEY=dummy", encoding="utf-8")
    monkeypatch.setenv("OPENAI_API_KEY", "dummy")
    monkeypatch.setenv("PYTHONIOENCODING", "utf-8")
    monkeypatch.setenv("LLM_ADAPTER_RPM", "120")

    fake_dotenv = types.SimpleNamespace()
    monkeypatch.setitem(sys.modules, "dotenv", fake_dotenv)

    monkeypatch.setattr(cli_module.socket, "gethostbyname", lambda host: "127.0.0.1")

    class DummyHTTPS:
        def __init__(self, host, timeout=0):
            self.host = host
            self.timeout = timeout

        def request(self, method, path):
            return None

        def getresponse(self):
            class Resp:
                status = 200

            return Resp()

        def close(self):
            return None

    monkeypatch.setattr(cli_module.http.client, "HTTPSConnection", DummyHTTPS)

    exit_code = cli_module.main(["doctor", "--lang", "en"])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "All checks passed" in captured.out
