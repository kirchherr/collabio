import { officeShapeBounds, officeShapePosition } from "./office-shapes.mjs";

export const OFFICE_SHAPE_GROUP_LIMIT = 20;
export const OFFICE_SHAPE_GROUP_MEMBER_LIMIT = 8;
export const OFFICE_SHAPE_GROUP_CONNECTION_KINDS = ["line", "arrow", "doubleArrow"];
export const OFFICE_SHAPE_GROUP_CONNECTION_COLORS = ["slate", "red", "green", "teal", "blue", "purple", "black"];

export function officeShapeGroupConnection(connection) {
  if (!connection || Object.keys(connection).length !== 3 ||
      !OFFICE_SHAPE_GROUP_CONNECTION_KINDS.includes(connection.kind) ||
      !OFFICE_SHAPE_GROUP_CONNECTION_COLORS.includes(connection.color) ||
      !Number.isInteger(connection.width) || connection.width < 1 || connection.width > 8) {
    throw new Error("shape-group-connection");
  }
  return { kind: connection.kind, color: connection.color, width: connection.width };
}

export function officeShapeGroupAttributes(attrs) {
  const keys = Object.keys(attrs || {}).filter((key) => !["connection", "connections", "position"].includes(key)).sort();
  if (!attrs || keys.join(",") !== "gap,id,layout" ||
      (Object.hasOwn(attrs, "connection") && attrs.connection !== null && typeof attrs.connection !== "object") ||
      (Object.hasOwn(attrs, "connections") && attrs.connections !== null && !Array.isArray(attrs.connections)) ||
      (Object.hasOwn(attrs, "position") && attrs.position !== null && typeof attrs.position !== "object") ||
      (attrs.connection != null && attrs.connections != null) ||
      !/^shape-group-[a-f0-9]{24}$/.test(attrs.id) ||
      !["row", "stack"].includes(attrs.layout) || !Number.isInteger(attrs.gap) || attrs.gap < 0 || attrs.gap > 48) {
    throw new Error("shape-group-attributes");
  }
  const result = { id: attrs.id, layout: attrs.layout, gap: attrs.gap };
  if (attrs.connection != null) result.connection = officeShapeGroupConnection(attrs.connection);
  if (attrs.connections != null) {
    if (attrs.connections.length < 1 || attrs.connections.length >= OFFICE_SHAPE_GROUP_MEMBER_LIMIT) {
      throw new Error("shape-group-connections");
    }
    result.connections = Array.from(attrs.connections, (connection) =>
      connection === null ? null : officeShapeGroupConnection(connection));
  }
  if (attrs.position != null) result.position = officeShapePosition(attrs.position);
  return result;
}

export function officeShapeGroupConnections(attrs, memberCount) {
  const group = officeShapeGroupAttributes(attrs);
  if (!Number.isInteger(memberCount) || memberCount < 2 || memberCount > OFFICE_SHAPE_GROUP_MEMBER_LIMIT) {
    throw new Error("shape-group-members");
  }
  if (group.connections && group.connections.length !== memberCount - 1) throw new Error("shape-group-connections");
  if (group.connections) return group.connections.map((connection) => connection && { ...connection });
  return Array.from({ length: memberCount - 1 }, () => group.connection ? { ...group.connection } : null);
}

export function officeShapeGroupInsertMember(attrs, memberCount, memberIndex) {
  const group = officeShapeGroupAttributes(attrs);
  if (!group.connections) return group;
  if (group.connections.length !== memberCount - 1 || !Number.isInteger(memberIndex) || memberIndex < 0 || memberIndex > memberCount) {
    throw new Error("shape-group-connections");
  }
  const connections = [...group.connections];
  connections.splice(Math.max(0, memberIndex - 1), 0, null);
  return { ...group, connections };
}

export function officeShapeGroupRemoveMember(attrs, memberCount, memberIndex) {
  const group = officeShapeGroupAttributes(attrs);
  if (!group.connections) return group;
  if (group.connections.length !== memberCount - 1 || memberCount <= 2 || !Number.isInteger(memberIndex) || memberIndex < 0 || memberIndex >= memberCount) {
    throw new Error("shape-group-connections");
  }
  const connections = [...group.connections];
  connections.splice(memberIndex === 0 ? 0 : memberIndex - 1, 1);
  return { ...group, connections };
}

export function officeShapeGroupBounds(attrs, members) {
  const group = officeShapeGroupAttributes(attrs);
  if (!Array.isArray(members) || members.length < 2 || members.length > OFFICE_SHAPE_GROUP_MEMBER_LIMIT) {
    throw new Error("shape-group-members");
  }
  officeShapeGroupConnections(group, members.length);
  const bounds = members.map(officeShapeBounds);
  return group.layout === "row" ? {
    width: bounds.reduce((total, value) => total + value.width, 0) + group.gap * (bounds.length - 1),
    height: Math.max(...bounds.map((value) => value.height)),
  } : {
    width: Math.max(...bounds.map((value) => value.width)),
    height: bounds.reduce((total, value) => total + value.height, 0) + group.gap * (bounds.length - 1),
  };
}

export function officeShapeGroupDescription(attrs, memberCount) {
  const group = officeShapeGroupAttributes(attrs);
  officeShapeGroupConnections(group, memberCount);
  const connection = group.connections ? ` · ${group.connections.filter(Boolean).length} individuelle Verbindungen` : group.connection ?
    ` · Verbindung ${group.connection.kind}, ${group.connection.color}, ${group.connection.width} px` : "";
  const position = group.position ?
    ` · ${group.position.layer === "front" ? "vor" : "hinter"} Text · X ${group.position.x} · Y ${group.position.y} px` : "";
  return `Formgruppe · ${memberCount} Formen · ${group.layout === "row" ? "nebeneinander" : "untereinander"} · Abstand ${group.gap} px${connection}${position}`;
}
