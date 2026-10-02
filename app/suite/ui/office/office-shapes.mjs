export const OFFICE_SHAPE_LIMIT = 100;
export const OFFICE_SHAPE_KINDS = ["rectangle", "roundedRectangle", "ellipse"];
export const OFFICE_SHAPE_COLORS = ["transparent", "white", "slate", "red", "orange", "yellow", "green", "teal", "blue", "purple", "black"];
export const OFFICE_SHAPE_TEXT_ALIGNMENTS = ["left", "center", "right"];

export function officeShapeWrap(wrap) {
  if (!wrap || Object.keys(wrap).length !== 2 || !["left", "right"].includes(wrap.side) ||
      !Number.isInteger(wrap.gap) || wrap.gap < 0 || wrap.gap > 48) throw new Error("shape-wrap");
  return { side: wrap.side, gap: wrap.gap };
}

export function officeShapePosition(position) {
  if (!position || Object.keys(position).length !== 3 || !["front", "behind"].includes(position.layer) ||
      !Number.isInteger(position.x) || position.x < 0 || position.x > 1000 ||
      !Number.isInteger(position.y) || position.y < -1200 || position.y > 1200) throw new Error("shape-position");
  return { layer: position.layer, x: position.x, y: position.y };
}

export function officeShapeAttributes(attrs) {
  const keys = ["fill", "height", "id", "kind", "stroke", "strokeWidth", "text", "textAlign", "width"];
  const actualKeys = Object.keys(attrs || {}).filter((key) => !["position", "rotation", "wrap"].includes(key)).sort();
  if (!attrs || actualKeys.join(",") !== keys.join(",") ||
      (Object.hasOwn(attrs, "position") && attrs.position !== null && typeof attrs.position !== "object") ||
      (Object.hasOwn(attrs, "rotation") && attrs.rotation !== null && ![90, 180, 270].includes(attrs.rotation)) ||
      (Object.hasOwn(attrs, "wrap") && attrs.wrap !== null && typeof attrs.wrap !== "object") ||
      !/^shape-[a-f0-9]{24}$/.test(attrs.id) || !OFFICE_SHAPE_KINDS.includes(attrs.kind) ||
      !Number.isInteger(attrs.width) || attrs.width < 80 || attrs.width > 1200 ||
      !Number.isInteger(attrs.height) || attrs.height < 40 || attrs.height > 800 ||
      !OFFICE_SHAPE_COLORS.includes(attrs.fill) || !OFFICE_SHAPE_COLORS.includes(attrs.stroke) ||
      !Number.isInteger(attrs.strokeWidth) || attrs.strokeWidth < 0 || attrs.strokeWidth > 8 ||
      typeof attrs.text !== "string" || attrs.text.length > 1000 ||
      [...attrs.text].some((character) => (character.codePointAt(0) < 32 && character !== "\n" && character !== "\t") ||
        (character.codePointAt(0) >= 127 && character.codePointAt(0) <= 159) ||
        (character.codePointAt(0) >= 0xd800 && character.codePointAt(0) <= 0xdfff) || ["\u2028", "\u2029"].includes(character)) ||
      !OFFICE_SHAPE_TEXT_ALIGNMENTS.includes(attrs.textAlign)) throw new Error("shape-attributes");
  const result = { id: attrs.id, kind: attrs.kind, width: attrs.width, height: attrs.height, fill: attrs.fill,
    stroke: attrs.stroke, strokeWidth: attrs.strokeWidth, text: attrs.text, textAlign: attrs.textAlign };
  if (attrs.rotation != null) result.rotation = attrs.rotation;
  if (attrs.position != null) result.position = officeShapePosition(attrs.position);
  if (attrs.wrap != null) result.wrap = officeShapeWrap(attrs.wrap);
  if (result.position != null && result.wrap != null) throw new Error("shape-layout-conflict");
  return result;
}

export function officeShapeDescription(attrs) {
  const shape = officeShapeAttributes(attrs);
  const kind = { rectangle: "Rechteck", roundedRectangle: "Abgerundetes Rechteck", ellipse: "Ellipse" }[shape.kind];
  const rotation = shape.rotation ? ` · ${shape.rotation}° gedreht` : "";
  const position = shape.position ? ` · ${shape.position.layer === "front" ? "vor" : "hinter"} Text · X ${shape.position.x} · Y ${shape.position.y} px` : "";
  const wrap = shape.wrap ? ` · Textumfluss ${shape.wrap.side === "left" ? "Form links" : "Form rechts"} · Abstand ${shape.wrap.gap} px` : "";
  return `${kind} · ${shape.width} × ${shape.height} px${rotation}${position}${wrap}${shape.text ? ` · ${shape.text}` : ""}`;
}

export function applyOfficeShapeDOM(element, attrs) {
  const shape = officeShapeAttributes(attrs);
  element.className = "office-shape";
  element.dataset.officeShape = shape.id;
  element.dataset.shapeKind = shape.kind;
  element.dataset.shapeFill = shape.fill;
  element.dataset.shapeStroke = shape.stroke;
  element.dataset.shapeTextAlign = shape.textAlign;
  if (shape.rotation) element.dataset.shapeRotation = String(shape.rotation); else delete element.dataset.shapeRotation;
  if (shape.wrap) {
    element.dataset.shapeWrap = shape.wrap.side;
    element.style.setProperty("--office-shape-wrap-gap", `${shape.wrap.gap}px`);
    const sideways = [90, 270].includes(shape.rotation), width = sideways ? shape.height : shape.width, height = sideways ? shape.width : shape.height;
    element.style.setProperty("--office-shape-wrap-width", `${Math.min(width, 480 * width / height)}px`);
  } else {
    delete element.dataset.shapeWrap;
    element.style.removeProperty("--office-shape-wrap-gap"); element.style.removeProperty("--office-shape-wrap-width");
  }
  if (shape.position) {
    element.dataset.shapePosition = shape.position.layer;
    element.style.setProperty("--office-shape-position-x", `${shape.position.x / 10}%`);
    element.style.setProperty("--office-shape-position-shift", `${-shape.position.x / 10}%`);
    element.style.setProperty("--office-shape-position-y", `${shape.position.y}px`);
  } else {
    delete element.dataset.shapePosition;
    for (const name of ["--office-shape-position-x", "--office-shape-position-shift", "--office-shape-position-y"]) element.style.removeProperty(name);
  }
  element.style.setProperty("--office-shape-width", String(shape.width));
  element.style.setProperty("--office-shape-height", String(shape.height));
  element.style.setProperty("--office-shape-rotation", `${shape.rotation || 0}deg`);
  element.style.setProperty("--office-shape-stroke", `${shape.strokeWidth}px`);
  element.setAttribute("contenteditable", "false");
  element.setAttribute("role", "img");
  element.setAttribute("aria-label", officeShapeDescription(shape));
  element.textContent = shape.text;
  return element;
}

export function officeShapeElement(attrs, dom = document) {
  return applyOfficeShapeDOM(dom.createElement("div"), attrs);
}
