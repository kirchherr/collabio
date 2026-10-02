export const OFFICE_SHAPE_LIMIT = 100;
export const OFFICE_SHAPE_KINDS = ["rectangle", "roundedRectangle", "ellipse"];
export const OFFICE_SHAPE_COLORS = ["transparent", "white", "slate", "red", "orange", "yellow", "green", "teal", "blue", "purple", "black"];
export const OFFICE_SHAPE_TEXT_ALIGNMENTS = ["left", "center", "right"];

export function officeShapePosition(position) {
  if (!position || Object.keys(position).length !== 3 || !["front", "behind"].includes(position.layer) ||
      !Number.isInteger(position.x) || position.x < 0 || position.x > 1000 ||
      !Number.isInteger(position.y) || position.y < -1200 || position.y > 1200) throw new Error("shape-position");
  return { layer: position.layer, x: position.x, y: position.y };
}

export function officeShapeAttributes(attrs) {
  const keys = ["fill", "height", "id", "kind", "stroke", "strokeWidth", "text", "textAlign", "width"];
  const actualKeys = Object.keys(attrs || {}).filter((key) => key !== "position").sort();
  if (!attrs || actualKeys.join(",") !== keys.join(",") ||
      (Object.hasOwn(attrs, "position") && attrs.position !== null && typeof attrs.position !== "object") ||
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
  if (attrs.position != null) result.position = officeShapePosition(attrs.position);
  return result;
}

export function officeShapeDescription(attrs) {
  const shape = officeShapeAttributes(attrs);
  const kind = { rectangle: "Rechteck", roundedRectangle: "Abgerundetes Rechteck", ellipse: "Ellipse" }[shape.kind];
  const position = shape.position ? ` · ${shape.position.layer === "front" ? "vor" : "hinter"} Text · X ${shape.position.x} · Y ${shape.position.y} px` : "";
  return `${kind} · ${shape.width} × ${shape.height} px${position}${shape.text ? ` · ${shape.text}` : ""}`;
}

export function applyOfficeShapeDOM(element, attrs) {
  const shape = officeShapeAttributes(attrs);
  element.className = "office-shape";
  element.dataset.officeShape = shape.id;
  element.dataset.shapeKind = shape.kind;
  element.dataset.shapeFill = shape.fill;
  element.dataset.shapeStroke = shape.stroke;
  element.dataset.shapeTextAlign = shape.textAlign;
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
