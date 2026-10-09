import { OFFICE_SHAPE_GROUP_MEMBER_LIMIT } from "./office-shape-groups.mjs";
import { officeShapePosition } from "./office-shapes.mjs";

export const OFFICE_SHAPE_MULTI_SELECTION_LIMIT = 20;
export const OFFICE_SHAPE_MULTI_AXES = ["horizontal", "vertical"];
export const OFFICE_SHAPE_MULTI_ALIGNMENTS = ["start", "center", "end"];
export const OFFICE_SHAPE_MULTI_LAYERS = ["front", "behind"];
export const OFFICE_SHAPE_MULTI_NUDGE_AMOUNTS = [-10, -1, 1, 10];

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
