from __future__ import annotations

import argparse
from pathlib import Path

from adapter.core.config import load_provider_config
from adapter.core.providers import ProviderFactory


def main() -> None:
    parser = argparse.ArgumentParser("llm-adapter")
    parser.add_argument("--provider", required=True, help="プロバイダ設定 YAML のパス")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--prompt", help="単発プロンプト文字列")
    group.add_argument("--prompts", help="JSONL 形式のプロンプト一覧")
    args = parser.parse_args()

    config = load_provider_config(Path(args.provider))
    provider = ProviderFactory.create(config)

    if args.prompt is not None:
        response = provider.generate(args.prompt)
        print(response.output_text)
    else:
        from adapter.run_compare import run_batch

        run_batch([args.provider], args.prompts)


if __name__ == "__main__":  # pragma: no cover
    main()
