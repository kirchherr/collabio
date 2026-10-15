// Version-owned literal running text. No HTML, URL, field or arbitrary CSS input.
export const OFFICE_RUNNING_DEFAULT = Object.freeze({ header: "", footer: "", numbering: "none" });
const INVALID_RUNNING_TEXT = /[\u0000-\u001f\u007f-\u009f\ud800-\udfff\u2028\u2029]/u;
function validText(text) {
  return typeof text === "string" && [...text].length <= 64 && !INVALID_RUNNING_TEXT.test(text);
}
export function officeRunningSettings(value = OFFICE_RUNNING_DEFAULT, page = null) {
  const keys = value && typeof value === "object" && !Array.isArray(value) ? Object.keys(value).sort().join(",") : "";
  const firstPage = value?.firstPage;
  if (!value || typeof value !== "object" || Array.isArray(value) ||
      !["footer,header,numbering", "firstPage,footer,header,numbering"].includes(keys) ||
      !["none", "page", "pageOfPages"].includes(value.numbering) ||
      [value.header, value.footer].some((text) => !validText(text)) ||
      (firstPage !== undefined && (!firstPage || typeof firstPage !== "object" || Array.isArray(firstPage) ||
        Object.keys(firstPage).sort().join(",") !== "footer,header,showNumber" ||
        [firstPage.header, firstPage.footer].some((text) => !validText(text)) ||
        typeof firstPage.showNumber !== "boolean" || (firstPage.showNumber && value.numbering === "none")))) {
    throw new TypeError("Invalid document running text");
  }
  const margins = page?.margins || { top: 18, bottom: 18 };
  if ((value.header && margins.top < 16) || ((value.footer || value.numbering !== "none") && margins.bottom < 16)) {
    throw new TypeError("Running text needs a margin of at least 16 mm");
  }
  if (firstPage && ((firstPage.header && margins.top < 16) ||
      ((firstPage.footer || firstPage.showNumber) && margins.bottom < 16))) {
    throw new TypeError("First-page running text needs a margin of at least 16 mm");
  }
  return { header: value.header, footer: value.footer, numbering: value.numbering,
    ...(firstPage ? { firstPage: { header: firstPage.header, footer: firstPage.footer, showNumber: firstPage.showNumber } } : {}) };
}
export function officeRunningDescription(value) {
  const running = officeRunningSettings(value);
  const base = `Kopfzeile: ${running.header || "leer"} · Fußzeile: ${running.footer || "leer"} · ` +
    ({ none: "Keine Seitenzahlen", page: "Seite X", pageOfPages: "Seite X von Y" })[running.numbering];
  return running.firstPage ? `${base} · Erste Seite: ${running.firstPage.header || "Kopfzeile leer"}, ` +
    `${running.firstPage.footer || "Fußzeile leer"}, Seitenzahl ${running.firstPage.showNumber ? "sichtbar" : "ausgeblendet"}` : base;
}
export function officeRunningNumber(value, page = 1, total = 3, first = false) {
  return value.numbering === "none" || (first && value.firstPage && !value.firstPage.showNumber) ? "" :
    `Seite ${page}${value.numbering === "pageOfPages" ? ` von ${total}` : ""}`;
}
export function officeResolveRunningFields(value, fields = []) {
  const running = officeRunningSettings(value), catalog = new Map(fields.map((field) => [field.key, field.value]));
  const resolve = (text) => {
    const result = text.replace(/\{\{field:([a-z][a-z0-9-]{0,47})\}\}/g,
      (_, key) => catalog.has(key) ? catalog.get(key) : `⟦Fehlendes Feld: ${key}⟧`);
    if ([...result].length > 64) throw new TypeError("Resolved running field exceeds 64 characters");
    return result;
  };
  return { header: resolve(running.header), footer: resolve(running.footer), numbering: running.numbering,
    ...(running.firstPage ? { firstPage: { header: resolve(running.firstPage.header), footer: resolve(running.firstPage.footer), showNumber: running.firstPage.showNumber } } : {}) };
}
// Encode every code point as a terminated CSS escape inside a quoted string.
// Quotes, backslashes, brackets and text resembling CSS remain literal glyphs.
export function officeRunningCssString(text) {
  return '"' + [...text].map((char) => `\\${char.codePointAt(0).toString(16)} `).join("") + '"';
}
function marginRules(dom) {
  const sheet = [...dom.styleSheets].find((entry) => entry.href && new URL(entry.href).pathname === "/office/assets/office.css");
  const pages = [...(sheet?.cssRules || [])].filter((entry) => entry.cssText.startsWith("@page office-document"));
  const pageRules = (first) => {
    const page = pages.find((entry) => entry.cssText.startsWith(first ? "@page office-document:first" : "@page office-document "));
    const rules = [...(page?.cssRules || [])];
    return ["top-center", "bottom-center"].map((name) => rules.find((rule) => rule.cssText.startsWith(`@${name}`)));
  };
  return [...pageRules(false), ...pageRules(true)];
}
export function clearOfficeRunningPrint(dom = document) {
  for (const rule of marginRules(dom)) rule?.style.setProperty("content", "none");
}
export function configureOfficeRunningPrint(value, page, dom = document) {
  const running = officeRunningSettings(value, page), [header, footer, firstHeader, firstFooter] = marginRules(dom);
  clearOfficeRunningPrint(dom);
  if (!header || !footer || !firstHeader || !firstFooter) {
    if (running.header || running.footer || running.numbering !== "none" || running.firstPage?.header ||
        running.firstPage?.footer || running.firstPage?.showNumber) throw new Error("Office running print unsupported");
    return;
  }
  const set = (headerRule, footerRule, profile, showNumber) => {
    headerRule.style.setProperty("content", profile.header ? officeRunningCssString(profile.header) : "none");
    const number = running.numbering === "none" || !showNumber ? "" : '"Seite " counter(page)' +
      (running.numbering === "pageOfPages" ? ' " von " counter(pages)' : "");
    const text = profile.footer ? officeRunningCssString(profile.footer) : "";
    footerRule.style.setProperty("content", [text, text && number ? '"\\a"' : "", number].filter(Boolean).join(" ") || "none");
  };
  set(header, footer, running, true);
  const first = running.firstPage || running;
  set(firstHeader, firstFooter, first, running.firstPage ? running.firstPage.showNumber : true);
}
