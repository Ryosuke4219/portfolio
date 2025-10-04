/*
 * このファイルは分割済みモジュールへの案内用のレガシー互換シムです。
 * 下記チェックリストを完了したら削除してください。
 *
 * - [ ] すべての呼び出し元を projects/03-ci-flaky/src/config/ 配下のモジュールへ移行
 * - [ ] 新モジュールの単体テスト整備とドキュメント更新
 */
export { DEFAULT_CONFIG, mergeDeep } from './config/defaults.js';
export { parseYAML } from './config/parser.js';
export { loadConfig } from './config/loader.js';
export { resolveConfigPaths } from './config/paths.js';
