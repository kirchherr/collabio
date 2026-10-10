class MockLLMProvider:
    def complete(self, *, model_id: str, prompt: str) -> str:
        if "OUTLINE_FORMAT_V1" in prompt:
            return "- Main topic\n  - Supporting point\n- Next step"
        normalized = " ".join(prompt.split())
        preview = normalized[:180]
        return f"[mock:{model_id}] {preview}"
