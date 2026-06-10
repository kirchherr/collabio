from typing import Protocol


class LLMProvider(Protocol):
    def complete(self, *, model_id: str, prompt: str) -> str:
        """Return a model completion for the prompt."""
