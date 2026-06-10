import httpx


class OllamaProvider:
    def __init__(self, *, base_url: str, timeout_seconds: float = 30.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def complete(self, *, model_id: str, prompt: str) -> str:
        response = httpx.post(
            f"{self.base_url}/api/generate",
            json={"model": model_id, "prompt": prompt, "stream": False},
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        return str(payload.get("response", ""))
