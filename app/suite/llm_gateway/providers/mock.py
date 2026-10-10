class MockLLMProvider:
    def complete(self, *, model_id: str, prompt: str) -> str:
        if "RISK_MARKING_FORMAT_V1" in prompt:
            return "STATUS: risks\nRISK: high|commitment|1|Confirm the named commitment before relying on it."
        if "POLICY_COMPARISON_FORMAT_V1" in prompt:
            return (
                "STATUS: unclear\n"
                "FINDING: The document partly reflects the selected policy.\n"
                "RECOMMENDATION: Verify the named obligation against the cited policy version."
            )
        if "OUTLINE_FORMAT_V1" in prompt:
            return "- Main topic\n  - Supporting point\n- Next step"
        normalized = " ".join(prompt.split())
        preview = normalized[:180]
        return f"[mock:{model_id}] {preview}"
