import { officePageDescription, officePageSettings, OFFICE_PAGE_SIDES } from "./office-page.mjs";
import { officeRunningCssString, officeRunningDescription, officeRunningSettings } from "./office-running.mjs";

export const OFFICE_SECTION_LIMIT = 12;

export function officeSectionProfile(value) {
  if (!value || typeof value !== "object" || Array.isArray(value) ||
      Object.keys(value).sort().join(",") !== "page,running") throw new TypeError("Invalid Office section profile");
  const page = officePageSettings(value.page), running = officeRunningSettings(value.running, page);
  if (running.firstPage) throw new TypeError("Section profiles cannot define document-first-page settings");
  return { page, running };
}

export function officeSectionDescription(value) {
  const profile = officeSectionProfile(value);
  return `${officePageDescription(profile.page)} · ${officeRunningDescription(profile.running)}`;
}

function sectionRules(dom) {
  const sheet = [...dom.styleSheets].find((entry) => entry.href && new URL(entry.href).pathname === "/office/assets/office.css");
  return Array.from({ length: OFFICE_SECTION_LIMIT }, (_, index) => {
    const name = `office-section-${String(index + 1).padStart(2, "0")}`;
    const page = [...(sheet?.cssRules || [])].find((entry) => entry.cssText.startsWith(`@page ${name} `));
    const rules = [...(page?.cssRules || [])];
    return { name, page, header: rules.find((rule) => rule.cssText.startsWith("@top-center")),
      footer: rules.find((rule) => rule.cssText.startsWith("@bottom-center")) };
  });
}

export function clearOfficeSectionPrint(dom = document) {
  for (const entry of sectionRules(dom)) {
    entry.header?.style.setProperty("content", "none");
    entry.footer?.style.setProperty("content", "none");
  }
}

export function configureOfficeSectionPrint(content, dom = document) {
  const profiles = (content?.content || []).filter((node) => node.type === "sectionBreak")
    .map((node) => officeSectionProfile(node.attrs));
  if (profiles.length > OFFICE_SECTION_LIMIT) throw new Error("Office section limit exceeded");
  const rules = sectionRules(dom);
  clearOfficeSectionPrint(dom);
  profiles.forEach(({ page, running }, index) => {
    const entry = rules[index];
    if (!entry?.page || !entry.header || !entry.footer) throw new Error("Office section print unsupported");
    entry.page.style.setProperty("size", `${page.paper} ${page.orientation}`);
    entry.page.style.setProperty("margin", OFFICE_PAGE_SIDES.map((side) => `${page.margins[side]}mm`).join(" "));
    entry.header.style.setProperty("content", running.header ? officeRunningCssString(running.header) : "none");
    const number = running.numbering === "none" ? "" : '"Seite " counter(page)' +
      (running.numbering === "pageOfPages" ? ' " von " counter(pages)' : "");
    const footer = running.footer ? officeRunningCssString(running.footer) : "";
    entry.footer.style.setProperty("content", [footer, footer && number ? '"\\a"' : "", number].filter(Boolean).join(" ") || "none");
  });
  return profiles.map((_, index) => rules[index].name);
}
