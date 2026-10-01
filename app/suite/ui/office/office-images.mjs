import { officeFigureCaption, officeFigureFragment, officeFigureId } from "./office-figures.mjs";

const keys = ["documentId", "assetId", "versionId", "contentHash", "manifestHash", "pixelWidth", "pixelHeight",
  "width", "height", "align", "alt", "caption", "decorative", "lockAspect"];
export const officeImageKeys = [...keys, "crop", "wrap", "position", "transform", "figureId"];
export function officeImageWrap(wrap) {
  if (!wrap || Object.keys(wrap).length !== 2 || !["left", "right"].includes(wrap.side) ||
      !Number.isInteger(wrap.gap) || wrap.gap < 0 || wrap.gap > 48) throw new Error("image-wrap");
  return { side: wrap.side, gap: wrap.gap };
}
export function officeImagePosition(position) {
  if (!position || Object.keys(position).length !== 3 || !["front", "behind"].includes(position.layer) ||
      !Number.isInteger(position.x) || position.x < 0 || position.x > 1000 ||
      !Number.isInteger(position.y) || position.y < -1200 || position.y > 1200) throw new Error("image-position");
  return { layer: position.layer, x: position.x, y: position.y };
}
export function officeImageTransform(transform) {
  if (!transform || Object.keys(transform).length !== 3 || ![0, 90, 180, 270].includes(transform.rotation) ||
      typeof transform.flipX !== "boolean" || typeof transform.flipY !== "boolean" ||
      (transform.rotation === 0 && !transform.flipX && !transform.flipY)) throw new Error("image-transform");
  return { rotation: transform.rotation, flipX: transform.flipX, flipY: transform.flipY };
}
export function applyOfficeImageLayout(element, attrs) {
  if (attrs.wrap != null && attrs.position != null) throw new Error("image-layout-conflict");
  if (attrs.wrap != null) {
    const wrap = officeImageWrap(attrs.wrap);
    element.setAttribute("data-image-wrap", wrap.side);
    element.style.setProperty("--image-wrap-gap", `${wrap.gap}px`);
    element.style.setProperty("--image-wrap-width", `${Math.min(attrs.width, 480 * attrs.width / attrs.height)}px`);
  } else {
    element.removeAttribute("data-image-wrap");
    element.style.removeProperty("--image-wrap-gap"); element.style.removeProperty("--image-wrap-width");
  }
  if (attrs.position != null) {
    const position = officeImagePosition(attrs.position);
    element.setAttribute("data-image-position", position.layer);
    element.style.setProperty("--image-position-x", `${position.x / 10}%`);
    element.style.setProperty("--image-position-shift", `${-position.x / 10}%`);
    element.style.setProperty("--image-position-y", `${position.y}px`);
    element.style.setProperty("--image-position-width", `${attrs.width}px`);
  } else {
    element.removeAttribute("data-image-position");
    for (const name of ["--image-position-x", "--image-position-shift", "--image-position-y", "--image-position-width"]) element.style.removeProperty(name);
  }
}
export function officeImageCrop(attrs) {
  const crop = attrs.crop ?? { x: 0, y: 0, width: attrs.pixelWidth, height: attrs.pixelHeight };
  if (!crop || Object.keys(crop).length !== 4 || ["x", "y", "width", "height"].some((key) => !Number.isInteger(crop[key])) ||
      crop.x < 0 || crop.y < 0 || crop.width < 1 || crop.height < 1 ||
      crop.x + crop.width > attrs.pixelWidth || crop.y + crop.height > attrs.pixelHeight) throw new Error("image-crop");
  return { x: crop.x, y: crop.y, width: crop.width, height: crop.height };
}
export class OfficeImageReadError extends Error {
  constructor(status) { super("Image unavailable"); this.status = status; }
}

export function officeImageAttributes(attrs) {
  if (!attrs || Object.keys(attrs).some((key) => !officeImageKeys.includes(key)) || keys.some((key) => !Object.hasOwn(attrs, key))) throw new Error("image-attributes");
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
  const result = Object.fromEntries(keys.map((key) => [key, attrs[key]]));
  if (attrs.crop != null) result.crop = officeImageCrop(attrs);
  if (attrs.wrap != null) result.wrap = officeImageWrap(attrs.wrap);
  if (attrs.position != null) result.position = officeImagePosition(attrs.position);
  if (attrs.transform != null) result.transform = officeImageTransform(attrs.transform);
  if (result.wrap != null && result.position != null) throw new Error("image-layout-conflict");
  if (attrs.figureId != null) {
    result.figureId = officeFigureId(attrs.figureId);
    if (!attrs.caption.trim()) throw new Error("image-figure-caption");
  }
  return result;
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

export function officeImageFigure(attrs, url, dom = document, figureNumber = null) {
  attrs = officeImageAttributes(attrs);
  if (typeof url !== "string" || !url.startsWith("blob:")) throw new Error("image-url");
  const figure = dom.createElement("figure"); figure.className = "office-image";
  figure.setAttribute("data-image-align", attrs.align);
  applyOfficeImageLayout(figure, attrs);
  const image = dom.createElement("img"); image.src = url; image.alt = attrs.decorative ? "" : attrs.alt;
  image.width = attrs.width; image.height = attrs.height;
  image.style.width = `${attrs.width}px`; image.style.aspectRatio = `${attrs.width} / ${attrs.height}`;
  image.draggable = false;
  let visual = image;
  if (attrs.crop) {
    const crop = officeImageCrop(attrs);
    const viewport = dom.createElement("span"); viewport.className = "office-image-viewport";
    viewport.style.width = `${attrs.width}px`; viewport.style.aspectRatio = `${attrs.width} / ${attrs.height}`;
    image.style.width = `${100 * attrs.pixelWidth / crop.width}%`;
    image.style.height = `${100 * attrs.pixelHeight / crop.height}%`;
    image.style.left = `${-100 * crop.x / crop.width}%`; image.style.top = `${-100 * crop.y / crop.height}%`;
    viewport.append(image); visual = viewport;
  }
  if (attrs.transform) {
    const transform = officeImageTransform(attrs.transform);
    const sideways = transform.rotation % 180 !== 0;
    const frameWidth = sideways ? attrs.height : attrs.width, frameHeight = sideways ? attrs.width : attrs.height;
    const frame = dom.createElement("span"); frame.className = "office-image-transform";
    frame.style.width = `${frameWidth}px`; frame.style.aspectRatio = `${frameWidth} / ${frameHeight}`;
    frame.dataset.imageRotation = String(transform.rotation);
    frame.dataset.imageFlipX = String(transform.flipX); frame.dataset.imageFlipY = String(transform.flipY);
    const stage = dom.createElement("span"); stage.className = "office-image-transform-stage";
    stage.style.width = `${100 * attrs.width / frameWidth}%`; stage.style.height = `${100 * attrs.height / frameHeight}%`;
    stage.style.transform = `translate(-50%, -50%) rotate(${transform.rotation}deg) scale(${transform.flipX ? -1 : 1}, ${transform.flipY ? -1 : 1})`;
    visual.style.width = "100%"; visual.style.height = "100%"; visual.style.aspectRatio = `${attrs.width} / ${attrs.height}`;
    stage.append(visual); frame.append(stage); figure.append(frame);
  } else figure.append(visual);
  if (attrs.caption) {
    const caption = dom.createElement("figcaption"); caption.textContent = officeFigureCaption(attrs, figureNumber); figure.append(caption);
  }
  if (attrs.figureId != null) { figure.id = officeFigureFragment(attrs.figureId); figure.dataset.officeFigure = attrs.figureId; }
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
