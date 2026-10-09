import { OFFICE_SHAPE_GROUP_MEMBER_LIMIT, officeShapeGroupAttributes,
  officeShapeGroupBounds } from "./office-shape-groups.mjs";
import { OFFICE_SHAPE_COLORS, OFFICE_SHAPE_TEXT_ALIGNMENTS, OFFICE_SHAPE_TEXT_COLORS,
  OFFICE_SHAPE_TEXT_STYLES, officeShapeAttributes, officeShapeBounds,
  officeShapePosition } from "./office-shapes.mjs";

export const OFFICE_SHAPE_MULTI_SELECTION_LIMIT = 20;
export const OFFICE_SHAPE_MULTI_AXES = ["horizontal", "vertical"];
export const OFFICE_SHAPE_MULTI_ALIGNMENTS = ["start", "center", "end"];
export const OFFICE_SHAPE_MULTI_LAYERS = ["front", "behind"];
export const OFFICE_SHAPE_MULTI_NUDGE_AMOUNTS = [-10, -1, 1, 10];
export const OFFICE_SHAPE_MULTI_SCALE_BASE = 1000;

export function officeShapeMultiSelection(entries, ids) {
  if (!Array.isArray(entries) || !Array.isArray(ids) || ids.length > OFFICE_SHAPE_MULTI_SELECTION_LIMIT ||
      ids.some((id) => typeof id !== "string") || new Set(ids).size !== ids.length) throw new Error("shape-multi-selection");
  const wanted = new Set(ids);
  return entries.filter((entry) => wanted.has(entry.id) && ["shape", "shapeGroup"].includes(entry.type))
    .sort((left, right) => left.rootIndex - right.rootIndex);
}

export function officeShapeMultiRange(entries, anchorId, targetId) {
  const anchor = entries.findIndex((entry) => entry.id === anchorId), target = entries.findIndex((entry) => entry.id === targetId);
  if (anchor < 0 || target < 0) return [targetId];
  return entries.slice(Math.min(anchor, target), Math.max(anchor, target) + 1).map((entry) => entry.id);
}

export function officeShapeMultiCanGroup(entries) {
  return entries.length >= 2 && entries.length <= OFFICE_SHAPE_GROUP_MEMBER_LIMIT &&
    entries.every((entry) => entry.type === "shape" && entry.node?.attrs.position == null && entry.node?.attrs.wrap == null) &&
    entries.every((entry, index) => index === 0 || entry.rootIndex === entries[index - 1].rootIndex + 1);
}

export function officeShapeMultiCanArrange(entries, minimum = 2) {
  if (!Array.isArray(entries) || !Number.isInteger(minimum) || minimum < 2 || entries.length < minimum ||
      entries.length > OFFICE_SHAPE_MULTI_SELECTION_LIMIT) return false;
  return entries.every((entry) => {
    if (!["shape", "shapeGroup"].includes(entry?.type)) return false;
    try { officeShapePosition(entry.node?.attrs.position); return true; } catch { return false; }
  });
}

function arrangementCoordinate(axis) {
  if (!OFFICE_SHAPE_MULTI_AXES.includes(axis)) throw new Error("shape-multi-axis");
  return axis === "horizontal" ? "x" : "y";
}

export function officeShapeMultiAlignment(entries, axis, alignment) {
  if (!officeShapeMultiCanArrange(entries) || !OFFICE_SHAPE_MULTI_ALIGNMENTS.includes(alignment)) {
    throw new Error("shape-multi-alignment");
  }
  const coordinate = arrangementCoordinate(axis);
  const values = entries.map((entry) => entry.node.attrs.position[coordinate]);
  const first = Math.min(...values), last = Math.max(...values);
  const target = alignment === "start" ? first : alignment === "end" ? last : Math.round((first + last) / 2);
  return entries.map((entry) => ({ id: entry.id,
    position: officeShapePosition({ ...entry.node.attrs.position, [coordinate]: target }) }));
}

export function officeShapeMultiDistribution(entries, axis) {
  if (!officeShapeMultiCanArrange(entries, 3)) throw new Error("shape-multi-distribution");
  const coordinate = arrangementCoordinate(axis);
  const ordered = [...entries].sort((left, right) =>
    left.node.attrs.position[coordinate] - right.node.attrs.position[coordinate] ||
    left.rootIndex - right.rootIndex || left.id.localeCompare(right.id));
  const first = ordered[0].node.attrs.position[coordinate];
  const last = ordered.at(-1).node.attrs.position[coordinate];
  const positions = new Map(ordered.map((entry, index) => [entry.id,
    Math.round(first + (last - first) * index / (ordered.length - 1))]));
  return entries.map((entry) => ({ id: entry.id,
    position: officeShapePosition({ ...entry.node.attrs.position, [coordinate]: positions.get(entry.id) }) }));
}

export function officeShapeMultiLayer(entries, layer) {
  if (!officeShapeMultiCanArrange(entries) || !OFFICE_SHAPE_MULTI_LAYERS.includes(layer)) {
    throw new Error("shape-multi-layer");
  }
  return entries.map((entry) => ({ id: entry.id,
    position: officeShapePosition({ ...entry.node.attrs.position, layer }) }));
}

export function officeShapeMultiTranslate(entries, deltaX, deltaY) {
  if (!officeShapeMultiCanArrange(entries) || !Number.isSafeInteger(deltaX) || !Number.isSafeInteger(deltaY)) {
    throw new Error("shape-multi-translate");
  }
  const xs = entries.map((entry) => entry.node.attrs.position.x);
  const ys = entries.map((entry) => entry.node.attrs.position.y);
  const boundedX = Math.max(-Math.min(...xs), Math.min(deltaX, 1000 - Math.max(...xs)));
  const boundedY = Math.max(-1200 - Math.min(...ys), Math.min(deltaY, 1200 - Math.max(...ys)));
  return entries.map((entry) => ({ id: entry.id,
    position: officeShapePosition({ ...entry.node.attrs.position,
      x: entry.node.attrs.position.x + boundedX, y: entry.node.attrs.position.y + boundedY }) }));
}

export function officeShapeMultiNudge(entries, axis, amount) {
  if (!officeShapeMultiCanArrange(entries) || !OFFICE_SHAPE_MULTI_NUDGE_AMOUNTS.includes(amount)) {
    throw new Error("shape-multi-nudge");
  }
  const coordinate = arrangementCoordinate(axis);
  return officeShapeMultiTranslate(entries, coordinate === "x" ? amount : 0, coordinate === "y" ? amount : 0);
}

function officeShapeMultiMembers(entry) {
  if (entry?.type === "shape") return [officeShapeAttributes(entry.node?.attrs)];
  if (entry?.type !== "shapeGroup" || !Array.isArray(entry.node?.content?.content)) {
    throw new Error("shape-multi-size-entry");
  }
  officeShapeGroupAttributes(entry.node.attrs);
  return entry.node.content.content.map((member) => officeShapeAttributes(member?.attrs));
}

export function officeShapeMultiCanStyle(entries) {
  if (!Array.isArray(entries) || entries.length < 2 || entries.length > OFFICE_SHAPE_MULTI_SELECTION_LIMIT) return false;
  try { entries.forEach(officeShapeMultiMembers); return true; } catch { return false; }
}

export function officeShapeMultiAppearance(entries, options) {
  const keys = ["fill", "stroke", "strokeWidth", "fontSize", "textColor", "textStyle", "textAlign"];
  if (!officeShapeMultiCanStyle(entries) || !options || typeof options !== "object" || Array.isArray(options) ||
      Object.keys(options).length !== keys.length || keys.some((key) => !Object.hasOwn(options, key)) ||
      (options.fill !== null && !OFFICE_SHAPE_COLORS.includes(options.fill)) ||
      (options.stroke !== null && !OFFICE_SHAPE_COLORS.includes(options.stroke)) ||
      (options.strokeWidth !== null && (!Number.isSafeInteger(options.strokeWidth) ||
        options.strokeWidth < 0 || options.strokeWidth > 8)) ||
      (options.fontSize !== null && (!Number.isSafeInteger(options.fontSize) ||
        options.fontSize < 10 || options.fontSize > 72)) ||
      (options.textColor !== null && options.textColor !== "auto" &&
        !OFFICE_SHAPE_TEXT_COLORS.includes(options.textColor)) ||
      (options.textStyle !== null && options.textStyle !== "normal" &&
        !OFFICE_SHAPE_TEXT_STYLES.includes(options.textStyle)) ||
      (options.textAlign !== null && !OFFICE_SHAPE_TEXT_ALIGNMENTS.includes(options.textAlign))) {
    throw new Error("shape-multi-appearance");
  }
  const style = (shape) => officeShapeAttributes({ ...shape,
    fill: options.fill ?? shape.fill,
    stroke: options.stroke ?? shape.stroke,
    strokeWidth: options.strokeWidth ?? shape.strokeWidth,
    fontSize: options.fontSize === null ? shape.fontSize ?? null : options.fontSize === 16 ? null : options.fontSize,
    textColor: options.textColor === null ? shape.textColor ?? null : options.textColor === "auto" ? null : options.textColor,
    textStyle: options.textStyle === null ? shape.textStyle ?? null : options.textStyle === "normal" ? null : options.textStyle,
    textAlign: options.textAlign ?? shape.textAlign,
  });
  const changes = entries.map((entry) => {
    const members = officeShapeMultiMembers(entry).map(style);
    return entry.type === "shape" ? { id: entry.id, type: entry.type, attrs: members[0] } :
      { id: entry.id, type: entry.type, attrs: officeShapeGroupAttributes(entry.node.attrs), members };
  });
  return { options: { ...options }, changes };
}

export function officeShapeMultiRootSize(entry) {
  const members = officeShapeMultiMembers(entry);
  return entry.type === "shape" ? officeShapeBounds(members[0]) : officeShapeGroupBounds(entry.node.attrs, members);
}

export function officeShapeMultiRootRotation(entry) {
  return officeShapeMultiMembers(entry)[0].rotation || 0;
}

export function officeShapeMultiRotate(entries, delta) {
  if (!officeShapeMultiCanArrange(entries) || !Number.isSafeInteger(delta) || Math.abs(delta) > 359) {
    throw new Error("shape-multi-rotate");
  }
  const members = entries.map(officeShapeMultiMembers);
  const changes = entries.map((entry, index) => {
    const rotated = members[index].map((shape) => {
      const rotation = ((shape.rotation || 0) + delta + 360) % 360;
      return officeShapeAttributes({ ...shape, rotation: rotation || null });
    });
    return entry.type === "shape" ? { id: entry.id, type: entry.type, attrs: rotated[0] } :
      { id: entry.id, type: entry.type, attrs: officeShapeGroupAttributes(entry.node.attrs), members: rotated };
  });
  return { delta, changes };
}

export function officeShapeMultiTransform(entries, options) {
  const keys = ["deltaX", "deltaY", "scaleX", "scaleY", "lockAspect", "rotation", "layer"];
  if (!options || typeof options !== "object" || Array.isArray(options) ||
      Object.keys(options).length !== keys.length || keys.some((key) => !Object.hasOwn(options, key)) ||
      !Number.isSafeInteger(options.deltaX) || options.deltaX < -1000 || options.deltaX > 1000 ||
      !Number.isSafeInteger(options.deltaY) || options.deltaY < -2400 || options.deltaY > 2400 ||
      !Number.isSafeInteger(options.scaleX) || options.scaleX < 100 || options.scaleX > 5000 ||
      !Number.isSafeInteger(options.scaleY) || options.scaleY < 100 || options.scaleY > 5000 ||
      typeof options.lockAspect !== "boolean" || !Number.isSafeInteger(options.rotation) ||
      options.rotation < -359 || options.rotation > 359 ||
      (options.layer !== null && !OFFICE_SHAPE_MULTI_LAYERS.includes(options.layer))) {
    throw new Error("shape-multi-transform");
  }
  const translated = officeShapeMultiTranslate(entries, options.deltaX, options.deltaY);
  const resized = officeShapeMultiResize(entries, options.scaleX, options.scaleY, options.lockAspect);
  const rotated = officeShapeMultiRotate(entries, options.rotation);
  const changes = resized.changes.map((change, index) => {
    const position = officeShapePosition({ ...translated[index].position,
      layer: options.layer ?? translated[index].position.layer });
    if (change.type === "shape") return { ...change,
      attrs: officeShapeAttributes({ ...change.attrs, rotation: rotated.changes[index].attrs.rotation, position }) };
    return { ...change, attrs: officeShapeGroupAttributes({ ...change.attrs, position }),
      members: change.members.map((member, memberIndex) => officeShapeAttributes({ ...member,
        rotation: rotated.changes[index].members[memberIndex].rotation })) };
  });
  return { deltaX: translated[0].position.x - entries[0].node.attrs.position.x,
    deltaY: translated[0].position.y - entries[0].node.attrs.position.y,
    scaleX: resized.scaleX, scaleY: resized.scaleY, rotation: options.rotation,
    layer: options.layer, changes };
}

function scaleRange(values, minimum, maximum) {
  return {
    minimum: Math.max(...values.map((value) => Math.ceil(minimum * OFFICE_SHAPE_MULTI_SCALE_BASE / value))),
    maximum: Math.min(...values.map((value) => Math.floor(maximum * OFFICE_SHAPE_MULTI_SCALE_BASE / value))),
  };
}

export function officeShapeMultiResize(entries, scaleX, scaleY, lockAspect = false) {
  if (!officeShapeMultiCanArrange(entries) || !Number.isSafeInteger(scaleX) || !Number.isSafeInteger(scaleY) ||
      scaleX < 1 || scaleY < 1 || typeof lockAspect !== "boolean") throw new Error("shape-multi-resize");
  const members = entries.map(officeShapeMultiMembers), flat = members.flat();
  const horizontal = scaleRange(flat.map((shape) => shape.width), 80, 1200);
  const vertical = scaleRange(flat.map((shape) => shape.height), 40, 800);
  if (lockAspect) {
    const requested = Math.abs(scaleX - OFFICE_SHAPE_MULTI_SCALE_BASE) >=
      Math.abs(scaleY - OFFICE_SHAPE_MULTI_SCALE_BASE) ? scaleX : scaleY;
    const bounded = Math.max(Math.max(horizontal.minimum, vertical.minimum),
      Math.min(requested, Math.min(horizontal.maximum, vertical.maximum)));
    scaleX = bounded; scaleY = bounded;
  } else {
    scaleX = Math.max(horizontal.minimum, Math.min(scaleX, horizontal.maximum));
    scaleY = Math.max(vertical.minimum, Math.min(scaleY, vertical.maximum));
  }
  const changes = entries.map((entry, index) => {
    const resized = members[index].map((shape) => officeShapeAttributes({ ...shape,
      width: Math.round(shape.width * scaleX / OFFICE_SHAPE_MULTI_SCALE_BASE),
      height: Math.round(shape.height * scaleY / OFFICE_SHAPE_MULTI_SCALE_BASE) }));
    return entry.type === "shape" ? { id: entry.id, type: entry.type, attrs: resized[0] } :
      { id: entry.id, type: entry.type, attrs: officeShapeGroupAttributes(entry.node.attrs), members: resized };
  });
  return { scaleX, scaleY, changes };
}
