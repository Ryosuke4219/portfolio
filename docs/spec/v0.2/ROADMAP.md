# LLM Adapter Roadmap (v0.2 Snapshot)

最新の04系ロードマップはリポジトリ直下の [`04/ROADMAP.md`](../../../04/ROADMAP.md) を参照してください。

OpenRouter を含むプロバイダ別セットアップ手順は `projects/04-llm-adapter/README.md` の [サンプル設定とプロンプト](../../../projects/04-llm-adapter/README.md#サンプル設定とプロンプト) を参照してください。Shadow 版ではなくコア構成の README を正とし、環境変数名と推奨オペレーション（APIキーの秘匿、429対策など）はそちらで随時更新しています。

> 補足: v0.2向けの追加計画や変更点が決まり次第、このファイルに追記します。

## CLI 実装メモ (v0.2)

`llm-adapter` CLI は `ProviderRequest` 経由でプロバイダを呼び出します[^cli-provider-request]。

[^cli-provider-request]: `adapter/cli/prompts.py` で設定読込時に CLI 引数を `ProviderRequest` 用に正規化し、`adapter/cli/prompt_runner.py` の `_build_request` がモデル・オプション・メタデータを束ねて `invoke` へ渡す。`projects/04-llm-adapter/tests/test_cli_single_prompt.py::test_cli_fake_provider` が代表的なリグレッションテスト。
