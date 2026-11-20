export const OFFICE_IMAGE_GROUP_LIMIT = 20;
export const OFFICE_IMAGE_GROUP_MEMBER_LIMIT = 8;
export const OFFICE_IMAGE_GROUP_LAYOUTS = Object.freeze({
  row: { label: "nebeneinander", columns: null },
  stack: { label: "untereinander", columns: 1 },
  "grid-2": { label: "Raster mit 2 Spalten", columns: 2 },
  "grid-3": { label: "Raster mit 3 Spalten", columns: 3 },
  "grid-4": { label: "Raster mit 4 Spalten", columns: 4 },
});

export function officeImageGroupAttributes(attrs) {
  if (!attrs || Object.keys(attrs).length !== 3 || !/^image-group-[a-f0-9]{24}$/.test(attrs.id) ||
      !Object.hasOwn(OFFICE_IMAGE_GROUP_LAYOUTS, attrs.layout) || !Number.isInteger(attrs.gap) || attrs.gap < 0 || attrs.gap > 48) {
    throw new Error("image-group-attributes");
  }
  return { id: attrs.id, layout: attrs.layout, gap: attrs.gap };
}

export function officeImageGroupColumns(layout, memberCount) {
  const profile = OFFICE_IMAGE_GROUP_LAYOUTS[layout];
  if (!profile || !Number.isInteger(memberCount) || memberCount < 2 || memberCount > OFFICE_IMAGE_GROUP_MEMBER_LIMIT) {
    throw new Error("image-group-layout");
  }
  return profile.columns == null ? memberCount : profile.columns;
}

export function officeImageGroupLayoutLabel(layout) {
  const profile = OFFICE_IMAGE_GROUP_LAYOUTS[layout];
  if (!profile) throw new Error("image-group-layout");
  return profile.label;
}
