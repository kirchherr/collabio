export const OFFICE_SHAPE_GROUP_LIMIT = 20;
export const OFFICE_SHAPE_GROUP_MEMBER_LIMIT = 8;

export function officeShapeGroupAttributes(attrs) {
  if (!attrs || Object.keys(attrs).length !== 3 || !/^shape-group-[a-f0-9]{24}$/.test(attrs.id) ||
      !["row", "stack"].includes(attrs.layout) || !Number.isInteger(attrs.gap) || attrs.gap < 0 || attrs.gap > 48) {
    throw new Error("shape-group-attributes");
  }
  return { id: attrs.id, layout: attrs.layout, gap: attrs.gap };
}
