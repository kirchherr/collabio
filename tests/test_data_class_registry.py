import json
import re
from pathlib import Path

from suite.ai_control_plane.models import DataClass
from suite.ai_control_plane.registries import InMemoryModelRegistry, InMemoryPromptRegistry
from suite.compliance.data_classes import (
    canonical_data_class_values,
    canonical_data_classes,
    data_class_definitions,
    legacy_data_class_aliases,
    resolve_data_class,
    source_indexable_data_classes,
)
from suite.kms.adapter import load_kms_adapter_policy
from suite.persistence.migration_catalog import get_migration
from suite.platform.tenant_policies import InMemoryTenantPolicyRepository
from suite.rag.source_indexing import DEFAULT_EMBEDDING_MODEL_DATA_CLASSES
from suite.storage.retention import load_retention_manifest_policy

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_CLASSIFICATION_PATH = REPO_ROOT / "DATA_CLASSIFICATION.md"
KMS_POLICY_PATH = REPO_ROOT / "docs" / "kms_adapter_policy.json"
RETENTION_MANIFEST_POLICY_PATH = REPO_ROOT / "docs" / "retention_manifest_policy.json"
RETENTION_POLICIES_PATH = REPO_ROOT / "RETENTION_POLICIES.yaml"


def test_canonical_data_class_registry_matches_runtime_enum_and_aliases_are_explicit() -> None:
    assert canonical_data_classes() == set(DataClass)
    assert {definition.data_class for definition in data_class_definitions()} == set(DataClass)
    assert len(data_class_definitions()) == len(DataClass)
    assert source_indexable_data_classes() == DEFAULT_EMBEDDING_MODEL_DATA_CLASSES

    aliases = legacy_data_class_aliases()
    assert aliases["personal_data"] == DataClass.PERSONAL
    assert aliases["gobd_record"] == DataClass.GOBD
    assert aliases["working_data"] == DataClass.INTERNAL
    assert resolve_data_class("personal") == DataClass.PERSONAL
    assert resolve_data_class("gobd_record", allow_legacy_alias=True) == DataClass.GOBD


def test_kms_retention_and_pgvector_constraints_use_only_canonical_data_classes() -> None:
    canonical_values = canonical_data_class_values()
    kms_policy = load_kms_adapter_policy(KMS_POLICY_PATH)
    retention_policy = load_retention_manifest_policy(RETENTION_MANIFEST_POLICY_PATH)

    assert {policy.data_class.value for policy in kms_policy.data_class_key_policies} == canonical_values
    assert {
        data_class.value for policy in retention_policy.policy_defaults for data_class in policy.classifications
    } == canonical_values
    assert _pgvector_classification_values() == canonical_values


def test_ai_prompt_model_tenant_and_embedding_registries_use_canonical_data_classes() -> None:
    canonical = canonical_data_classes()

    for row in InMemoryModelRegistry.default().rows():
        model_classes = {DataClass(value) for value in row["allowed_data_classes"]}
        assert model_classes <= canonical

    for row in InMemoryPromptRegistry.default().rows():
        prompt_classes = {DataClass(value) for value in row["allowed_data_classes"]}
        assert prompt_classes <= canonical

    for row in InMemoryTenantPolicyRepository.default().rows():
        tenant_classes = {DataClass(value) for value in row["allowed_data_classes"]}
        assert tenant_classes <= canonical

    assert canonical >= DEFAULT_EMBEDDING_MODEL_DATA_CLASSES


def test_policy_docs_use_canonical_active_data_classes() -> None:
    canonical_values = canonical_data_class_values()

    assert _retention_yaml_data_class_values() <= canonical_values
    assert _active_data_classification_table_values() == canonical_values

    with RETENTION_MANIFEST_POLICY_PATH.open(encoding="utf-8") as handle:
        retention_manifest = json.load(handle)
    manifest_values = {
        classification
        for policy in retention_manifest["policy_defaults"]
        for classification in policy["classifications"]
    }
    assert manifest_values == canonical_values


def _pgvector_classification_values() -> frozenset[str]:
    sql = get_migration("0001").sql()
    match = re.search(
        r"classification text not null check \(\s*classification in \((.*?)\)\s*\)",
        sql,
        flags=re.IGNORECASE | re.DOTALL,
    )
    assert match is not None
    return frozenset(re.findall(r"'([a-z0-9_]+)'", match.group(1)))


def _retention_yaml_data_class_values() -> frozenset[str]:
    values: set[str] = set()
    in_data_classes = False
    for line in RETENTION_POLICIES_PATH.read_text(encoding="utf-8").splitlines():
        if re.match(r"\s+data_classes:\s*$", line):
            in_data_classes = True
            continue
        if in_data_classes:
            item_match = re.match(r"\s+-\s+([a-z0-9_]+)\s*$", line)
            if item_match is not None:
                values.add(item_match.group(1))
                continue
            if line.strip() and not line.startswith(" " * 6):
                in_data_classes = False
    return frozenset(values)


def _active_data_classification_table_values() -> frozenset[str]:
    text = DATA_CLASSIFICATION_PATH.read_text(encoding="utf-8")
    active_section = text.split("## Canonical Runtime Data Classes", maxsplit=1)[1].split(
        "## Legacy Planning Terms",
        maxsplit=1,
    )[0]
    return frozenset(re.findall(r"\| `([a-z0-9_]+)` \|", active_section))
