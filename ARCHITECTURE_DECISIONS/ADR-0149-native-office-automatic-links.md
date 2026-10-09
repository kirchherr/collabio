# ADR-0149: Safe native Office automatic link recognition

Date: 2026-10-08
Status: accepted; development validation, isolated review deployment and publication complete; ordinary tenant and production admission remain closed

Native Office recognizes complete HTTPS addresses, explicit `mailto:` targets and simple email addresses while an
authorized editor types or pastes plain text. Recognition reuses the existing canonical link mark and its strict
validator. It never introduces a second stored link format, fetches a target, resolves metadata, opens a browser
window or sends a request to the detected address.

The detector scans bounded whitespace-delimited tokens, preserves every literal character and excludes surrounding
sentence punctuation plus unmatched closing brackets. Balanced brackets remain part of an HTTPS address. Only a
candidate accepted by `officeLinkHref` receives a mark; HTTP, credentials, active or local schemes, prepared mail
messages, malformed domains, control characters and overlong values remain inert text.

Typing applies a link only after a delimiter completes the token. Plain-text paste may recognize several links in one
operation and remains a single isolated undo step. Code, existing links and document or cross-reference marks are not
rewritten. Loading a legacy document does not scan or mutate it, and undo/redo, confirmed CAS save, immutable history,
comparison, search/replacement, reuse and print continue to use the established link lifecycle.

Rendering still emits fixed safe anchor attributes with `noopener noreferrer`; print omits the interactive target
behavior. The application never navigates automatically. Deliberate opening remains available only through the
existing explicit link dialog action.

No SQL migration, API endpoint, external provider, URL preview, network lookup, background worker, new recovery store,
DOCX engine or ordinary tenant admission is introduced. Existing tenant, ACL, classification, canonical-size, audit,
version and recovery boundaries remain authoritative. The existing exact HTTPS/mail/reset recovery lineage proves the
canonical stored result because automatically and manually created links are intentionally indistinguishable.

Acceptance requires pure candidate/content model tests and responsive desktop/mobile browser evidence for typing,
multi-link paste, punctuation, unsafe inert text, isolated undo/redo, confirmed save, immutable predecessor, reload,
semantic print/PDF output and zero target requests.
