from suite.ai_control_plane.models import DataClass, TenantPolicy


class InMemoryTenantPolicyRepository:
    def __init__(self, policies: dict[str, TenantPolicy]) -> None:
        self._policies = policies

    @classmethod
    def default(cls) -> "InMemoryTenantPolicyRepository":
        demo_policy = TenantPolicy(
            tenant_id="tenant-demo",
            ai_enabled=True,
            allowed_model_ids={"mock-summarizer"},
            allowed_data_classes={DataClass.INTERNAL, DataClass.PERSONAL},
            rag_enabled=True,
            voice_enabled=True,
            raw_audio_storage_allowed=False,
        )
        return cls(policies={demo_policy.tenant_id: demo_policy})

    def get(self, tenant_id: str) -> TenantPolicy:
        try:
            return self._policies[tenant_id]
        except KeyError as exc:
            raise LookupError(f"Unknown tenant policy: {tenant_id}") from exc
