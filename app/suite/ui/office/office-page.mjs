// Inert version-owned page geometry. Values are never accepted as arbitrary CSS.
export const OFFICE_PAGE_DEFAULT = Object.freeze({ paper: "a4", orientation: "portrait",
  margins: Object.freeze({ top: 18, right: 18, bottom: 18, left: 18 }) });
export const OFFICE_PAGE_SIDES = Object.freeze(["top", "right", "bottom", "left"]);

export function officePageSettings(value = OFFICE_PAGE_DEFAULT) {
  const object = (entry) => entry && typeof entry === "object" && !Array.isArray(entry);
  if (!object(value) || Object.keys(value).sort().join(",") !== "margins,orientation,paper" ||
      !["a4", "letter"].includes(value.paper) || !["portrait", "landscape"].includes(value.orientation) ||
      !object(value.margins) || Object.keys(value.margins).sort().join(",") !== "bottom,left,right,top" ||
      OFFICE_PAGE_SIDES.some((side) => !Number.isInteger(value.margins[side]) || value.margins[side] < 5 || value.margins[side] > 50)) {
    throw new TypeError("Invalid document page settings");
  }
  return { paper: value.paper, orientation: value.orientation,
    margins: Object.fromEntries(OFFICE_PAGE_SIDES.map((side) => [side, value.margins[side]])) };
}

export function officePageDimensions(value) {
  const page = officePageSettings(value);
  const [short, long] = page.paper === "a4" ? [210, 297] : [215.9, 279.4];
  const [width, height] = page.orientation === "portrait" ? [short, long] : [long, short];
  return { width, height, contentWidth: width - page.margins.left - page.margins.right,
    contentHeight: height - page.margins.top - page.margins.bottom };
}

export function officePageDescription(value) {
  const page = officePageSettings(value);
  return `${page.paper === "a4" ? "A4" : "Letter"} · ${page.orientation === "portrait" ? "Hochformat" : "Querformat"} · ` +
    `Ränder oben ${page.margins.top}, rechts ${page.margins.right}, unten ${page.margins.bottom}, links ${page.margins.left} mm`;
}

export function officePagePreview(element, value) {
  const page = officePageSettings(value), { width, height } = officePageDimensions(page);
  element.style.setProperty("--office-page-width", `${width}mm`);
  element.style.setProperty("--office-page-height", `${height}mm`);
  element.style.setProperty("--office-page-ratio", `${width} / ${height}`);
  for (const side of OFFICE_PAGE_SIDES) {
    element.style.setProperty(`--office-page-${side}`, `${page.margins[side]}mm`);
    element.style.setProperty(`--office-preview-${side}`, `${page.margins[side] / (side === "left" || side === "right" ? width : height) * 100}%`);
  }
}

export function configureOfficePrintPage(value, dom = document) {
  const page = officePageSettings(value);
  const sheet = [...dom.styleSheets].find((entry) => entry.href && new URL(entry.href).pathname === "/office/assets/office.css");
  const rule = sheet && [...sheet.cssRules].find((entry) => entry.cssText.startsWith("@page office-document"));
  if (!rule) throw new Error("Office print page rule unavailable");
  rule.style.setProperty("size", `${page.paper} ${page.orientation}`);
  rule.style.setProperty("margin", OFFICE_PAGE_SIDES.map((side) => `${page.margins[side]}mm`).join(" "));
}
