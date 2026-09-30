import os
from pathlib import Path
from dotenv import load_dotenv

# 加载 .env 文件（使用绝对路径）
env_path = Path(__file__).parent / ".env"
load_dotenv(env_path)

ANYTHINGLLM_API_KEY: str = os.getenv("ANYTHINGLLM_API_KEY", "")
ANYTHINGLLM_BASE_URL: str = os.getenv("ANYTHINGLLM_BASE_URL", "http://localhost:3001/api")
ANYTHINGLLM_WORKSPACE_SLUG: str = os.getenv("ANYTHINGLLM_WORKSPACE_SLUG", "")


def validate() -> None:
    if not ANYTHINGLLM_API_KEY:
        raise ValueError("ANYTHINGLLM_API_KEY is not set. Add it to .env or environment variables.")
    if not ANYTHINGLLM_WORKSPACE_SLUG:
        raise ValueError("ANYTHINGLLM_WORKSPACE_SLUG is not set. Add it to .env or environment variables.")
