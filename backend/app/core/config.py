from pathlib import Path

from dotenv import load_dotenv
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parents[2]
load_dotenv(BASE_DIR / ".env")


class Settings:
    APP_NAME: str = "ShipBounty API"
    APP_ENV: str = "development"
    DATABASE_URL: str = "postgresql+psycopg2://postgres:postgres@localhost:5432/github_bounty_dispenser"
    GITHUB_WEBHOOK_SECRET: str = ""
    GITHUB_APP_ID: str = ""
    GITHUB_PRIVATE_KEY: str = ""
    GITHUB_OAUTH_CLIENT_ID: str = ""
    GITHUB_OAUTH_CLIENT_SECRET: str = ""
    GITHUB_OAUTH_REDIRECT_URI: str = "http://localhost:8000/auth/github/callback"
    FRONTEND_URL: str = "http://localhost:3000"
    AUTH_JWT_KEYS: str = ""
    AUTH_JWT_ISSUER: str = "shipbounty"
    AUTH_JWT_AUDIENCE: str = "shipbounty-api"
    AUTH_SESSION_TTL_SECONDS: int = 3600
    TOKEN_ENCRYPTION_KEYS: str = ""
    SESSION_COOKIE_NAME: str = "gbd_session"
    SESSION_COOKIE_DOMAIN: str = ""
    DEMO_MODE: bool = False
    DEMO_ACCESS_KEY: str = ""
    PLATFORM_ADMIN_GITHUB_IDS: str = ""
    RATE_LIMIT_REQUESTS: int = 120
    RATE_LIMIT_WINDOW_SECONDS: int = 60
    REDIS_URL: str = "redis://localhost:6379/0"
    CELERY_BROKER_URL: str = ""
    CELERY_MAX_RETRIES: int = 5
    CELERY_TASK_TIME_LIMIT: int = 300
    CELERY_TASK_SOFT_TIME_LIMIT: int = 270
    OUTBOX_DISPATCH_BATCH_SIZE: int = 100
    ANALYSIS_VERSION: str = "v1"
    EXTERNAL_ANALYZERS_ENABLED: bool = False
    ANALYZER_CONTAINER_RUNTIME: str = "docker"
    ANALYZER_IMAGES_JSON: str = "{}"
    ANALYZER_TIMEOUT_SECONDS: int = 120
    ANALYZER_MAX_OUTPUT_BYTES: int = 1048576
    AI_REVIEW_PROMPT_VERSION: str = "ai-review-v1"
    AI_REVIEW_PROVIDER: str = "openai"
    OPENAI_API_KEY: str = ""
    OPENAI_API_BASE_URL: str = "https://api.openai.com"
    OPENAI_AI_REVIEW_MODEL: str = ""
    OPENAI_MODERATION_MODEL: str = "omni-moderation-latest"
    AI_REVIEW_TIMEOUT_SECONDS: int = 90
    AI_REVIEW_DAILY_LIMIT: int = 50
    GEMINI_API_KEY: str = ""
    GEMINI_API_BASE_URL: str = "https://generativelanguage.googleapis.com"
    GEMINI_AI_REVIEW_MODEL: str = "gemini-flash-latest"
    GEMINI_TIMEOUT_SECONDS: int = 120
    GEMINI_MAX_OUTPUT_TOKENS: int = 2500
    ALLOW_MANUAL_AI_REVIEW_STATE: bool = False
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USERNAME: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM_EMAIL: str = ""
    SMTP_USE_TLS: bool = True
    NOTIFICATION_MAX_RETRIES: int = 5
    PAYOUTS_ENABLED: bool = False
    PAYOUTS_EMERGENCY_PAUSED: bool = True
    PAYOUTS_ALLOW_MAINNET: bool = False
    ALLOW_MANUAL_PAYOUT_STATE: bool = False
    PAYOUT_SUBMISSION_RECOVERY_MAX_ATTEMPTS: int = 5
    PAYOUT_PROVIDER_BASE_URL: str = ""
    PAYOUT_PROVIDER_API_TOKEN: str = ""
    PAYOUT_PROVIDER_TIMEOUT_SECONDS: int = 20
    PAYOUT_RECONCILIATION_INTERVAL_SECONDS: int = 30
    BASE_SEPOLIA_CHAIN_ID: int = 84532
    BASE_SEPOLIA_USDC_CONTRACT: str = (
        "0x036CbD53842c5426634e7929541eC2318f3dCF7e"
    )
    BASE_SEPOLIA_EXPLORER_URL: str = "https://sepolia-explorer.base.org"

    def __init__(self) -> None:
        import os

        self.APP_NAME = os.getenv("APP_NAME", self.APP_NAME)
        self.APP_ENV = os.getenv("APP_ENV", self.APP_ENV)
        self.DATABASE_URL = os.getenv("DATABASE_URL", self.DATABASE_URL)
        self.GITHUB_WEBHOOK_SECRET = os.getenv("GITHUB_WEBHOOK_SECRET", self.GITHUB_WEBHOOK_SECRET)
        self.GITHUB_APP_ID = os.getenv("GITHUB_APP_ID", self.GITHUB_APP_ID)
        self.GITHUB_PRIVATE_KEY = os.getenv("GITHUB_PRIVATE_KEY", self.GITHUB_PRIVATE_KEY)
        self.GITHUB_OAUTH_CLIENT_ID = os.getenv(
            "GITHUB_OAUTH_CLIENT_ID", self.GITHUB_OAUTH_CLIENT_ID
        )
        self.GITHUB_OAUTH_CLIENT_SECRET = os.getenv(
            "GITHUB_OAUTH_CLIENT_SECRET", self.GITHUB_OAUTH_CLIENT_SECRET
        )
        self.GITHUB_OAUTH_REDIRECT_URI = os.getenv(
            "GITHUB_OAUTH_REDIRECT_URI", self.GITHUB_OAUTH_REDIRECT_URI
        )
        self.FRONTEND_URL = os.getenv("FRONTEND_URL", self.FRONTEND_URL)
        self.AUTH_JWT_KEYS = os.getenv("AUTH_JWT_KEYS", self.AUTH_JWT_KEYS)
        self.AUTH_JWT_ISSUER = os.getenv("AUTH_JWT_ISSUER", self.AUTH_JWT_ISSUER)
        self.AUTH_JWT_AUDIENCE = os.getenv(
            "AUTH_JWT_AUDIENCE", self.AUTH_JWT_AUDIENCE
        )
        self.AUTH_SESSION_TTL_SECONDS = int(
            os.getenv("AUTH_SESSION_TTL_SECONDS", str(self.AUTH_SESSION_TTL_SECONDS))
        )
        self.TOKEN_ENCRYPTION_KEYS = os.getenv(
            "TOKEN_ENCRYPTION_KEYS", self.TOKEN_ENCRYPTION_KEYS
        )
        self.SESSION_COOKIE_NAME = os.getenv(
            "SESSION_COOKIE_NAME", self.SESSION_COOKIE_NAME
        )
        self.SESSION_COOKIE_DOMAIN = os.getenv(
            "SESSION_COOKIE_DOMAIN", self.SESSION_COOKIE_DOMAIN
        )
        self.DEMO_MODE = os.getenv(
            "DEMO_MODE", str(self.DEMO_MODE)
        ).lower() in {"1", "true", "yes", "on"}
        self.DEMO_ACCESS_KEY = os.getenv(
            "DEMO_ACCESS_KEY", self.DEMO_ACCESS_KEY
        )
        self.PLATFORM_ADMIN_GITHUB_IDS = os.getenv(
            "PLATFORM_ADMIN_GITHUB_IDS", self.PLATFORM_ADMIN_GITHUB_IDS
        )
        if self.DEMO_MODE and self.APP_ENV.lower() == "production":
            raise RuntimeError("DEMO_MODE cannot be enabled in production")
        self.RATE_LIMIT_REQUESTS = int(
            os.getenv("RATE_LIMIT_REQUESTS", str(self.RATE_LIMIT_REQUESTS))
        )
        self.RATE_LIMIT_WINDOW_SECONDS = int(
            os.getenv(
                "RATE_LIMIT_WINDOW_SECONDS", str(self.RATE_LIMIT_WINDOW_SECONDS)
            )
        )
        self.REDIS_URL = os.getenv("REDIS_URL", self.REDIS_URL)
        self.CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", self.REDIS_URL)
        self.CELERY_MAX_RETRIES = int(os.getenv("CELERY_MAX_RETRIES", str(self.CELERY_MAX_RETRIES)))
        self.CELERY_TASK_TIME_LIMIT = int(
            os.getenv("CELERY_TASK_TIME_LIMIT", str(self.CELERY_TASK_TIME_LIMIT))
        )
        self.CELERY_TASK_SOFT_TIME_LIMIT = int(
            os.getenv("CELERY_TASK_SOFT_TIME_LIMIT", str(self.CELERY_TASK_SOFT_TIME_LIMIT))
        )
        self.OUTBOX_DISPATCH_BATCH_SIZE = int(
            os.getenv("OUTBOX_DISPATCH_BATCH_SIZE", str(self.OUTBOX_DISPATCH_BATCH_SIZE))
        )
        self.ANALYSIS_VERSION = os.getenv("ANALYSIS_VERSION", self.ANALYSIS_VERSION)
        self.EXTERNAL_ANALYZERS_ENABLED = os.getenv(
            "EXTERNAL_ANALYZERS_ENABLED",
            str(self.EXTERNAL_ANALYZERS_ENABLED),
        ).lower() in {"1", "true", "yes", "on"}
        self.ANALYZER_CONTAINER_RUNTIME = os.getenv(
            "ANALYZER_CONTAINER_RUNTIME", self.ANALYZER_CONTAINER_RUNTIME
        )
        self.ANALYZER_IMAGES_JSON = os.getenv(
            "ANALYZER_IMAGES_JSON", self.ANALYZER_IMAGES_JSON
        )
        self.ANALYZER_TIMEOUT_SECONDS = int(
            os.getenv(
                "ANALYZER_TIMEOUT_SECONDS",
                str(self.ANALYZER_TIMEOUT_SECONDS),
            )
        )
        self.ANALYZER_MAX_OUTPUT_BYTES = int(
            os.getenv(
                "ANALYZER_MAX_OUTPUT_BYTES",
                str(self.ANALYZER_MAX_OUTPUT_BYTES),
            )
        )
        self.AI_REVIEW_PROMPT_VERSION = os.getenv(
            "AI_REVIEW_PROMPT_VERSION", self.AI_REVIEW_PROMPT_VERSION
        )
        self.AI_REVIEW_PROVIDER = os.getenv(
            "AI_REVIEW_PROVIDER", self.AI_REVIEW_PROVIDER
        )
        self.OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", self.OPENAI_API_KEY)
        self.OPENAI_API_BASE_URL = os.getenv(
            "OPENAI_API_BASE_URL", self.OPENAI_API_BASE_URL
        )
        self.OPENAI_AI_REVIEW_MODEL = os.getenv(
            "OPENAI_AI_REVIEW_MODEL", self.OPENAI_AI_REVIEW_MODEL
        )
        self.OPENAI_MODERATION_MODEL = os.getenv(
            "OPENAI_MODERATION_MODEL", self.OPENAI_MODERATION_MODEL
        )
        self.AI_REVIEW_TIMEOUT_SECONDS = int(
            os.getenv(
                "AI_REVIEW_TIMEOUT_SECONDS",
                str(self.AI_REVIEW_TIMEOUT_SECONDS),
            )
        )
        self.AI_REVIEW_DAILY_LIMIT = int(
            os.getenv(
                "AI_REVIEW_DAILY_LIMIT",
                str(self.AI_REVIEW_DAILY_LIMIT),
            )
        )
        self.GEMINI_API_KEY = os.getenv(
            "GEMINI_API_KEY", self.GEMINI_API_KEY
        )
        self.GEMINI_API_BASE_URL = os.getenv(
            "GEMINI_API_BASE_URL", self.GEMINI_API_BASE_URL
        )
        self.GEMINI_AI_REVIEW_MODEL = os.getenv(
            "GEMINI_AI_REVIEW_MODEL", self.GEMINI_AI_REVIEW_MODEL
        )
        self.GEMINI_TIMEOUT_SECONDS = int(
            os.getenv(
                "GEMINI_TIMEOUT_SECONDS",
                str(self.GEMINI_TIMEOUT_SECONDS),
            )
        )
        self.GEMINI_MAX_OUTPUT_TOKENS = int(
            os.getenv(
                "GEMINI_MAX_OUTPUT_TOKENS",
                str(self.GEMINI_MAX_OUTPUT_TOKENS),
            )
        )
        if self.AI_REVIEW_DAILY_LIMIT < 0:
            raise RuntimeError("AI_REVIEW_DAILY_LIMIT cannot be negative")
        if self.GEMINI_MAX_OUTPUT_TOKENS <= 0:
            raise RuntimeError("GEMINI_MAX_OUTPUT_TOKENS must be positive")
        self.ALLOW_MANUAL_AI_REVIEW_STATE = os.getenv(
            "ALLOW_MANUAL_AI_REVIEW_STATE",
            str(self.ALLOW_MANUAL_AI_REVIEW_STATE),
        ).lower() in {"1", "true", "yes", "on"}
        if (
            self.ALLOW_MANUAL_AI_REVIEW_STATE
            and self.APP_ENV.lower() == "production"
        ):
            raise RuntimeError(
                "ALLOW_MANUAL_AI_REVIEW_STATE cannot be enabled in production"
            )
        self.SMTP_HOST = os.getenv("SMTP_HOST", self.SMTP_HOST)
        self.SMTP_PORT = int(os.getenv("SMTP_PORT", str(self.SMTP_PORT)))
        self.SMTP_USERNAME = os.getenv("SMTP_USERNAME", self.SMTP_USERNAME)
        self.SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", self.SMTP_PASSWORD)
        self.SMTP_FROM_EMAIL = os.getenv(
            "SMTP_FROM_EMAIL", self.SMTP_FROM_EMAIL
        )
        self.SMTP_USE_TLS = os.getenv(
            "SMTP_USE_TLS", str(self.SMTP_USE_TLS)
        ).lower() in {"1", "true", "yes", "on"}
        self.NOTIFICATION_MAX_RETRIES = int(
            os.getenv(
                "NOTIFICATION_MAX_RETRIES",
                str(self.NOTIFICATION_MAX_RETRIES),
            )
        )
        self.PAYOUTS_ENABLED = os.getenv(
            "PAYOUTS_ENABLED", str(self.PAYOUTS_ENABLED)
        ).lower() in {"1", "true", "yes", "on"}
        self.PAYOUTS_EMERGENCY_PAUSED = os.getenv(
            "PAYOUTS_EMERGENCY_PAUSED",
            str(self.PAYOUTS_EMERGENCY_PAUSED),
        ).lower() in {"1", "true", "yes", "on"}
        self.PAYOUTS_ALLOW_MAINNET = os.getenv(
            "PAYOUTS_ALLOW_MAINNET", str(self.PAYOUTS_ALLOW_MAINNET)
        ).lower() in {"1", "true", "yes", "on"}
        self.ALLOW_MANUAL_PAYOUT_STATE = os.getenv(
            "ALLOW_MANUAL_PAYOUT_STATE",
            str(self.ALLOW_MANUAL_PAYOUT_STATE),
        ).lower() in {"1", "true", "yes", "on"}
        if self.ALLOW_MANUAL_PAYOUT_STATE and self.APP_ENV.lower() == "production":
            raise RuntimeError(
                "ALLOW_MANUAL_PAYOUT_STATE cannot be enabled in production"
            )
        self.PAYOUT_SUBMISSION_RECOVERY_MAX_ATTEMPTS = int(
            os.getenv(
                "PAYOUT_SUBMISSION_RECOVERY_MAX_ATTEMPTS",
                str(self.PAYOUT_SUBMISSION_RECOVERY_MAX_ATTEMPTS),
            )
        )
        self.PAYOUT_PROVIDER_BASE_URL = os.getenv(
            "PAYOUT_PROVIDER_BASE_URL", self.PAYOUT_PROVIDER_BASE_URL
        )
        self.PAYOUT_PROVIDER_API_TOKEN = os.getenv(
            "PAYOUT_PROVIDER_API_TOKEN", self.PAYOUT_PROVIDER_API_TOKEN
        )
        self.PAYOUT_PROVIDER_TIMEOUT_SECONDS = int(
            os.getenv(
                "PAYOUT_PROVIDER_TIMEOUT_SECONDS",
                str(self.PAYOUT_PROVIDER_TIMEOUT_SECONDS),
            )
        )
        self.PAYOUT_RECONCILIATION_INTERVAL_SECONDS = int(
            os.getenv(
                "PAYOUT_RECONCILIATION_INTERVAL_SECONDS",
                str(self.PAYOUT_RECONCILIATION_INTERVAL_SECONDS),
            )
        )
        self.BASE_SEPOLIA_CHAIN_ID = int(
            os.getenv(
                "BASE_SEPOLIA_CHAIN_ID", str(self.BASE_SEPOLIA_CHAIN_ID)
            )
        )
        self.BASE_SEPOLIA_USDC_CONTRACT = os.getenv(
            "BASE_SEPOLIA_USDC_CONTRACT",
            self.BASE_SEPOLIA_USDC_CONTRACT,
        )
        self.BASE_SEPOLIA_EXPLORER_URL = os.getenv(
            "BASE_SEPOLIA_EXPLORER_URL",
            self.BASE_SEPOLIA_EXPLORER_URL,
        )


settings = Settings()
