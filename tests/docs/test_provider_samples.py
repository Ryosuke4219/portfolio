from pathlib import Path


def test_ollama_comment_prioritizes_base_url():
    sample_path = Path(
        "projects/04-llm-adapter/examples/providers/ollama.yml"
    )
    lines = sample_path.read_text(encoding="utf-8").splitlines()
    assert (
        "#         ※ OLLAMA_HOST は互換目的の旧変数で、設定がなければ BASE_URL のフォールバックとして解釈されます"
        in lines
    )
