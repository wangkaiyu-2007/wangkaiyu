import httpx
from config import ANYTHINGLLM_API_KEY, ANYTHINGLLM_BASE_URL, ANYTHINGLLM_WORKSPACE_SLUG


class AnythingLLMClient:
    def __init__(self) -> None:
        self.base_url = ANYTHINGLLM_BASE_URL.rstrip("/")
        self.headers = {
            "Authorization": f"Bearer {ANYTHINGLLM_API_KEY}",
            "Content-Type": "application/json",
        }
        self.workspace_slug = ANYTHINGLLM_WORKSPACE_SLUG

    async def chat(self, message: str) -> str:
        url = f"{self.base_url}/v1/workspace/{self.workspace_slug}/chat"
        payload = {"message": message, "mode": "chat"}
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(url, json=payload, headers=self.headers)
            resp.raise_for_status()
            data = resp.json()
            # AnythingLLM 返回的响应结构是 {textResponse: "...", sources: [...], ...}
            if data.get("error"):
                raise RuntimeError(f"AnythingLLM error: {data['error']}")
            return data.get("textResponse", "")

    async def list_workspaces(self) -> list[dict]:
        url = f"{self.base_url}/v1/workspaces"
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, headers=self.headers)
            resp.raise_for_status()
            data = resp.json()
            if not data.get("success"):
                raise RuntimeError(f"AnythingLLM error: {data.get('error', 'unknown')}")
            return data["data"]["workspaces"]


_client: AnythingLLMClient | None = None


def get_client() -> AnythingLLMClient:
    global _client
    if _client is None:
        _client = AnythingLLMClient()
    return _client
