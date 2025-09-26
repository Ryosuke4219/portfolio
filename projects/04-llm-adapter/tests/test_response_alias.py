from adapter.core.providers import ProviderResponse as R


def test_aliases() -> None:
    resp = R(output_text="ok", input_tokens=5, output_tokens=7, latency_ms=12)
    assert resp.text == "ok"
    usage = resp.token_usage
    assert (usage.prompt, usage.completion, usage.total) == (5, 7, 12)
