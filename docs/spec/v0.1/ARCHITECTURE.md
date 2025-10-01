# Architecture Overview - planting-planner v0.1

## システム構成
- フロントエンド: React + Vite (TypeScript)。PCブラウザ専用UI、localStorageでお気に入りを永続化。
- バックエンド: FastAPI (Python) + SQLite。収集済み市場データと栽培期間マスタを提供。
- CI/CD: GitHub Actions。lint (ruff/black, eslint), 型検査 (mypy/tsc), テスト (pytest/node:test) を自動実行。

## データフロー
1. バックエンドが公的データソースから取り込んだ市場データと作物ごとの生育日数マスタをSQLiteに格納。
2. フロントエンドはユーザー入力の収穫希望週をAPIに送信。
3. APIは希望週から播種・定植週を逆算し、今週植えるべき作物リストを生成して返却。
4. フロントエンドはレスポンスを表示し、ユーザーがお気に入りを設定するとlocalStorageに保存。次回アクセス時はお気に入りを優先表示。

## レイヤ構造
- **Presentation**: Reactコンポーネント群。状態管理とlocalStorageハンドリングを担当。
- **Application**: FastAPIルーター。リクエスト検証、逆算ロジック呼び出し、レスポンス整形。
- **Domain**: 栽培期間計算やお気に入り並び替えなどのドメインロジック。
- **Infrastructure**: データ取得・SQLite永続化・外部APIクライアント。

## エンドポイント
- `GET /health`: ヘルスチェック。
- `POST /plans/weekly`: 入力パラメータ（作物カテゴリ、収穫希望週、地域オプション）から週次プランを生成。
- `GET /catalog/crops`: 作物マスタ一覧。

## データモデル
- **Crop**: `id`, `name`, `category`, `growth_days`
- **MarketPrice**: `id`, `crop_id`, `week`, `price_avg`
- **PlantingPlan**: APIレスポンス用DTO。`crop_id`, `plant_week`, `transplant_week`, `harvest_week`, `notes`

## 逆算ロジック
- 収穫週から平均生育日数を差し引き播種週を算定。
- 定植が必要な作物は追加で定植リードタイムを引き、播種→定植→収穫の週次タイムラインを生成。
- 現在週と一致する播種週・定植週がある作物をフィルタし、優先度（お気に入り、有望市場価格など）でソート。

## 非機能要求反映
- すべての入出力はJSON。CLIやバッチを追加する際は同スキーマを再利用。
- ログは構造化JSONで出力し、例外は再試行可否に応じて階層化。
- レスポンスタイム影響を最小化するため、頻出マスタはアプリ起動時にメモリキャッシュへプリロード。

## セキュリティ・運用
- 認証はv0.1では不要だが、将来の拡張用にAPIキー認証ミドルウェアをプレースホルダーとして用意。
- 機微データ不取扱。環境変数は `.env.example` を基準にローカルで設定。
- データ更新はGitHub Actionsスケジュールワークフローで日次実行、SQLiteを再生成しArtifactsへ保存。
