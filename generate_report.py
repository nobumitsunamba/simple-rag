"""Generate development report as a Word document."""

from docx import Document
from docx.shared import Pt, Inches, Cm, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT


def add_heading(doc, text, level=1):
    heading = doc.add_heading(text, level=level)
    return heading


def add_table(doc, headers, rows):
    table = doc.add_table(rows=1, cols=len(headers))
    table.style = "Light Grid Accent 1"
    # Header row
    for i, header in enumerate(headers):
        table.rows[0].cells[i].text = header
    # Data rows
    for row_data in rows:
        row = table.add_row()
        for i, cell_text in enumerate(row_data):
            row.cells[i].text = cell_text
    return table


def main():
    doc = Document()

    # Title
    title = doc.add_heading("Simple RAG アプリケーション 開発レポート", level=0)

    # 概要
    add_heading(doc, "概要")
    doc.add_paragraph(
        "PDF・Wordファイルをアップロードし、その内容に基づいてチャット形式で質問に回答する"
        "RAG（Retrieval-Augmented Generation）アプリケーションを開発・デプロイしました。"
    )

    # 技術スタック
    add_heading(doc, "技術スタック")
    add_table(doc, ["カテゴリ", "技術"], [
        ["バックエンド", "Python 3.11 / FastAPI"],
        ["LLM", "Claude Sonnet 4.6 (Anthropic API)"],
        ["テキスト検索", "TF-IDF (Pure Python実装)"],
        ["ドキュメント処理", "PyPDF2 (PDF), python-docx (Word)"],
        ["テキスト分割", "langchain-text-splitters"],
        ["フロントエンド", "HTML / CSS / JavaScript (単一ファイル)"],
        ["インフラ", "AWS ECS Express Mode (Fargate)"],
        ["CI/CD", "GitHub Actions"],
        ["コンテナレジストリ", "Amazon ECR"],
    ])

    # アーキテクチャ
    add_heading(doc, "アーキテクチャ")
    doc.add_paragraph(
        "[ユーザー] → [ALB] → [ECS Fargate コンテナ] → [FastAPI + TF-IDF検索 + Anthropic API (Claude Sonnet)]"
    )
    doc.add_paragraph(
        "ユーザーがアップロードしたPDF/Wordファイルからテキストを抽出し、チャンクに分割。"
        "質問時にTF-IDFで関連チャンクを検索し、Claude Sonnetに渡して回答を生成します。"
    )

    # プロジェクト構成
    add_heading(doc, "プロジェクト構成")
    structure = [
        ".github/workflows/deploy.yml  - CI/CD パイプライン",
        "app/__init__.py",
        "app/main.py                   - FastAPI アプリケーション",
        "app/document_processor.py     - ドキュメント処理（PDF/Word）",
        "app/vector_store.py           - TF-IDF ベース検索エンジン",
        "app/rag_engine.py             - RAG エンジン（Claude Sonnet連携）",
        "static/index.html             - チャットUI",
        "Dockerfile                    - コンテナイメージ定義",
        "requirements.txt              - Python依存パッケージ",
        "README.md                     - プロジェクト説明",
    ]
    for item in structure:
        doc.add_paragraph(item, style="List Bullet")

    # 機能一覧
    add_heading(doc, "機能一覧")

    add_heading(doc, "ドキュメント管理", level=2)
    features_doc = [
        "PDF ファイルのアップロード・テキスト抽出",
        "Word (.docx) ファイルのアップロード・テキスト抽出",
        "複数ファイルの同時管理",
        "アップロード済みドキュメントの一覧表示",
        "全データの一括削除",
    ]
    for f in features_doc:
        doc.add_paragraph(f, style="List Bullet")

    add_heading(doc, "チャット機能", level=2)
    features_chat = [
        "自然言語による質問入力",
        "アップロード済みドキュメントに基づく回答生成",
        "回答の出典（ファイル名）表示",
        "リアルタイムのタイピングインジケーター",
    ]
    for f in features_chat:
        doc.add_paragraph(f, style="List Bullet")

    # API エンドポイント
    add_heading(doc, "API エンドポイント")
    add_table(doc, ["メソッド", "パス", "説明"], [
        ["GET", "/", "チャットUI"],
        ["POST", "/api/upload", "ドキュメントアップロード"],
        ["POST", "/api/chat", "質問送信・回答取得"],
        ["GET", "/api/stats", "アップロード状況確認"],
        ["POST", "/api/clear", "全データ削除"],
    ])

    # デプロイ構成
    add_heading(doc, "デプロイ構成")

    add_heading(doc, "CI/CD パイプライン (GitHub Actions)", level=2)
    steps = [
        "main ブランチへのプッシュをトリガー",
        "GitHub OIDC でAWS認証（シークレットキー不要）",
        "Dockerイメージのビルド",
        "Amazon ECR へプッシュ",
        "ECS Express Mode でデプロイ",
    ]
    for i, step in enumerate(steps, 1):
        doc.add_paragraph(f"{i}. {step}")

    add_heading(doc, "AWS リソース", level=2)
    add_table(doc, ["リソース", "名前/設定"], [
        ["ECR リポジトリ", "simple-rag"],
        ["ECS クラスター", "default"],
        ["ECS サービス", "simple-rag (Express Mode)"],
        ["CPU / メモリ", "1 vCPU / 2 GB"],
        ["オートスケーリング", "1〜20タスク (CPU 60%ターゲット)"],
        ["IAM ロール (Task Execution)", "ecsTaskExecutionRole"],
        ["IAM ロール (Infrastructure)", "ecsInfrastructureRoleForExpressServices"],
        ["IAM ロール (GitHub Actions)", "GitHubActionsRole-SimpleRAG"],
        ["OIDC プロバイダー", "token.actions.githubusercontent.com"],
    ])

    add_heading(doc, "デプロイURL", level=2)
    doc.add_paragraph("https://si-aecae9ee619d4ec8938daaa28c992793.ecs.ap-northeast-1.on.aws")

    # 開発中の課題と対応
    add_heading(doc, "開発中の課題と対応")
    add_table(doc, ["課題", "原因", "対応"], [
        ["faiss-cpu インストール失敗", "Python 3.14 対応バージョンなし", "バージョンを 1.14.2 に更新"],
        ["numpy ビルド失敗", "Python 3.14 + Visual Studio未インストール", "scikit-learn に切り替え"],
        ["scikit-learn インストール停止", "Python 3.14 用 wheel なし", "Pure Python実装に切り替え"],
        ["sentence-transformers メモリエラー", "Python 3.14 と Rust バインディング互換性問題", "TF-IDF (Pure Python) に変更"],
        ["Claude API 404エラー", "モデルID が無効", "claude-sonnet-4-6 に修正"],
        ["pip install 固まる", "前回の強制終了によるキャッシュ破損", "pip cache purge で解決"],
        ["GitHub Actions OIDC失敗", "AWSアカウントIDの誤り", "正しいID に修正"],
        ["ECS CPU/Memory エラー", "値の単位が不正", "Fargate互換の値に修正"],
        ["ECS サービスリンクロール不在", "初回ECS利用時に必要", "create-service-linked-role で作成"],
    ])

    # 設計判断
    add_heading(doc, "設計判断")

    add_heading(doc, "TF-IDF を採用した理由", level=2)
    doc.add_paragraph(
        "当初は sentence-transformers + FAISS によるセマンティック検索を予定していたが、"
        "Python 3.14 環境での互換性問題により、外部依存のない Pure Python 実装の TF-IDF に変更。"
        "文字 n-gram (2〜4文字) を使用することで、日本語テキストにも対応。"
    )

    add_heading(doc, "ECS Express Mode を採用した理由", level=2)
    reasons = [
        "AWS App Runner が2026年4月30日以降新規利用不可",
        "ECS Express Mode は App Runner の後継として推奨",
        "インフラ管理が自動化され、URL発行・SSL・オートスケーリングが標準装備",
        "Docker ローカルインストール不要（GitHub Actions でビルド）",
    ]
    for r in reasons:
        doc.add_paragraph(r, style="List Bullet")

    # 今後の改善案
    add_heading(doc, "今後の改善案")
    improvements = [
        "検索精度向上: Amazon Bedrock Titan Embeddings を使ったセマンティック検索への移行",
        "永続化: アップロードデータのS3保存 + ベクトルインデックスの永続化",
        "認証: Cognito による認証追加",
        "ファイル対応拡張: テキストファイル、Markdown、Excel 対応",
        "会話履歴: マルチターン対話のサポート",
        "コスト最適化: タスク数の最小値を0にしてスケールダウン",
    ]
    for i, item in enumerate(improvements, 1):
        doc.add_paragraph(f"{i}. {item}")

    # 作成日
    doc.add_paragraph("")
    doc.add_paragraph("作成日: 2026年5月29日")

    # Save
    output_path = "docs/development-report.docx"
    doc.save(output_path)
    print(f"レポートを保存しました: {output_path}")


if __name__ == "__main__":
    main()
