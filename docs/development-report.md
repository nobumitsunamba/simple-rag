# Simple RAG アプリケーション 開発レポート

## 概要

PDF・Wordファイルをアップロードし、その内容に基づいてチャット形式で質問に回答するRAG（Retrieval-Augmented Generation）アプリケーションを開発・デプロイしました。

## 技術スタック

| カテゴリ | 技術 |
|---------|------|
| バックエンド | Python 3.11 / FastAPI |
| LLM | Claude Sonnet 4.6 (Anthropic API) |
| テキスト検索 | TF-IDF (Pure Python実装) |
| ドキュメント処理 | PyPDF2 (PDF), python-docx (Word) |
| テキスト分割 | langchain-text-splitters |
| フロントエンド | HTML / CSS / JavaScript (単一ファイル) |
| インフラ | AWS ECS Express Mode (Fargate) |
| CI/CD | GitHub Actions |
| コンテナレジストリ | Amazon ECR |

## アーキテクチャ

```
[ユーザー] → [ALB] → [ECS Fargate (コンテナ)]
                              │
                    ┌─────────┼─────────┐
                    │         │         │
              [FastAPI]  [TF-IDF]  [Anthropic API]
                    │      検索      (Claude Sonnet)
                    │
            [PDF/Word処理]
```

## プロジェクト構成

```
Simple-rag/
├── .github/workflows/
│   └── deploy.yml              # CI/CD パイプライン
├── app/
│   ├── __init__.py
│   ├── main.py                 # FastAPI アプリケーション
│   ├── document_processor.py   # ドキュメント処理（PDF/Word）
│   ├── vector_store.py         # TF-IDF ベース検索エンジン
│   └── rag_engine.py           # RAG エンジン（Claude Sonnet連携）
├── static/
│   └── index.html              # チャットUI
├── docs/
│   ├── aws-setup.md            # AWSセットアップ手順
│   └── development-report.md   # 本レポート
├── Dockerfile                  # コンテナイメージ定義
├── .dockerignore
├── .gitignore
├── .env.example
├── requirements.txt
├── deploy.ps1                  # ローカルデプロイスクリプト (Windows)
├── deploy.sh                   # ローカルデプロイスクリプト (Linux/Mac)
└── README.md
```

## 機能一覧

### ドキュメント管理
- PDF ファイルのアップロード・テキスト抽出
- Word (.docx) ファイルのアップロード・テキスト抽出
- 複数ファイルの同時管理
- アップロード済みドキュメントの一覧表示
- 全データの一括削除

### チャット機能
- 自然言語による質問入力
- アップロード済みドキュメントに基づく回答生成
- 回答の出典（ファイル名）表示
- リアルタイムのタイピングインジケーター

### API エンドポイント
| メソッド | パス | 説明 |
|---------|------|------|
| GET | `/` | チャットUI |
| POST | `/api/upload` | ドキュメントアップロード |
| POST | `/api/chat` | 質問送信・回答取得 |
| GET | `/api/stats` | アップロード状況確認 |
| POST | `/api/clear` | 全データ削除 |

## デプロイ構成

### CI/CD パイプライン (GitHub Actions)
1. `main` ブランチへのプッシュをトリガー
2. GitHub OIDC でAWS認証（シークレットキー不要）
3. Dockerイメージのビルド
4. Amazon ECR へプッシュ
5. ECS Express Mode でデプロイ

### AWS リソース
| リソース | 名前/設定 |
|---------|-----------|
| ECR リポジトリ | `simple-rag` |
| ECS クラスター | `default` |
| ECS サービス | `simple-rag` (Express Mode) |
| CPU / メモリ | 1 vCPU / 2 GB |
| オートスケーリング | 1〜20タスク (CPU 60%ターゲット) |
| IAM ロール (Task Execution) | `ecsTaskExecutionRole` |
| IAM ロール (Infrastructure) | `ecsInfrastructureRoleForExpressServices` |
| IAM ロール (GitHub Actions) | `GitHubActionsRole-SimpleRAG` |
| OIDC プロバイダー | `token.actions.githubusercontent.com` |

### デプロイURL
```
https://si-aecae9ee619d4ec8938daaa28c992793.ecs.ap-northeast-1.on.aws
```

## 開発中の課題と対応

| 課題 | 原因 | 対応 |
|------|------|------|
| faiss-cpu インストール失敗 | Python 3.14 に対応するバージョンがない | バージョンを 1.14.2 に更新 |
| numpy ビルド失敗 | Python 3.14 + Visual Studio未インストール | scikit-learn に切り替え |
| scikit-learn インストールが進まない | Python 3.14 用のwheelがなくソースビルドが必要 | Pure Python実装に切り替え |
| sentence-transformers メモリエラー | Python 3.14 と Rust バインディングの互換性問題 | TF-IDF (Pure Python) に変更 |
| Claude API 404エラー | モデルID `claude-sonnet-4-20250514` が無効 | `claude-sonnet-4-6` に修正 |
| pip install が固まる | 前回の強制終了によるキャッシュ破損 | `pip cache purge` で解決 |
| GitHub Actions OIDC失敗 | AWSアカウントIDの誤り | 正しいID `032401368831` に修正 |
| ECS CPU/Memory エラー | 値の単位が不正 (1→1024, 2→2048) | Fargate互換の値に修正 |
| ECS サービスリンクロール不在 | 初回ECS利用時に必要 | `create-service-linked-role` で作成 |

## 設計判断

### TF-IDF を採用した理由
当初は sentence-transformers + FAISS によるセマンティック検索を予定していたが、Python 3.14 環境での互換性問題により、外部依存のない Pure Python 実装の TF-IDF に変更。文字 n-gram (2〜4文字) を使用することで、日本語テキストにも対応。

### ECS Express Mode を採用した理由
- AWS App Runner が2026年4月30日以降新規利用不可
- ECS Express Mode は App Runner の後継として推奨
- インフラ管理が自動化され、URL発行・SSL・オートスケーリングが標準装備
- Docker ローカルインストール不要（GitHub Actions でビルド）

## 今後の改善案

1. **検索精度向上**: Amazon Bedrock Titan Embeddings を使ったセマンティック検索への移行
2. **永続化**: アップロードデータのS3保存 + ベクトルインデックスの永続化
3. **認証**: Cognito による認証追加
4. **ファイル対応拡張**: テキストファイル、Markdown、Excel 対応
5. **会話履歴**: マルチターン対話のサポート
6. **コスト最適化**: タスク数の最小値を0にしてスケールダウン

## 作成日

2026年5月29日
