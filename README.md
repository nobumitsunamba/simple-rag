<<<<<<< HEAD
# Simple RAG - ドキュメントQ&Aアプリ

PDF・Wordファイルをアップロードし、その内容に基づいてチャット形式で質問に答えるRAG（Retrieval-Augmented Generation）アプリケーションです。

## 技術スタック

- **バックエンド:** FastAPI
- **LLM:** Claude Sonnet (Anthropic API)
- **埋め込み:** sentence-transformers (all-MiniLM-L6-v2)
- **ベクトル検索:** FAISS
- **ドキュメント処理:** PyPDF2, python-docx
- **フロントエンド:** HTML/CSS/JavaScript (単一ファイル)

## セットアップ

### 1. 仮想環境の作成

```bash
python -m venv .venv
.venv\Scripts\activate  # Windows
# source .venv/bin/activate  # Mac/Linux
```

### 2. 依存パッケージのインストール

```bash
pip install -r requirements.txt
```

### 3. 環境変数の設定

```bash
copy .env.example .env
```

`.env` ファイルを編集して Anthropic API キーを設定:

```
ANTHROPIC_API_KEY=sk-ant-xxxxx
```

### 4. アプリの起動

```bash
uvicorn app.main:app --reload
```

ブラウザで http://localhost:8000 を開きます。

## 使い方

1. 左サイドバーからPDFまたはWordファイルをアップロード
2. 右側のチャット欄で質問を入力
3. アップロードしたドキュメントの内容に基づいた回答が返されます

## API エンドポイント

| メソッド | パス | 説明 |
|---------|------|------|
| POST | `/api/upload` | ドキュメントのアップロード |
| POST | `/api/chat` | 質問の送信 |
| GET | `/api/stats` | アップロード状況の確認 |
| POST | `/api/clear` | 全データの削除 |

## AWS App Runner へのデプロイ

### 前提条件

- AWS CLI がインストール・設定済み
- Docker がインストール・起動済み
- `ANTHROPIC_API_KEY` 環境変数が設定済み

### デプロイ手順 (Windows PowerShell)

```powershell
$env:ANTHROPIC_API_KEY = "sk-ant-xxxxx"
.\deploy.ps1
```

### デプロイ手順 (Mac/Linux)

```bash
export ANTHROPIC_API_KEY="sk-ant-xxxxx"
chmod +x deploy.sh
./deploy.sh
```

デプロイ完了後、App Runner が発行するURL（`https://xxxxx.ap-northeast-1.awsapprunner.com`）でアクセスできます。

### サービスURLの確認

```powershell
$arn = aws apprunner list-services --region ap-northeast-1 --query "ServiceSummaryList[?ServiceName=='simple-rag'].ServiceArn" --output text
aws apprunner describe-service --service-arn $arn --region ap-northeast-1 --query "Service.ServiceUrl" --output text
```

## 注意事項

- 初回起動時に sentence-transformers のモデル（約90MB）がダウンロードされます
- アップロードしたデータはメモリ上に保持されるため、サーバー再起動で消えます
- 大量のドキュメントを扱う場合はメモリ使用量に注意してください
- App Runner のインスタンスは 1 vCPU / 2GB メモリで構成されています
=======
# simple-rag
>>>>>>> 4f7dc1a29e24d7545598f154cee45dcf8303d0b0
