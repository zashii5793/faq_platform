from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    product_name: str = "Inquira"
    org_name: str = "（貴社）"
    assistant_role: str = "社内ヘルプデスク"

    anthropic_api_key: str = ""
    claude_model: str = "claude-sonnet-4-6"

    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://localhost:8000/auth/callback"

    allowed_domain: str = ""
    allowed_emails: str = ""

    session_secret: str = "dev-secret-change-me"

    # --- データ保存先（環境変数で全て上書き可能） ---
    faq_master_dir: Path = Path("./data/faq_master")
    index_path: Path = Path("./data/index.json")
    audit_log_dir: Path = Path("./data/audit")
    feedback_path: Path = Path("./data/feedback_scores.json")
    org_settings_path: Path = Path("./data/org_settings.json")
    raw_upload_dir: Path = Path("./data/raw")
    # 共有Q&A のメタ情報（投票数・解決マーカー）
    shared_qa_meta_path: Path = Path("./data/shared_qa_meta.json")

    masking_industry: str = "general"

    # 検索バックエンド: tfidf (デフォルト・軽量) / e5-small / e5-large / e5-base
    embedding_backend: str = "tfidf"
    # Embedding 使用時のキャッシュ保存先
    embedding_cache_path: Path = Path("./data/embeddings.npz")

    # 確信度: top-1 スコアがこの値未満ならLLM呼び出しを行わず「該当情報なし」を返す
    # TF-IDF char_wb の経験値: 関連質問は 0.15+, ノイズマッチは 0.05-0.07 程度
    min_score_threshold: float = 0.08

    host: str = "0.0.0.0"
    port: int = 8000

    demo_mode: bool = False

    @property
    def allowed_email_set(self) -> set[str]:
        return {e.strip().lower() for e in self.allowed_emails.split(",") if e.strip()}


settings = Settings()
