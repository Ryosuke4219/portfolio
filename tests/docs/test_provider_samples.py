from pathlib import Path


def test_ollama_comment_prioritizes_base_url():
    sample_path = Path(
        "projects/04-llm-adapter/examples/providers/ollama.yml"
    )
    lines = sample_path.read_text(encoding="utf-8").splitlines()
    assert (
        "#         ※ OLLAMA_BASE_URL が優先され、未設定の場合のみ旧互換の OLLAMA_HOST が利用されます"
        in lines
    )
