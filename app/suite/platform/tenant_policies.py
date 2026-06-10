import json
from pathlib import Path
from typing import Any

from suite.ai_control_plane.models import DataClass, TenantPolicy


def write_json_array(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(json.dumps(rows, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temp_path.replace(path)


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

    def rows(self) -> list[dict[str, Any]]:
        return [policy.model_dump(mode="json") for policy in self._policies.values()]

    def update(self, policy: TenantPolicy) -> TenantPolicy:
        if policy.tenant_id not in self._policies:
            raise LookupError(f"Unknown tenant policy: {policy.tenant_id}")
        self._policies[policy.tenant_id] = policy
        return policy


class JsonFileTenantPolicyRepository(InMemoryTenantPolicyRepository):
    def __init__(self, policies: dict[str, TenantPolicy], path: Path) -> None:
        super().__init__(policies=policies)
        self.path = path

    @classmethod
    def load_or_seed(cls, path: Path, seed: InMemoryTenantPolicyRepository) -> "JsonFileTenantPolicyRepository":
        if not path.exists():
            write_json_array(path, seed.rows())
        rows = json.loads(path.read_text(encoding="utf-8"))
        policies = {row["tenant_id"]: TenantPolicy.model_validate(row) for row in rows}
        return cls(policies=policies, path=path)

    def update(self, policy: TenantPolicy) -> TenantPolicy:
        updated = super().update(policy)
        write_json_array(self.path, self.rows())
        return updated
