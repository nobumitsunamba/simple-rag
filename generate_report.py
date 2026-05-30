"""Generate development report as a Word document."""

from docx import Document
from docx.shared import Pt, Cm
from docx.enum.text import WD_ALIGN_PARAGRAPH


def add_table(doc, headers, rows):
    table = doc.add_table(rows=1, cols=len(headers))
    table.style = "Light Grid Accent 1"
    for i, header in enumerate(headers):
        table.rows[0].cells[i].text = header
    for row_data in rows:
        row = table.add_row()
        for i, cell_text in enumerate(row_data):
            row.cells[i].text = cell_text
    return table


def main():
    doc = Document()

    doc.add_heading("Simple RAG アプリケーション 開発レポート", level=0)
    doc.add_paragraph(f"最終更新: 2026年5月30日")
    doc.add_paragraph("")

    # === 概要 ===
    doc.add_heading("1. 概要", level=1)
    doc.add_paragraph(
        "PDF・Word・Excel・PowerPoint・CSV・テキストファイルをアップロードし、"
        "その内容に基づいてチャット形式で質問に回答するRAG（Retrieval-Augmented Generation）アプリケーション。"
        "社内業務マニュアルや帳票を複数人で共有し、繰り返し利用することを想定している。"
    )

    # === 技術スタック ===
    doc.add_heading("2. 技術スタック", level=1)
    add_table(doc, ["カテゴリ", "技術"], [
        ["バックエンド", "Python 3.11 / FastAPI"],
        ["LLM (回答生成)", "Claude Sonnet 4.6 (Anthropic API)"],
        ["埋め込み (検索)", "Amazon Bedrock Titan Text Embeddings V2 (256次元)"],
        ["ベクトル検索", "コサイン類似度 (Pure Python)"],
        ["ナレッジ永続化", "Amazon S3"],
        ["認証", "Amazon Cognito User Pool"],
        ["ドキュメント処理", "PyPDF2, python-docx, openpyxl, python-pptx"],
        ["フロントエンド", "HTML / CSS / JavaScript (単一ファイル)"],
        ["インフラ", "AWS ECS Express Mode (Fargate)"],
        ["CI/CD", "GitHub Actions (OIDC認証)"],
        ["コンテナレジストリ", "Amazon ECR"],
    ])

    # === アーキテクチャ ===
    doc.add_heading("3. アーキテクチャ", level=1)
    doc.add_paragraph(
        "ユーザー → ALB (HTTPS/SSL自動) → ECS Fargate コンテナ → FastAPI アプリケーション"
    )
    doc.add_paragraph("アプリケーション内部の処理フロー:")
    steps = [
        "ファイルアップロード → テキスト抽出 → 文単位チャンク分割 → Bedrock Titan Embeddings でベクトル化 → メモリ保持",
        "ナレッジベース保存 → チャンク + メタデータ + 埋め込みベクトルをJSON化 → S3に保存",
        "質問応答 → クエリ拡張 → 複数クエリで検索 → リランキング → 周辺コンテキスト結合 → Claude Sonnet で回答生成",
    ]
    for s in steps:
        doc.add_paragraph(s, style="List Bullet")

    # === 機能一覧 ===
    doc.add_heading("4. 機能一覧", level=1)

    doc.add_heading("4.1 認証", level=2)
    features = [
        "Cognito User Pool によるメール + パスワード認証",
        "新規登録 → メール確認コード → ログイン",
        "ログアウト機能",
        "未認証アクセスはログイン画面にリダイレクト",
    ]
    for f in features:
        doc.add_paragraph(f, style="List Bullet")

    doc.add_heading("4.2 ドキュメント管理", level=2)
    features = [
        "対応形式: PDF / Word (.docx) / Excel (.xlsx) / PowerPoint (.pptx) / CSV / テキスト (.txt, .md)",
        "複数ファイル同時アップロード（ファイル選択・ドラッグ&ドロップ）",
        "大容量ファイルのバックグラウンド処理（進捗表示付き）",
        "ファイル単位での削除",
        "Bedrock スロットリング対策（指数バックオフ + 並列数制限）",
    ]
    for f in features:
        doc.add_paragraph(f, style="List Bullet")

    doc.add_heading("4.3 ナレッジベース管理", level=2)
    features = [
        "名前を付けて保存（S3に永続化）",
        "保存済みナレッジベースの一覧表示・読み込み",
        "ナレッジベースへのファイル追加",
        "上書き保存（ファイル追加/削除後にアクティブ化）",
        "ナレッジベースの削除",
        "埋め込みベクトルごと保存するため、読み込み時に再計算不要",
    ]
    for f in features:
        doc.add_paragraph(f, style="List Bullet")

    doc.add_heading("4.4 チャット (RAG)", level=2)
    features = [
        "会話履歴の保持（直近10往復）",
        "クエリ拡張: 質問の意図を分析し、複数の検索クエリを自動生成",
        "リランキング: Claude が検索結果の関連度を再評価",
        "周辺コンテキスト: ヒットチャンクの前後も結合して情報量を確保",
        "確信度表示（検索スコアに基づく）",
        "出典表示（ファイル名 + PDFページ番号）",
        "フィードバックボタン（👍 役立った / 👎 不十分）",
        "チャット履歴のWord (.docx) エクスポート",
        "検索結果の多様性確保（1ファイルあたり最大3チャンク）",
    ]
    for f in features:
        doc.add_paragraph(f, style="List Bullet")

    doc.add_heading("4.5 UI/UX", level=2)
    features = [
        "ライトモード / ダークモード切替（ブラウザに設定保存）",
        "スマートフォン対応（レスポンシブデザイン）",
        "ヘッダーにLLMモデル名・ログインユーザー表示",
        "ナレッジベース選択をトップに配置",
    ]
    for f in features:
        doc.add_paragraph(f, style="List Bullet")

    # === RAG処理フロー ===
    doc.add_heading("5. RAG処理フロー（質問応答）", level=1)
    doc.add_paragraph("1つの質問に対して以下の処理が実行される:")
    steps = [
        "1. クエリ拡張: Claude が質問の意図を分析し、3つの追加検索クエリを生成",
        "2. ベクトル検索: 元の質問 + 3つの拡張クエリで候補チャンクを収集（重複排除）",
        "3. リランキング: Claude が候補チャンク（最大15件）の関連度を1〜5で評価",
        "4. フィルタリング: 関連度3以上のチャンクのみ残す（上位6件）",
        "5. 周辺コンテキスト: ヒットチャンクの前後チャンクを結合",
        "6. 回答生成: 構造化プロンプト（結論→根拠→補足）で Claude が回答",
    ]
    for s in steps:
        doc.add_paragraph(s)
    doc.add_paragraph("")
    doc.add_paragraph("Claude API 呼び出し回数: 1質問あたり3回（拡張 + リランキング + 回答）")

    # === デプロイ構成 ===
    doc.add_heading("6. デプロイ構成", level=1)

    doc.add_heading("6.1 CI/CD パイプライン", level=2)
    steps = [
        "main ブランチへの git push をトリガー",
        "GitHub OIDC で AWS 認証（シークレットキー不要）",
        "Docker イメージのビルド（GitHub Actions ランナー上）",
        "Amazon ECR へプッシュ",
        "ECS Express Mode でデプロイ（ローリングアップデート）",
    ]
    for i, s in enumerate(steps, 1):
        doc.add_paragraph(f"{i}. {s}")

    doc.add_heading("6.2 AWS リソース", level=2)
    add_table(doc, ["リソース", "設定"], [
        ["ECS サービス", "simple-rag (Express Mode, Fargate)"],
        ["CPU / メモリ", "1 vCPU / 2 GB"],
        ["オートスケーリング", "0〜20タスク (CPU 60%ターゲット)"],
        ["ECR リポジトリ", "simple-rag"],
        ["S3 バケット", "simple-rag-knowledge-032401368831"],
        ["Cognito User Pool", "simple-rag-users"],
        ["IAM ロール (Task)", "ecsTaskRole-SimpleRAG"],
        ["IAM ロール (Execution)", "ecsTaskExecutionRole"],
        ["IAM ロール (Infrastructure)", "ecsInfrastructureRoleForExpressServices"],
        ["IAM ロール (GitHub Actions)", "GitHubActionsRole-SimpleRAG"],
    ])

    doc.add_heading("6.3 コスト最適化", level=2)
    doc.add_paragraph(
        "ECS の最小タスク数を 0 に設定。アクセスがない時間帯はタスクが自動停止し、"
        "Fargate の課金がゼロになる。次のアクセス時に自動起動（コールドスタート: 30〜60秒）。"
    )

    # === チャンク分割戦略 ===
    doc.add_heading("7. チャンク分割戦略", level=1)
    add_table(doc, ["パラメータ", "値"], [
        ["チャンクサイズ", "700文字"],
        ["オーバーラップ", "150文字"],
        ["分割単位", "文単位（日本語句点・英語ピリオドで分割）"],
        ["段落境界", "チャンクサイズの60%以上で段落境界を優先的に分割点にする"],
        ["日本語対応", "「。」「！」「？」を文末として認識"],
    ])

    # === API エンドポイント ===
    doc.add_heading("8. API エンドポイント", level=1)
    add_table(doc, ["メソッド", "パス", "説明"], [
        ["GET", "/", "メインUI"],
        ["GET", "/login", "ログイン画面"],
        ["POST", "/api/auth/signup", "新規登録"],
        ["POST", "/api/auth/confirm", "メール確認"],
        ["POST", "/api/auth/signin", "ログイン"],
        ["GET", "/api/auth/me", "ユーザー情報取得"],
        ["POST", "/api/upload", "ファイルアップロード"],
        ["GET", "/api/processing/{filename}", "処理状況確認"],
        ["POST", "/api/chat", "質問送信・回答取得"],
        ["GET", "/api/stats", "統計情報"],
        ["DELETE", "/api/document/{filename}", "ファイル削除"],
        ["POST", "/api/clear", "セッションクリア"],
        ["POST", "/api/knowledge/save", "ナレッジベース保存"],
        ["POST", "/api/knowledge/load", "ナレッジベース読み込み"],
        ["POST", "/api/knowledge/append", "ナレッジベースに追加"],
        ["GET", "/api/knowledge/list", "ナレッジベース一覧"],
        ["DELETE", "/api/knowledge/{name}", "ナレッジベース削除"],
        ["POST", "/api/export/word", "チャット履歴エクスポート"],
    ])

    # === セキュリティ ===
    doc.add_heading("9. セキュリティ", level=1)
    items = [
        "Cognito によるユーザー認証（メール + パスワード）",
        "GitHub OIDC による CI/CD 認証（長期キー不使用）",
        "ECS Task Role による最小権限の原則（Bedrock, S3, Cognito のみ）",
        "HTTPS 自動（ALB + ACM）",
        "API キーは環境変数で管理（コードに含めない）",
        "GitHub Push Protection によるシークレット漏洩防止",
    ]
    for item in items:
        doc.add_paragraph(item, style="List Bullet")

    # === 今後の改善案 ===
    doc.add_heading("10. 今後の改善案", level=1)
    items = [
        "社内AD連携（Azure AD / ADFS との SAML/OIDC 連携）",
        "ナレッジベースのアクセス制御（部署ごとの権限管理）",
        "ハイブリッド検索（セマンティック + キーワード完全一致の統合）",
        "利用ログ・監査（誰がいつ何を質問したかの記録）",
        "回答のストリーミング表示（Server-Sent Events）",
        "ファイルのOCR対応（スキャンPDFへの対応）",
    ]
    for i, item in enumerate(items, 1):
        doc.add_paragraph(f"{i}. {item}")

    # Save
    output_path = "docs/development-report.docx"
    doc.save(output_path)
    print(f"レポートを保存しました: {output_path}")


if __name__ == "__main__":
    main()
