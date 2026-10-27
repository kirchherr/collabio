# ADR-0071: GenOffice DOCX Quick-Edit Preflight Boundary

- Status: Accepted
- Date: 2026-08-13
- Scope: Office Quick Edit evaluation only
- Supersedes: none
- Extends: ADR-0061, ADR-0069, ADR-0070

## Context

The admitted GenOffice development image is intentionally status-only. ADR-0070 requires a real two-person runtime
authorization before an executable proof harness may be built or invoked. The current solo-founder exception cannot
replace that control. Waiting for the second accountable person must not, however, postpone the engine-independent
security contract that every future DOCX input and candidate output must pass.

OOXML is an Open Packaging Conventions ZIP package rather than one XML file. The package can contain external
relationships, active content, embedded objects, ambiguous part names, highly compressed entries, hostile XML and
package signatures. A server-side Office engine therefore needs a bounded package admission layer before invocation
and a separately mounted, source-blind candidate revalidator afterwards.

The selected GenOffice `docx-engine` remains pinned to commit
`fd33934dab1fdf8666af3f88b9794e7b4e19474a`. Upstream's byte-preserving paragraph patching is useful for fidelity,
but its Electron security model does not constitute Collabio's server-worker isolation or content admission policy.

## Decision

Collabio introduces `genoffice_docx_quick_edit_preflight_policy.v1` as an engine-independent, fail-closed boundary.
It performs no filesystem extraction and inspects only bounded ZIP central-directory metadata and bounded XML bytes.
The fixed policy limits archive size, part count, declared and per-part expansion, compression ratio, XML size/depth,
relationship count and compression methods.

The preflight rejects before engine invocation when it observes:

- unsafe, duplicate or case-colliding package part names;
- encrypted or unsupported ZIP entries, excessive expansion or resource limits;
- malformed XML, DTD/entity declarations or excessive XML nesting;
- any external relationship, including attached templates;
- VBA, macro-enabled content, ActiveX, OLE or embedded package markers;
- package signatures until an authoritative signature validator exists.

Package-signature presence is not treated as proof of signer identity or integrity. The original bytes must be retained
under the future SourceObject retention policy. Any edited derivative must carry `invalidated_by_edit`; it may not
inherit the original signature state. Microsoft OPC documentation confirms that package signatures protect selected
signed parts while trust in signer identity remains a consumer decision.

The deterministic synthetic corpus contains 19 fixtures: three bounded fidelity fixtures and 16 negative fixtures for
external relationships, templates, VBA, OLE, path traversal, duplicate/case-colliding parts, compression bombs,
hostile XML, package signatures, encrypted flags, unsupported compression, declared oversize and excessive part count.
The corpus evaluation reports hashes, counters and finding codes only.

Safe export and high-fidelity export are separate future modes. Both prohibit active and external content, require
source-blind candidate revalidation and require the existing independent CDR preview. Safe export removes invalidated
package signatures. High-fidelity export may preserve only safe unknown parts and additionally requires explicit human
confirmation. No fidelity claim is allowed until Microsoft Word, LibreOffice, GenOffice and the Collabio revalidator
have produced a recorded comparison matrix.

The source-blind revalidator receives only candidate bytes and their expected transport hash. It has no source-object
mount, source bytes, tenant credentials, network or persistence. The current proof uses one clean synthetic fixture to
verify the independent validator contract; it does not present those bytes as engine output.

`genoffice_docx_quick_edit_harness_admission_report.v1` remains hard closed. It records the verified corpus and
revalidator while explicitly denying execution because real two-person runtime authorization and a newly built,
attested executable proof-harness image are absent and the existing worker entrypoint is status-only.

## Consequences

- Security and export rules can be tested now without weakening ADR-0070.
- The same preflight can later guard both the input side and the source-blind output side of the engine sandbox.
- Synthetic corpus bytes and all metadata-only reports become critical Office recovery evidence.
- The full DOCX Quick-Edit spike remains incomplete until the real two-person ceremony, executable attested harness,
  no-egress runsc execution, cross-engine fidelity matrix and CDR-linked output evidence exist.
- No tenant document, candidate version, draft, saved version, business record or WORM record is created by this ADR.

## References

- [GenOffice repository](https://github.com/genspark-ai/genoffice)
- [Pinned GenOffice source](https://github.com/genspark-ai/genoffice/commit/fd33934dab1fdf8666af3f88b9794e7b4e19474a)
- [GenOffice security policy](https://github.com/genspark-ai/genoffice/blob/main/SECURITY.md)
- [Microsoft Open Packaging Conventions overview](https://learn.microsoft.com/en-us/previous-versions/windows/desktop/opc/open-packaging-conventions-overview)
- [Microsoft package relationship API and external targets](https://learn.microsoft.com/en-us/dotnet/api/system.io.packaging.package.createrelationship?view=windowsdesktop-9.0)
