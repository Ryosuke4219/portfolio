import argparse
import hashlib
import json
from types import SimpleNamespace

from adapter.cli.prompt_io import collect_prompts, read_jsonl_prompts, write_metrics
from adapter.cli.prompt_runner import PromptResult
from adapter.core.metrics.models import RunMetric


def test_collect_prompts_strips_crlf(tmp_path):
    prompt_path = tmp_path / "prompt.txt"
    prompt_path.write_text("hello\r\n", encoding="utf-8")
    parser = argparse.ArgumentParser()
    args = SimpleNamespace(prompt=None, prompt_file=str(prompt_path), prompts=None)

    prompts = collect_prompts(args, parser, lang="en")

    assert prompts == ["hello"]


def test_read_jsonl_prompts_handles_bom(tmp_path):
    prompts_path = tmp_path / "prompts.jsonl"
    prompts_path.write_text("\ufeff{\"prompt\": \"hello\"}\n", encoding="utf-8")

    prompts = read_jsonl_prompts(prompts_path, lang="en")

    assert prompts == ["hello"]


def test_write_metrics_creates_jsonl(tmp_path):
    out_dir = tmp_path / "out"
    prompt = "hello"
    metric = RunMetric(
        provider="test-provider",
        model="test-model",
        endpoint="responses",
        latency_ms=1,
        input_tokens=1,
        output_tokens=1,
        cost_usd=0.0,
        status="ok",
        error=None,
        prompt_sha256=hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:16],
    )
    results = [
        PromptResult(
            index=0,
            prompt=prompt,
            response=None,
            metric=metric,
            output_text="",
            error=None,
        )
    ]

    write_metrics(out_dir, results, include_prompts=False, lang="en")

    metrics_path = out_dir / "metrics.jsonl"
    assert metrics_path.exists()
    with metrics_path.open(encoding="utf-8") as fp:
        lines = fp.readlines()
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["provider"] == "test-provider"
