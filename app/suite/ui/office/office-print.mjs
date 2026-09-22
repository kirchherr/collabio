// Render validated native content as inert, semantic DOM. No HTML parsing,
// editor decorations, browser grants, or remote attributes enter the print surface.
import { officeCharacterDOMAttributes } from "./office-character.mjs";
import { officeStyles, officeStyledDOMAttributes } from "./office-styles.mjs";

const blockTags = {
  paragraph: "p", bulletList: "ul", orderedList: "ol", listItem: "li",
  blockquote: "blockquote", codeBlock: "pre", horizontalRule: "hr", hardBreak: "br",
};
const markTags = { bold: "strong", italic: "em", underline: "u", strike: "s", code: "code" };

export function renderOfficePrintDocument(content, title, dom = document) {
  if (content?.type !== "doc" || !Array.isArray(content.content) || typeof title !== "string") {
    throw new Error("Invalid print document");
  }
  let count = 0;
  const styles = officeStyles(content.attrs?.styles || []);
  const render = (value, depth = 0) => {
    if (!value || ++count > 10000 || depth > 32) throw new Error("Invalid print structure");
    if (value.type === "text") {
      if (typeof value.text !== "string") throw new Error("Invalid print text");
      let text = dom.createTextNode(value.text);
      for (const mark of [...(value.marks || [])].reverse()) {
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
  const body = dom.createElement("div"); body.className = "office-print-content";
  for (const child of content.content) body.append(render(child, 1));
  article.append(heading, body);
  return article;
}
