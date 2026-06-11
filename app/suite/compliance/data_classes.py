from __future__ import annotations

from dataclasses import dataclass

from suite.ai_control_plane.models import DataClass


@dataclass(frozen=True)
class DataClassDefinition:
    data_class: DataClass
    display_name: str
    description: str
    sensitivity_rank: int
    retention_required: bool
    kms_required: bool
    audit_required: bool
    legal_hold_allowed: bool
    cryptoshred_allowed_by_default: bool
    source_indexable: bool
    legacy_aliases: tuple[str, ...] = ()


DATA_CLASS_DEFINITIONS: tuple[DataClassDefinition, ...] = (
    DataClassDefinition(
        data_class=DataClass.PUBLIC,
        display_name="Public",
        description="Published or intentionally public content.",
        sensitivity_rank=10,
        retention_required=True,
        kms_required=True,
        audit_required=False,
        legal_hold_allowed=False,
        cryptoshred_allowed_by_default=False,
        source_indexable=True,
        legacy_aliases=("temporary",),
    ),
    DataClassDefinition(
        data_class=DataClass.INTERNAL,
        display_name="Internal",
        description="Normal collaborative working data and non-public internal records.",
        sensitivity_rank=20,
        retention_required=True,
        kms_required=True,
        audit_required=True,
        legal_hold_allowed=True,
        cryptoshred_allowed_by_default=True,
        source_indexable=True,
        legacy_aliases=("working_data", "model_config", "ai_evaluation"),
    ),
    DataClassDefinition(
        data_class=DataClass.PERSONAL,
        display_name="Personal",
        description="Personal data governed by privacy rights and retention policy.",
        sensitivity_rank=30,
        retention_required=True,
        kms_required=True,
        audit_required=True,
        legal_hold_allowed=True,
        cryptoshred_allowed_by_default=True,
        source_indexable=True,
        legacy_aliases=("personal_data",),
    ),
    DataClassDefinition(
        data_class=DataClass.CONFIDENTIAL,
        display_name="Confidential",
        description="Sensitive business, security, export, retrieval trace, and privileged evidence data.",
        sensitivity_rank=40,
        retention_required=True,
        kms_required=True,
        audit_required=True,
        legal_hold_allowed=True,
        cryptoshred_allowed_by_default=True,
        source_indexable=True,
        legacy_aliases=("security_data", "export_package", "retrieval_trace", "tool_call"),
    ),
    DataClassDefinition(
        data_class=DataClass.GOBD,
        display_name="GoBD",
        description="German tax- and accounting-relevant business records.",
        sensitivity_rank=50,
        retention_required=True,
        kms_required=True,
        audit_required=True,
        legal_hold_allowed=True,
        cryptoshred_allowed_by_default=False,
        source_indexable=True,
        legacy_aliases=("gobd_record",),
    ),
    DataClassDefinition(
        data_class=DataClass.LEGAL_HOLD,
        display_name="Legal Hold",
        description="Records preserved for legal, audit, regulatory, or investigation matters.",
        sensitivity_rank=60,
        retention_required=True,
        kms_required=True,
        audit_required=True,
        legal_hold_allowed=True,
        cryptoshred_allowed_by_default=False,
        source_indexable=True,
    ),
    DataClassDefinition(
        data_class=DataClass.AI_PROMPT,
        display_name="AI Prompt",
        description="User instructions and prompt context sent to the Local LLM Gateway.",
        sensitivity_rank=40,
        retention_required=True,
        kms_required=True,
        audit_required=True,
        legal_hold_allowed=True,
        cryptoshred_allowed_by_default=True,
        source_indexable=False,
    ),
    DataClassDefinition(
        data_class=DataClass.AI_OUTPUT,
        display_name="AI Output",
        description="Generated text, labels, drafts, and classifications until validated by policy or a user.",
        sensitivity_rank=40,
        retention_required=True,
        kms_required=True,
        audit_required=True,
        legal_hold_allowed=True,
        cryptoshred_allowed_by_default=True,
        source_indexable=False,
    ),
    DataClassDefinition(
        data_class=DataClass.RAG_CHUNK,
        display_name="RAG Chunk",
        description="Extracted source chunk metadata and text prepared for authorized retrieval.",
        sensitivity_rank=40,
        retention_required=True,
        kms_required=True,
        audit_required=True,
        legal_hold_allowed=True,
        cryptoshred_allowed_by_default=False,
        source_indexable=False,
    ),
    DataClassDefinition(
        data_class=DataClass.EMBEDDING,
        display_name="Embedding",
        description="Vector representation of source-derived content. Not anonymous by default.",
        sensitivity_rank=40,
        retention_required=True,
        kms_required=True,
        audit_required=True,
        legal_hold_allowed=True,
        cryptoshred_allowed_by_default=False,
        source_indexable=False,
    ),
    DataClassDefinition(
        data_class=DataClass.VOICE_TRANSCRIPT,
        display_name="Voice Transcript",
        description="Transcribed voice input. Raw audio remains forbidden unless a tenant policy explicitly allows it.",
        sensitivity_rank=40,
        retention_required=True,
        kms_required=True,
        audit_required=True,
        legal_hold_allowed=True,
        cryptoshred_allowed_by_default=True,
        source_indexable=False,
        legacy_aliases=("voice_audio",),
    ),
)


def data_class_definitions() -> tuple[DataClassDefinition, ...]:
    return DATA_CLASS_DEFINITIONS


def canonical_data_classes() -> frozenset[DataClass]:
    return frozenset(definition.data_class for definition in DATA_CLASS_DEFINITIONS)


def canonical_data_class_values() -> frozenset[str]:
    return frozenset(data_class.value for data_class in canonical_data_classes())


def source_indexable_data_classes() -> frozenset[DataClass]:
    return frozenset(definition.data_class for definition in DATA_CLASS_DEFINITIONS if definition.source_indexable)


def legacy_data_class_aliases() -> dict[str, DataClass]:
    aliases: dict[str, DataClass] = {}
    for definition in DATA_CLASS_DEFINITIONS:
        for alias in definition.legacy_aliases:
            if alias in aliases:
                raise ValueError(f"duplicate data class alias: {alias}")
            aliases[alias] = definition.data_class
    return aliases


def resolve_data_class(value: str, *, allow_legacy_alias: bool = False) -> DataClass:
    try:
        return DataClass(value)
    except ValueError as exc:
        if allow_legacy_alias:
            alias = legacy_data_class_aliases().get(value)
            if alias is not None:
                return alias
        raise ValueError(f"unknown data class: {value}") from exc
