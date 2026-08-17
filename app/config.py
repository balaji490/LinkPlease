import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()

@dataclass
class Settings:
    PSEUDOGRAM_BASE_URL: str = os.getenv("PSEUDOGRAM_BASE_URL", "https://pseudogram-api.onrender.com").rstrip("/")
    PSEUDOGRAM_API_KEY: str = os.getenv("PSEUDOGRAM_API_KEY", "")
    DATABASE_PATH: str = os.getenv("DATABASE_PATH", "linkplease.db")
    
    # Rate limit: PseudoGram allows 10 requests per rolling 60s
    RATE_LIMIT_REQUESTS: int = int(os.getenv("RATE_LIMIT_REQUESTS", "10"))
    RATE_LIMIT_WINDOW_SECONDS: float = float(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "60.0"))
    
    # Max send retry attempts on 500 or network failure
    MAX_RETRIES: int = int(os.getenv("MAX_RETRIES", "5"))
    INITIAL_RETRY_BACKOFF_SECONDS: float = float(os.getenv("INITIAL_RETRY_BACKOFF_SECONDS", "1.0"))
    MAX_RETRY_BACKOFF_SECONDS: float = float(os.getenv("MAX_RETRY_BACKOFF_SECONDS", "30.0"))
    
    # Worker and Reconciler intervals
    WORKER_POLL_INTERVAL: float = float(os.getenv("WORKER_POLL_INTERVAL", "0.2"))
    RECONCILER_INTERVAL: float = float(os.getenv("RECONCILER_INTERVAL", "1.5"))
    RECONCILER_BATCH_SIZE: int = int(os.getenv("RECONCILER_BATCH_SIZE", "20"))
    
    # Signature verification
    VERIFY_SIGNATURE: bool = os.getenv("VERIFY_SIGNATURE", "false").lower() in ("true", "1", "yes")
    
    # Server host & port
    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", "8000"))

settings = Settings()
