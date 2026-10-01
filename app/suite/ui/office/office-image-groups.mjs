export const OFFICE_IMAGE_GROUP_LIMIT = 20;
export const OFFICE_IMAGE_GROUP_MEMBER_LIMIT = 8;

export function officeImageGroupAttributes(attrs) {
  if (!attrs || Object.keys(attrs).length !== 3 || !/^image-group-[a-f0-9]{24}$/.test(attrs.id) ||
      !["row", "stack"].includes(attrs.layout) || !Number.isInteger(attrs.gap) || attrs.gap < 0 || attrs.gap > 48) {
    throw new Error("image-group-attributes");
  }
  return { id: attrs.id, layout: attrs.layout, gap: attrs.gap };
}
