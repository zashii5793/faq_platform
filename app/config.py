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

    faq_master_dir: Path = Path("./data/faq_master")
    index_path: Path = Path("./data/index.json")

    masking_industry: str = "general"

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
