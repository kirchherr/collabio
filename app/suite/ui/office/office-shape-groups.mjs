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
  const keys = Object.keys(attrs || {}).filter((key) => key !== "connection").sort();
  if (!attrs || keys.join(",") !== "gap,id,layout" ||
      (Object.hasOwn(attrs, "connection") && attrs.connection !== null && typeof attrs.connection !== "object") ||
      !/^shape-group-[a-f0-9]{24}$/.test(attrs.id) ||
      !["row", "stack"].includes(attrs.layout) || !Number.isInteger(attrs.gap) || attrs.gap < 0 || attrs.gap > 48) {
    throw new Error("shape-group-attributes");
  }
  const result = { id: attrs.id, layout: attrs.layout, gap: attrs.gap };
  if (attrs.connection != null) result.connection = officeShapeGroupConnection(attrs.connection);
  return result;
}
