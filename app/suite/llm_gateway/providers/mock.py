class MockLLMProvider:
    def complete(self, *, model_id: str, prompt: str) -> str:
        normalized = " ".join(prompt.split())
        preview = normalized[:180]
        return f"[mock:{model_id}] {preview}"

