import argparse
from types import SimpleNamespace

from adapter.cli.prompt_io import collect_prompts, read_jsonl_prompts


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
