// Render validated native content as inert, semantic DOM. No HTML parsing,
// editor decorations, browser grants, or remote attributes enter the print surface.
import { officeCharacterDOMAttributes } from "./office-character.mjs";
import { officeStyles, officeStyledDOMAttributes } from "./office-styles.mjs";
import { officeImageFigure, officeImagePath } from "./office-images.mjs";
import { OFFICE_SECTION_LIMIT, officeSectionProfile } from "./office-sections.mjs";
import { officeLinkDOMAttributes } from "./office-links.mjs";
import { officeBookmarkAttributes, officeBookmarkFragment, officeReferenceInventory, officeCrossReferenceAttributes } from "./office-bookmarks.mjs";
import { officeTableAttributes, officeTableCaption, officeTableFragment } from "./office-tables.mjs";

const blockTags = {
  paragraph: "p", bulletList: "ul", orderedList: "ol", listItem: "li",
  blockquote: "blockquote", codeBlock: "pre", horizontalRule: "hr", hardBreak: "br",
};
const markTags = { bold: "strong", italic: "em", underline: "u", strike: "s", code: "code" };

export function renderOfficePrintDocument(content, title, dom = document, images = new Map()) {
  if (content?.type !== "doc" || !Array.isArray(content.content) || typeof title !== "string") {
    throw new Error("Invalid print document");
  }
  let count = 0;
  const styles = officeStyles(content.attrs?.styles || []);
  const targets = officeReferenceInventory(content);
  const targetsById = new Map(targets.map((entry) => [entry.id, entry]));
  const render = (value, depth = 0) => {
    if (!value || ++count > 10000 || depth > 32) throw new Error("Invalid print structure");
    if (value.type === "pageBreak") {
      if (depth !== 1 || Object.keys(value).length !== 1) throw new Error("Invalid page break");
      const marker = dom.createElement("div"); marker.className = "office-page-break";
      marker.setAttribute("role", "separator"); marker.setAttribute("aria-label", "Seitenumbruch");
      return marker;
    }
    if (value.type === "sectionBreak") {
      if (depth !== 1 || Object.keys(value).sort().join(",") !== "attrs,type") throw new Error("Invalid section break");
      officeSectionProfile(value.attrs);
      const marker = dom.createElement("div"); marker.className = "office-section-break";
      marker.setAttribute("role", "separator"); marker.setAttribute("aria-label", "Abschnittsumbruch");
      return marker;
    }
    if (value.type === "image") {
      const target = value.attrs?.figureId == null ? null : targetsById.get(value.attrs.figureId);
      return officeImageFigure(value.attrs, images.get(officeImagePath(value.attrs)), dom, target?.number ?? null);
    }
    if (value.type === "bookmark") {
      const attrs = officeBookmarkAttributes(value.attrs), marker = dom.createElement("span");
      marker.id = officeBookmarkFragment(attrs.id); marker.className = "office-print-bookmark";
      marker.setAttribute("data-office-bookmark", attrs.id); marker.setAttribute("aria-label", `Lesezeichen: ${attrs.label}`);
      return marker;
    }
    if (value.type === "text") {
      if (typeof value.text !== "string") throw new Error("Invalid print text");
      let text = dom.createTextNode(value.text);
      for (const mark of [...(value.marks || [])].reverse()) {
        if (mark.type === "link") {
          const wrapper = dom.createElement("a");
          for (const [name, attribute] of Object.entries(officeLinkDOMAttributes(mark.attrs?.href, { printable: true }))) wrapper.setAttribute(name, attribute);
          wrapper.append(text); text = wrapper;
          continue;
        }
        if (mark.type === "crossReference") {
          const attrs = officeCrossReferenceAttributes(mark.attrs);
          const target = targetsById.get(attrs.targetId);
          const wrapper = dom.createElement(target ? "a" : "span");
          wrapper.setAttribute("data-office-cross-reference", attrs.targetId);
          if (target) wrapper.setAttribute("href", `#${target.fragment}`);
          else wrapper.setAttribute("data-office-cross-reference-broken", "true");
          wrapper.append(text); text = wrapper;
          continue;
        }
        if (mark.type === "textStyle") {
          const wrapper = dom.createElement("span");
          for (const [name, attribute] of Object.entries(officeCharacterDOMAttributes(mark.attrs))) wrapper.setAttribute(name, attribute);
          wrapper.append(text); text = wrapper;
          continue;
        }
        if (!Object.hasOwn(markTags, mark.type)) throw new Error("Invalid print mark");
        const wrapper = dom.createElement(markTags[mark.type]);
        wrapper.append(text); text = wrapper;
      }
      return text;
    }
    if (value.type === "table") {
      const table = dom.createElement("table");
      const attrs = officeTableAttributes(value.attrs);
      if (attrs.tableId != null) {
        const target = targetsById.get(attrs.tableId);
        if (!target || target.kind !== "table") throw new Error("Invalid print table target");
        table.id = officeTableFragment(attrs.tableId); table.dataset.officeTable = attrs.tableId;
        const caption = dom.createElement("caption"); caption.textContent = officeTableCaption(attrs, target.number);
        table.append(caption);
      }
      const head = dom.createElement("thead");
      const body = dom.createElement("tbody");
      let header = true;
      for (const row of value.content || []) {
        if (row.type !== "tableRow" || ++count > 10000 || depth + 1 > 32) throw new Error("Invalid print row");
        header = header && Boolean(row.content?.length) && row.content.every((cell) => cell.type === "tableHeader");
        const tr = dom.createElement("tr");
        for (const cell of row.content || []) {
          if (!["tableCell", "tableHeader"].includes(cell.type)) throw new Error("Invalid print cell");
          const element = render(cell, depth + 2);
          if (header) element.setAttribute("scope", "col");
          tr.append(element);
        }
        (header ? head : body).append(tr);
      }
      if (head.childNodes.length) table.append(head);
      if (body.childNodes.length) table.append(body);
      return table;
    }
    let tag;
    if (value.type === "heading") {
      if (![1, 2, 3].includes(value.attrs?.level)) throw new Error("Invalid print heading");
      tag = `h${value.attrs.level}`;
    } else if (["tableCell", "tableHeader"].includes(value.type)) tag = value.type === "tableHeader" ? "th" : "td";
    else if (Object.hasOwn(blockTags, value.type)) tag = blockTags[value.type];
    else throw new Error("Unsupported print node");
    const element = dom.createElement(tag);
    if (["paragraph", "heading"].includes(value.type)) {
      for (const [name, attribute] of Object.entries(officeStyledDOMAttributes(value.attrs, styles))) {
        element.setAttribute(name, attribute);
      }
    }
    if (value.type === "orderedList") {
      const start = value.attrs?.start ?? 1;
      if (!Number.isInteger(start) || start < 1 || start > 1000000) throw new Error("Invalid print numbering");
      element.setAttribute("start", String(start));
    }
    const container = value.type === "codeBlock" ? dom.createElement("code") : element;
    for (const child of value.content || []) container.append(render(child, depth + 1));
    if (container !== element) element.append(container);
    return element;
  };
  const article = dom.createElement("article"); article.className = "office-print-document";
  const heading = dom.createElement("h1"); heading.className = "office-print-title"; heading.textContent = title;
  let body = dom.createElement("div"); body.className = "office-print-content";
  article.append(heading, body);
  let boundary = false, section = 0;
  for (const child of content.content) {
    if (!["pageBreak", "sectionBreak"].includes(child.type) && boundary) {
      body = dom.createElement("div");
      body.className = `office-print-content office-print-page-start${section ? ` office-print-section-${String(section).padStart(2, "0")}` : ""}`;
      if (section) body.dataset.officeSection = String(section);
      article.append(body); boundary = false;
    }
    body.append(render(child, 1));
    if (child.type === "pageBreak") boundary = true;
    if (child.type === "sectionBreak") {
      section += 1;
      if (section > OFFICE_SECTION_LIMIT) throw new Error("Office section limit exceeded");
      boundary = true;
    }
  }
  return article;
}
