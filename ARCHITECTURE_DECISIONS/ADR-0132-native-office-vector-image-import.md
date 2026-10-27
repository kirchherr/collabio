# ADR-0132: Native Office SVG and EPS image import

Status: Accepted
Date: 2026-10-06

## Context

Native Office accepted document-owned PNG and JPEG images, normalized them in a credential-free decoder and stored
only a canonical RGBA PNG. Authors also need common vector artwork without introducing active SVG, PostScript or
external-resource behavior into saved documents. SVG can contain scripts, event handlers, XML entities, stylesheets
and network references. EPS is executable PostScript and has no native partial-alpha model.

## Decision

Accept bounded SVG and EPS uploads through the existing tenant- and write-authorized image endpoint. Keep original
vector bytes transient and store only the canonical metadata-free RGBA PNG rendition. SVG dimensions support bounded
pixel and physical units or a view box. SVG input is rejected before rendering when it contains document types,
entities, XML stylesheets, active or embedded elements, event attributes, external references, CSS imports or
non-fragment CSS URLs.

EPS input must declare EPSF and a finite numeric bounding box; generic PostScript is rejected. Render only the first
page with Ghostscript `SAFER` and a transparent canvas. EPS-painted areas remain opaque because EPS has no partial
alpha semantics; unpainted canvas remains transparent. SVG is rendered with CairoSVG and retains source alpha.

Both renderers run only inside the existing non-root, read-only, credential-free, network-none image decoder. Every
request gets a fresh child with CPU, address-space, output-size and timeout limits. Input remains limited to 8 MiB,
4096 pixels per axis and four million output pixels. The decoder image pins its Alpine Ghostscript and CairoSVG
packages. Browser selection accepts SVG and `.eps`, including extension fallback when a browser omits the EPS media
type.

## Consequences

Authors can insert and replace SVG and EPS artwork through the existing accessible image dialog, while save, history,
comparison, print, grouping, transforms, ACL enforcement and immutable asset ownership continue to operate on the
same inert PNG contract. Stored versions never contain executable vector input or an external-resource dependency.
EPS files that paint a white background retain that opaque background, and unsupported active or ambiguous vectors
fail closed.
