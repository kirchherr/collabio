import { OFFICE_SHAPE_GROUP_LIMIT, OFFICE_SHAPE_GROUP_MEMBER_LIMIT, officeShapeGroupAttributes,
  officeShapeGroupConnections,
  officeShapeGroupBounds } from "./office-shape-groups.mjs";
import { OFFICE_SHAPE_COLORS, OFFICE_SHAPE_TEXT_ALIGNMENTS, OFFICE_SHAPE_TEXT_COLORS,
  OFFICE_SHAPE_TEXT_STYLES, officeShapeAttributes, officeShapeBounds,
  officeShapePosition } from "./office-shapes.mjs";

export const OFFICE_SHAPE_MULTI_SELECTION_LIMIT = 20;
export const OFFICE_SHAPE_MULTI_AXES = ["horizontal", "vertical"];
export const OFFICE_SHAPE_MULTI_ALIGNMENTS = ["start", "center", "end"];
export const OFFICE_SHAPE_MULTI_LAYERS = ["front", "behind"];
export const OFFICE_SHAPE_MULTI_NUDGE_AMOUNTS = [-10, -1, 1, 10];
export const OFFICE_SHAPE_MULTI_ORDER_ACTIONS = ["previous", "next", "first", "last"];
export const OFFICE_SHAPE_MULTI_SCALE_BASE = 1000;
const OFFICE_SHAPE_MULTI_APPEARANCE_KEYS = [
  "fill", "stroke", "strokeWidth", "fontSize", "textColor", "textStyle", "textAlign",
];

export function officeShapeMultiSelection(entries, ids) {
  if (!Array.isArray(entries) || !Array.isArray(ids) || ids.length > OFFICE_SHAPE_MULTI_SELECTION_LIMIT ||
      ids.some((id) => typeof id !== "string") || new Set(ids).size !== ids.length) throw new Error("shape-multi-selection");
  const wanted = new Set(ids);
  return entries.filter((entry) => wanted.has(entry.id) && ["shape", "shapeGroup"].includes(entry.type))
    .sort((left, right) => left.rootIndex - right.rootIndex);
}

export function officeShapeMultiSelectionPlan(entries, ids) {
  if (!Array.isArray(entries) || !Array.isArray(ids) || ids.length > OFFICE_SHAPE_MULTI_SELECTION_LIMIT ||
      ids.some((id) => typeof id !== "string") || new Set(ids).size !== ids.length) {
    throw new Error("shape-multi-selection-plan");
  }
  const byId = new Map(); let previous = -1;
  for (const entry of entries) {
    if (!entry || typeof entry.id !== "string" || byId.has(entry.id) ||
        !["shape", "shapeGroup"].includes(entry.type) || !Number.isSafeInteger(entry.rootIndex) ||
        entry.rootIndex <= previous || entry.rootIndex < 0) throw new Error("shape-multi-selection-plan");
    byId.set(entry.id, entry); previous = entry.rootIndex;
  }
  const wanted = new Set(ids);
  if (ids.some((id) => !byId.has(id))) throw new Error("shape-multi-selection-plan");
  const selected = entries.filter((entry) => wanted.has(entry.id));
  if (selected.length !== ids.length) throw new Error("shape-multi-selection-plan");
  return { ids: selected.map((entry) => entry.id), entries: selected };
}

export function officeShapeMultiUnlocked(entries) {
  if (!Array.isArray(entries) || entries.length < 1 || entries.length > OFFICE_SHAPE_MULTI_SELECTION_LIMIT) return false;
  return entries.every((entry) => ["shape", "shapeGroup"].includes(entry?.type) && entry.node?.attrs &&
    [undefined, null, true].includes(entry.node.attrs.locked) && [undefined, null, true].includes(entry.node.attrs.hidden) &&
    entry.node.attrs.locked !== true && entry.node.attrs.hidden !== true);
}

export function officeShapeMultiObjectState(entries, options) {
  if (!Array.isArray(entries) || entries.length < 1 || entries.length > OFFICE_SHAPE_MULTI_SELECTION_LIMIT ||
      !options || typeof options !== "object" || Array.isArray(options) ||
      Object.keys(options).sort().join(",") !== "hidden,locked" ||
      ![null, true, false].includes(options.hidden) || ![null, true, false].includes(options.locked) ||
      (options.hidden === null) === (options.locked === null)) throw new Error("shape-multi-object-state");
  const ids = new Set(); let previous = -1;
  const changes = entries.map((entry) => {
    if (typeof entry?.id !== "string" || ids.has(entry.id) || !Number.isSafeInteger(entry.rootIndex) ||
        entry.rootIndex <= previous || !["shape", "shapeGroup"].includes(entry.type)) {
      throw new Error("shape-multi-object-state");
    }
    ids.add(entry.id); previous = entry.rootIndex;
    const attrs = entry.type === "shape" ? officeShapeAttributes(entry.node?.attrs) :
      officeShapeGroupAttributes(entry.node?.attrs);
    if (attrs.id !== entry.id) throw new Error("shape-multi-object-state");
    const next = { ...attrs };
    for (const key of ["hidden", "locked"]) {
      if (options[key] === true) next[key] = true;
      else if (options[key] === false) delete next[key];
    }
    return { id: entry.id, type: entry.type, attrs: entry.type === "shape" ?
      officeShapeAttributes(next) : officeShapeGroupAttributes(next) };
  });
  return { options: { ...options }, changes };
}

export function officeShapeMultiRange(entries, anchorId, targetId) {
  const anchor = entries.findIndex((entry) => entry.id === anchorId), target = entries.findIndex((entry) => entry.id === targetId);
  if (anchor < 0 || target < 0) return [targetId];
  return entries.slice(Math.min(anchor, target), Math.max(anchor, target) + 1).map((entry) => entry.id);
}

export function officeShapeMultiOrder(rootCount, entries, action) {
  if (!Number.isSafeInteger(rootCount) || rootCount < 1 || !Array.isArray(entries) || entries.length < 2 ||
      entries.length > OFFICE_SHAPE_MULTI_SELECTION_LIMIT || !OFFICE_SHAPE_MULTI_ORDER_ACTIONS.includes(action) ||
      entries.some((entry) => !["shape", "shapeGroup"].includes(entry?.type) ||
        !Number.isSafeInteger(entry.rootIndex) || entry.rootIndex < 0 || entry.rootIndex >= rootCount)) {
    throw new Error("shape-multi-order");
  }
  const indexes = entries.map((entry) => entry.rootIndex);
  if (new Set(indexes).size !== indexes.length) throw new Error("shape-multi-order");
  const selected = new Set(indexes), order = Array.from({ length: rootCount }, (_, index) => index);
  if (action === "previous") {
    for (let index = 1; index < order.length; index += 1) {
      if (selected.has(order[index]) && !selected.has(order[index - 1])) {
        [order[index - 1], order[index]] = [order[index], order[index - 1]];
      }
    }
  } else if (action === "next") {
    for (let index = order.length - 2; index >= 0; index -= 1) {
      if (selected.has(order[index]) && !selected.has(order[index + 1])) {
        [order[index], order[index + 1]] = [order[index + 1], order[index]];
      }
    }
  } else {
    const picked = order.filter((index) => selected.has(index));
    const remainder = order.filter((index) => !selected.has(index));
    order.splice(0, order.length, ...(action === "first" ? [...picked, ...remainder] : [...remainder, ...picked]));
  }
  return { action, order, changed: order.some((rootIndex, index) => rootIndex !== index) };
}

export function officeShapeMultiMoveTo(rootCount, entries, target) {
  if (!Number.isSafeInteger(rootCount) || rootCount < 2 || !Array.isArray(entries) || entries.length < 2 ||
      entries.length > OFFICE_SHAPE_MULTI_SELECTION_LIMIT || entries.length >= rootCount ||
      !Number.isSafeInteger(target) || target < 1 || target > rootCount - entries.length + 1) {
    throw new Error("shape-multi-move-to");
  }
  const selected = new Set(); let previous = -1;
  for (const entry of entries) {
    if (!entry || !["shape", "shapeGroup"].includes(entry.type) || !Number.isSafeInteger(entry.rootIndex) ||
        entry.rootIndex <= previous || entry.rootIndex < 0 || entry.rootIndex >= rootCount ||
        selected.has(entry.rootIndex)) throw new Error("shape-multi-move-to");
    selected.add(entry.rootIndex); previous = entry.rootIndex;
  }
  const picked = [...selected];
  const remainder = Array.from({ length: rootCount }, (_, index) => index).filter((index) => !selected.has(index));
  const insertion = target - 1;
  const order = [...remainder.slice(0, insertion), ...picked, ...remainder.slice(insertion)];
  return { target, order, changed: order.some((rootIndex, index) => rootIndex !== index) };
}

export function officeShapeMultiCanOrder(rootCount, entries, action) {
  try { return officeShapeMultiOrder(rootCount, entries, action).changed; } catch { return false; }
}

export function officeShapeMultiCanGroup(entries) {
  return entries.length >= 2 && entries.length <= OFFICE_SHAPE_GROUP_MEMBER_LIMIT &&
    officeShapeMultiUnlocked(entries) &&
    entries.every((entry) => entry.type === "shape" && entry.node?.attrs.position == null && entry.node?.attrs.wrap == null) &&
    entries.every((entry, index) => index === 0 || entry.rootIndex === entries[index - 1].rootIndex + 1);
}

export function officeShapeMultiCanArrange(entries, minimum = 2) {
  if (!Array.isArray(entries) || !Number.isInteger(minimum) || minimum < 2 || entries.length < minimum ||
      entries.length > OFFICE_SHAPE_MULTI_SELECTION_LIMIT) return false;
  return officeShapeMultiUnlocked(entries) && entries.every((entry) => {
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

export function officeShapeMultiCanUngroup(entries) {
  if (!Array.isArray(entries) || entries.length < 2 || entries.length > OFFICE_SHAPE_MULTI_SELECTION_LIMIT) return false;
  try {
    if (!officeShapeMultiUnlocked(entries)) return false;
    const positioned = entries[0]?.node?.attrs.position != null;
    return entries.every((entry) => {
      if (entry?.type !== "shapeGroup" || (entry.node?.attrs.position != null) !== positioned) return false;
      const members = officeShapeMultiMembers(entry);
      return members.length >= 2 && members.length <= OFFICE_SHAPE_GROUP_MEMBER_LIMIT &&
        members.every((member) => member.position == null && member.wrap == null);
    });
  } catch { return false; }
}

export function officeShapeMultiUngroup(entries, placements = null) {
  if (!officeShapeMultiCanUngroup(entries)) throw new Error("shape-multi-ungroup");
  const positioned = entries[0].node.attrs.position != null;
  const placementById = new Map();
  if (positioned) {
    if (!Array.isArray(placements)) throw new Error("shape-multi-ungroup");
    for (const placement of placements) {
      if (typeof placement?.id !== "string" || placementById.has(placement.id)) throw new Error("shape-multi-ungroup");
      placementById.set(placement.id, officeShapePosition(placement.position));
    }
  } else if (placements != null) throw new Error("shape-multi-ungroup");
  const groups = entries.map((entry) => ({ id: entry.id, rootIndex: entry.rootIndex,
    attrs: officeShapeGroupAttributes(entry.node.attrs),
    memberIds: entry.node.content.content.map((member) => member.attrs.id),
    ...(positioned ? { memberPositions: entry.node.content.content.map((member) => {
      const position = placementById.get(member.attrs.id);
      if (!position || position.layer !== entry.node.attrs.position.layer) throw new Error("shape-multi-ungroup");
      placementById.delete(member.attrs.id); return { id: member.attrs.id, position };
    }) } : {}) }));
  if (placementById.size) throw new Error("shape-multi-ungroup");
  return { groups, memberIds: groups.flatMap((group) => group.memberIds) };
}

export function officeShapeMultiRegroup(entries, snapshot) {
  if (!Array.isArray(entries) || !Array.isArray(snapshot?.groups) || snapshot.groups.length < 2 ||
      snapshot.groups.length > OFFICE_SHAPE_MULTI_SELECTION_LIMIT) throw new Error("shape-multi-regroup");
  const byId = new Map(), existingIds = new Set();
  for (const entry of entries) {
    if (typeof entry?.id !== "string" || existingIds.has(entry.id)) throw new Error("shape-multi-regroup");
    existingIds.add(entry.id); byId.set(entry.id, entry);
  }
  const groupIds = new Set(), memberIds = new Set();
  const positioned = snapshot.groups[0]?.attrs?.position != null;
  const groups = snapshot.groups.map((group) => {
    const attrs = officeShapeGroupAttributes(group?.attrs);
    if (typeof group?.id !== "string" || attrs.id !== group.id || (attrs.position != null) !== positioned ||
        groupIds.has(group.id) || existingIds.has(group.id) || !Array.isArray(group.memberIds) ||
        group.memberIds.length < 2 || group.memberIds.length > OFFICE_SHAPE_GROUP_MEMBER_LIMIT) {
      throw new Error("shape-multi-regroup");
    }
    officeShapeGroupConnections(attrs, group.memberIds.length);
    const expectedPositions = new Map();
    if (positioned) {
      if (!Array.isArray(group.memberPositions) || group.memberPositions.length !== group.memberIds.length) {
        throw new Error("shape-multi-regroup");
      }
      for (const placement of group.memberPositions) {
        if (typeof placement?.id !== "string" || expectedPositions.has(placement.id)) throw new Error("shape-multi-regroup");
        const position = officeShapePosition(placement.position);
        if (position.layer !== attrs.position.layer) throw new Error("shape-multi-regroup");
        expectedPositions.set(placement.id, position);
      }
    } else if (group.memberPositions != null) throw new Error("shape-multi-regroup");
    groupIds.add(group.id);
    const members = group.memberIds.map((id) => {
      const entry = byId.get(id);
      if (typeof id !== "string" || memberIds.has(id) || entry?.type !== "shape" || entry.id !== id ||
          !Number.isSafeInteger(entry.rootIndex) || entry.rootIndex < 0) throw new Error("shape-multi-regroup");
      const shape = officeShapeAttributes(entry.node?.attrs);
      const expected = expectedPositions.get(id);
      if (shape.id !== id || shape.wrap != null || (!positioned && shape.position != null) ||
          (positioned && (!expected || shape.position?.layer !== expected.layer || shape.position.x !== expected.x ||
            shape.position.y !== expected.y))) throw new Error("shape-multi-regroup");
      expectedPositions.delete(id);
      memberIds.add(id); return entry;
    });
    if (expectedPositions.size) throw new Error("shape-multi-regroup");
    if (members.some((entry, index) => index > 0 && entry.rootIndex !== members[index - 1].rootIndex + 1)) {
      throw new Error("shape-multi-regroup");
    }
    return { id: group.id, attrs, memberIds: [...group.memberIds],
      ...(positioned ? { memberPositions: group.memberPositions.map((placement) => ({
        id: placement.id, position: officeShapePosition(placement.position) })) } : {}),
      rootIndex: members[0].rootIndex,
      endRootIndex: members.at(-1).rootIndex };
  });
  if (groups.some((group, index) => index > 0 && group.rootIndex <= groups[index - 1].endRootIndex) ||
      entries.filter((entry) => entry.type === "shapeGroup").length + groups.length > OFFICE_SHAPE_GROUP_LIMIT) {
    throw new Error("shape-multi-regroup");
  }
  return { groups, memberIds: [...memberIds] };
}

export function officeShapeMultiCanRegroup(entries, snapshot) {
  try { officeShapeMultiRegroup(entries, snapshot); return true; } catch { return false; }
}

export function officeShapeMultiCanStyle(entries) {
  if (!Array.isArray(entries) || entries.length < 2 || entries.length > OFFICE_SHAPE_MULTI_SELECTION_LIMIT) return false;
  try { if (!officeShapeMultiUnlocked(entries)) return false; entries.forEach(officeShapeMultiMembers); return true; } catch { return false; }
}

function validAppearanceOptions(options, allowNull) {
  const nullable = (value) => allowNull && value === null;
  return options && typeof options === "object" && !Array.isArray(options) &&
    Object.keys(options).length === OFFICE_SHAPE_MULTI_APPEARANCE_KEYS.length &&
    OFFICE_SHAPE_MULTI_APPEARANCE_KEYS.every((key) => Object.hasOwn(options, key)) &&
    (nullable(options.fill) || OFFICE_SHAPE_COLORS.includes(options.fill)) &&
    (nullable(options.stroke) || OFFICE_SHAPE_COLORS.includes(options.stroke)) &&
    (nullable(options.strokeWidth) || (Number.isSafeInteger(options.strokeWidth) &&
      options.strokeWidth >= 0 && options.strokeWidth <= 8)) &&
    (nullable(options.fontSize) || (Number.isSafeInteger(options.fontSize) &&
      options.fontSize >= 10 && options.fontSize <= 72)) &&
    (nullable(options.textColor) || options.textColor === "auto" ||
      OFFICE_SHAPE_TEXT_COLORS.includes(options.textColor)) &&
    (nullable(options.textStyle) || options.textStyle === "normal" ||
      OFFICE_SHAPE_TEXT_STYLES.includes(options.textStyle)) &&
    (nullable(options.textAlign) || OFFICE_SHAPE_TEXT_ALIGNMENTS.includes(options.textAlign));
}

function appearanceSample(shape) {
  return {
    fill: shape.fill,
    stroke: shape.stroke,
    strokeWidth: shape.strokeWidth,
    fontSize: shape.fontSize ?? 16,
    textColor: shape.textColor ?? "auto",
    textStyle: shape.textStyle ?? "normal",
    textAlign: shape.textAlign,
  };
}

export function officeShapeMultiAppearanceSample(entry) {
  const samples = officeShapeMultiMembers(entry).map(appearanceSample);
  const sample = samples[0];
  if (!validAppearanceOptions(sample, false) ||
      samples.some((candidate) => OFFICE_SHAPE_MULTI_APPEARANCE_KEYS.some((key) => candidate[key] !== sample[key]))) {
    throw new Error("shape-multi-appearance-sample");
  }
  return { ...sample };
}

export function officeShapeMultiCanCopyAppearance(entries) {
  if (!Array.isArray(entries) || entries.length !== 1) return false;
  try { if (!officeShapeMultiUnlocked(entries)) return false; officeShapeMultiAppearanceSample(entries[0]); return true; } catch { return false; }
}

export function officeShapeMultiAppearance(entries, options) {
  if (!officeShapeMultiCanStyle(entries) || !validAppearanceOptions(options, true)) {
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

export function officeShapeMultiPasteAppearance(entries, sample) {
  if (!validAppearanceOptions(sample, false)) throw new Error("shape-multi-appearance-paste");
  return officeShapeMultiAppearance(entries, { ...sample });
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
