const keys = ["documentId", "assetId", "versionId", "contentHash", "manifestHash", "pixelWidth", "pixelHeight",
  "width", "height", "align", "alt", "caption", "decorative", "lockAspect"];
export const officeImageKeys = keys;
export class OfficeImageReadError extends Error {
  constructor(status) { super("Image unavailable"); this.status = status; }
}

export function officeImageAttributes(attrs) {
  if (!attrs || Object.keys(attrs).length !== keys.length || keys.some((key) => !Object.hasOwn(attrs, key))) throw new Error("image-attributes");
  for (const [key, prefix] of [["documentId", "office-doc-"], ["assetId", "office-image-"], ["versionId", "office-image-version-"]]) {
    if (typeof attrs[key] !== "string" || !new RegExp(`^${prefix}[a-f0-9]{32}$`).test(attrs[key])) throw new Error("image-id");
  }
  for (const key of ["contentHash", "manifestHash"]) if (!/^sha256:[a-f0-9]{64}$/.test(attrs[key])) throw new Error("image-hash");
  for (const [key, max] of [["pixelWidth", 4096], ["pixelHeight", 4096], ["width", 1600], ["height", 1600]]) {
    if (!Number.isInteger(attrs[key]) || attrs[key] < 1 || attrs[key] > max) throw new Error("image-size");
  }
  if (attrs.pixelWidth * attrs.pixelHeight > 4000000 || !["left", "center", "right"].includes(attrs.align) ||
      typeof attrs.decorative !== "boolean" || typeof attrs.lockAspect !== "boolean") throw new Error("image-options");
  for (const [key, max] of [["alt", 500], ["caption", 1000]]) {
    if (typeof attrs[key] !== "string" || Array.from(attrs[key]).length > max || /[\x00-\x1f\x7f-\x9f\uD800-\uDFFF]/u.test(attrs[key])) throw new Error("image-text");
  }
  if ((attrs.decorative && attrs.alt) || (!attrs.decorative && !attrs.alt.trim())) throw new Error("image-alt");
  return Object.fromEntries(keys.map((key) => [key, attrs[key]]));
}

export function officeImageReferences(content) {
  const result = [];
  const visit = (node) => {
    if (node.type === "image") result.push(officeImageAttributes(node.attrs));
    for (const child of node.content || []) visit(child);
  };
  visit(content);
  if (result.length > 40) throw new Error("image-count");
  return result;
}

export function officeImageFigure(attrs, url, dom = document) {
  attrs = officeImageAttributes(attrs);
  if (typeof url !== "string" || !url.startsWith("blob:")) throw new Error("image-url");
  const figure = dom.createElement("figure"); figure.className = "office-image";
  figure.setAttribute("data-image-align", attrs.align);
  const image = dom.createElement("img"); image.src = url; image.alt = attrs.decorative ? "" : attrs.alt;
  image.width = attrs.width; image.height = attrs.height;
  image.style.width = `${attrs.width}px`; image.style.aspectRatio = `${attrs.width} / ${attrs.height}`;
  image.draggable = false;
  figure.append(image);
  if (attrs.caption) {
    const caption = dom.createElement("figcaption"); caption.textContent = attrs.caption; figure.append(caption);
  }
  return figure;
}

export function officeImagePath(attrs) {
  return `/v1/office/documents/${encodeURIComponent(attrs.documentId)}/images/${encodeURIComponent(attrs.assetId)}/${encodeURIComponent(attrs.versionId)}`;
}

export async function fetchOfficeImage(attrs, context, signal) {
  const response = await fetch(officeImagePath(attrs), { cache: "no-store", signal, headers: {
    "X-Tenant-Id": context.tenantId, "X-User-Id": context.userId,
    "X-Role-Ids": context.roleIds, "X-Readable-Object-Ids": context.readableObjectIds,
  } });
  if (!response.ok) throw new OfficeImageReadError(response.status);
  if (response.headers.get("Content-Type") !== "image/png" ||
      response.headers.get("X-Office-Content-Hash") !== attrs.contentHash ||
      response.headers.get("X-Office-Manifest-Hash") !== attrs.manifestHash) throw new OfficeImageReadError(502);
  const blob = await response.blob();
  if (!blob.size || blob.size > 16065536) throw new Error("image-size");
  return URL.createObjectURL(blob);
}

export async function loadOfficePrintImages(content, context, signal) {
  const urls = new Map();
  try {
    for (const attrs of officeImageReferences(content)) {
      const key = officeImagePath(attrs);
      if (urls.has(key)) continue;
      const url = await fetchOfficeImage(attrs, context, signal);
      urls.set(key, url);
      const image = new Image(); image.src = url; await image.decode();
    }
    return urls;
  } catch (error) {
    for (const url of urls.values()) URL.revokeObjectURL(url);
    throw error;
  }
}
