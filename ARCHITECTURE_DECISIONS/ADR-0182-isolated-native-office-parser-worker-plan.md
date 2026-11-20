# ADR-0182: Isolated native Office parser-worker plan

Date: 2026-10-10

Status: Accepted

## Context

Native Office already has a bounded development parser for PDF, ODT and DOCX. It rejects unsupported formats,
external processes and network access, and applies input, archive and extracted-text limits. The roadmap now needs a
clear tenant-facing architecture boundary before any scheduler can dispatch untrusted documents to that worker.

The repository does not yet contain a content-addressed input materializer, a write-only result handoff, job timeout
enforcement, a verified malicious-document corpus, sandbox-escape fuzzing, a nonempty parser recovery proof or an
admitted production worker image. Treating the development manifest as a production service would bypass those
controls.

## Decision

Expose `office_parser_worker_plan.v1` as a read-gated, tenant-scoped and metadata-only plan. The endpoint accepts no
content, object ID or version ID. It returns supported MIME types, source prerequisites, ordered pipeline steps,
isolation requirements, exact resource limits and blockers. Dispatch and production admission are always false.

Any future parsing request must first authorize the caller against the authoritative tenant and source object, bind
the exact immutable source version and manifest hash, carry classification, retention, legal-hold and ACL versions,
and present a malware and active-content decision. Exact bytes are then materialized into a content-addressed input,
parsed once without network access, validated against a bounded result schema and hashes, reauthorized before use and
removed from scratch storage.

Harden the existing `rich-document-parser` Compose service with `network_mode: none`, read-only root filesystem,
UID/GID 1000, all Linux capabilities dropped, `no-new-privileges` and a 64 MiB `noexec,nosuid,nodev` tmpfs. Give it
no database, object-storage or provider credential and no direct storage or vector-write path. Limit it to 256 MiB
memory, 64 processes and one CPU. Retain the parser's 25 MB input, 20 MB expanded-archive and two-million-character
output limits.

Treat every parser result as untrusted until independent schema and hash validation. Normal logs may contain no
content. Audit only the tenant-bound plan version, bounded counts, closed states and blocker count; do not audit file
content, source identifiers or versions through this endpoint.

## Consequences

The browser can explain the intended import isolation and exact missing evidence without uploading or dispatching a
document. A real transient container probe verifies the effective no-network, non-root, read-only, capability,
privilege, memory, process, CPU and tmpfs controls.

Production work must separately implement and verify the content-addressed materializer, write-only result handoff,
scheduler and wall-clock timeout, malicious corpus, sandbox-escape fuzzing, nonempty recovery and image admission.
This plan grants none of them and must not be interpreted as a parser runtime or import-completion claim.
