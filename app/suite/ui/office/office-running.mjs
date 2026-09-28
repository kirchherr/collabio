// Version-owned literal running text. No HTML, URL, field or arbitrary CSS input.
export const OFFICE_RUNNING_DEFAULT = Object.freeze({ header: "", footer: "", numbering: "none" });
export function officeRunningSettings(value = OFFICE_RUNNING_DEFAULT, page = null) {
  if (!value || typeof value !== "object" || Array.isArray(value) ||
      Object.keys(value).sort().join(",") !== "footer,header,numbering" ||
      !["none", "page", "pageOfPages"].includes(value.numbering) ||
      [value.header, value.footer].some((text) => typeof text !== "string" || [...text].length > 64 ||
        /[\u0000-\u001f\u007f-\u009f\ud800-\udfff\u2028\u2029]/u.test(text))) {
    throw new TypeError("Invalid document running text");
  }
  const margins = page?.margins || { top: 18, bottom: 18 };
  if ((value.header && margins.top < 16) || ((value.footer || value.numbering !== "none") && margins.bottom < 16)) {
    throw new TypeError("Running text needs a margin of at least 16 mm");
  }
  return { header: value.header, footer: value.footer, numbering: value.numbering };
}
export function officeRunningDescription(value) {
  const running = officeRunningSettings(value);
  return `Kopfzeile: ${running.header || "leer"} · Fußzeile: ${running.footer || "leer"} · ` +
    ({ none: "Keine Seitenzahlen", page: "Seite X", pageOfPages: "Seite X von Y" })[running.numbering];
}
export function officeRunningNumber(value, page = 1, total = 3) {
  return value.numbering === "none" ? "" : `Seite ${page}${value.numbering === "pageOfPages" ? ` von ${total}` : ""}`;
}
// Encode every code point as a terminated CSS escape inside a quoted string.
// Quotes, backslashes, brackets and text resembling CSS remain literal glyphs.
export function officeRunningCssString(text) {
  return '"' + [...text].map((char) => `\\${char.codePointAt(0).toString(16)} `).join("") + '"';
}
function marginRules(dom) {
  const sheet = [...dom.styleSheets].find((entry) => entry.href && new URL(entry.href).pathname === "/office/assets/office.css");
  const page = sheet && [...sheet.cssRules].find((entry) => entry.cssText.startsWith("@page office-document"));
  const rules = [...(page?.cssRules || [])];
  return ["top-center", "bottom-center"].map((name) => rules.find((rule) => rule.cssText.startsWith(`@${name}`)));
}
export function clearOfficeRunningPrint(dom = document) {
  for (const rule of marginRules(dom)) rule?.style.setProperty("content", "none");
}
export function configureOfficeRunningPrint(value, page, dom = document) {
  const running = officeRunningSettings(value, page), [header, footer] = marginRules(dom);
  clearOfficeRunningPrint(dom);
  if (!header || !footer) {
    if (running.header || running.footer || running.numbering !== "none") throw new Error("Office running print unsupported");
    return;
  }
  header.style.setProperty("content", running.header ? officeRunningCssString(running.header) : "none");
  const number = running.numbering === "none" ? "" : '"Seite " counter(page)' +
    (running.numbering === "pageOfPages" ? ' " von " counter(pages)' : "");
  const text = running.footer ? officeRunningCssString(running.footer) : "";
  footer.style.setProperty("content", [text, text && number ? '"\\a"' : "", number].filter(Boolean).join(" ") || "none");
}
