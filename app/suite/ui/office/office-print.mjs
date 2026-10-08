// Render validated native content as inert, semantic DOM. No HTML parsing,
// editor decorations, browser grants, or remote attributes enter the print surface.
import { officeCharacterDOMAttributes } from "./office-character.mjs";
import { officeStyles, officeStyledDOMAttributes } from "./office-styles.mjs";
import { officeImageFigure, officeImagePath } from "./office-images.mjs";
import { officeImageGroupAttributes, officeImageGroupColumns, OFFICE_IMAGE_GROUP_MEMBER_LIMIT } from "./office-image-groups.mjs";
import { officeShapeElement } from "./office-shapes.mjs";
import { officeShapeGroupAttributes, OFFICE_SHAPE_GROUP_MEMBER_LIMIT } from "./office-shape-groups.mjs";
import { OFFICE_SECTION_LIMIT, officeSectionProfile } from "./office-sections.mjs";
import { officeLinkDOMAttributes } from "./office-links.mjs";
import { officeBookmarkAttributes, officeBookmarkFragment, officeReferenceInventory, officeCrossReferenceAttributes } from "./office-bookmarks.mjs";
import { officeTableAttributes, officeTableCaption, officeTableCellAttributes, officeTableCellDOMAttributes, officeTableDOMAttributes, officeTableFragment, officeTableGrid } from "./office-tables.mjs";
import { officeBibliographyLabel, officeCitationAttributes, officeCitationLabel, officeEquationAttributes, officeFieldAttributes, officeNoteAttributes, officeSemanticInventory } from "./office-semantics.mjs";
import { officeDocumentReferenceAttributes, officeDocumentReferenceDescription, officeDocumentReferenceKey } from "./office-document-references.mjs";
import { officeDocumentCardAttributes, officeDocumentCardDescription, officeDocumentCardKey } from "./office-document-cards.mjs";
import { officeChartElement } from "./office-charts.mjs";

const blockTags = {
  paragraph: "p", bulletList: "ul", orderedList: "ol", listItem: "li",
  blockquote: "blockquote", codeBlock: "pre", horizontalRule: "hr", hardBreak: "br",
};
const markTags = { bold: "strong", italic: "em", underline: "u", strike: "s", code: "code" };

export function renderOfficePrintDocument(content, title, dom = document, images = new Map(), documentReferences = new Map(), informationClassification = "internal") {
  if (content?.type !== "doc" || !Array.isArray(content.content) || typeof title !== "string") {
    throw new Error("Invalid print document");
  }
  const classifications = { public: "Öffentlich", internal: "Intern", confidential: "Vertraulich", restricted: "Streng vertraulich" };
  if (!Object.hasOwn(classifications, informationClassification)) throw new Error("Invalid document classification");
  let count = 0;
  const styles = officeStyles(content.attrs?.styles || []);
  const targets = officeReferenceInventory(content);
  const targetsById = new Map(targets.map((entry) => [entry.id, entry]));
  const semantics = officeSemanticInventory(content);
  let footnote = 0, endnote = 0;
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
    if (value.type === "documentCard") {
      if (depth !== 1 || value.content) throw new Error("Invalid document object");
      const attrs = officeDocumentCardAttributes(value.attrs);
      const resolved = documentReferences.get(officeDocumentCardKey(attrs));
      const available = resolved?.status === "resolved";
      const card = dom.createElement("article"); card.className = "office-document-card office-print-document-card";
      card.dataset.officeDocumentCard = attrs.targetObjectId; card.dataset.officeDocumentVersion = attrs.targetVersionId;
      card.dataset.officeDocumentMode = attrs.mode; card.dataset.officeReferenceStatus = available ? "resolved" : "unavailable";
      const kind = dom.createElement("span"); kind.className = "office-document-card-kind";
      kind.textContent = attrs.mode === "linked" ? "Verknüpftes Dokument" : "Dokument-Momentaufnahme";
      const label = dom.createElement("strong"); label.className = "office-document-card-title";
      label.textContent = available ? resolved.title : "Dokumentobjekt nicht verfügbar";
      const detail = dom.createElement("span"); detail.className = "office-document-card-detail";
      detail.textContent = available ? `${resolved.isCurrentVersion ? "Aktuelle" : "Gespeicherte"} Version` :
        "Zugriff oder Version nicht verfügbar";
      card.setAttribute("aria-label", officeDocumentCardDescription(attrs, documentReferences));
      card.append(kind, label, detail); return card;
    }
    if (value.type === "chart") {
      if (depth !== 1 || value.content) throw new Error("Invalid chart");
      const chart = officeChartElement(value.attrs, dom); chart.classList.add("office-print-chart"); return chart;
    }
    if (value.type === "image") {
      const target = value.attrs?.figureId == null ? null : targetsById.get(value.attrs.figureId);
      return officeImageFigure(value.attrs, images.get(officeImagePath(value.attrs)), dom, target?.number ?? null);
    }
    if (value.type === "imageGroup") {
      const attrs = officeImageGroupAttributes(value.attrs), children = value.content || [];
      if (depth !== 1 || children.length < 2 || children.length > OFFICE_IMAGE_GROUP_MEMBER_LIMIT ||
          children.some((child) => child.type !== "image" || child.attrs?.wrap != null || child.attrs?.position != null)) {
        throw new Error("Invalid image group");
      }
      const group = dom.createElement("section"); group.className = "office-image-group office-print-image-group";
      group.dataset.imageGroup = attrs.id; group.dataset.imageGroupLayout = attrs.layout;
      group.style.setProperty("--image-group-gap", `${attrs.gap}px`);
      group.style.setProperty("--image-group-columns", String(officeImageGroupColumns(attrs.layout, children.length)));
      for (const child of children) group.append(render(child, depth + 1));
      return group;
    }
    if (value.type === "shape") {
      if (depth !== 1 || value.content) throw new Error("Invalid shape");
      const shape = officeShapeElement(value.attrs, dom); shape.classList.add("office-print-shape"); return shape;
    }
    if (value.type === "shapeGroup") {
      const attrs = officeShapeGroupAttributes(value.attrs), children = value.content || [];
      if (depth !== 1 || children.length < 2 || children.length > OFFICE_SHAPE_GROUP_MEMBER_LIMIT ||
          children.some((child) => child.type !== "shape" || child.attrs?.wrap != null || child.attrs?.position != null)) {
        throw new Error("Invalid shape group");
      }
      const group = dom.createElement("section"); group.className = "office-shape-group office-print-shape-group";
      group.dataset.shapeGroup = attrs.id; group.dataset.shapeGroupLayout = attrs.layout;
      group.style.setProperty("--shape-group-gap", `${attrs.gap}px`);
      group.style.setProperty("--shape-group-columns", attrs.layout === "row" ? String(children.length) : "1");
      if (attrs.connection) {
        group.dataset.shapeGroupConnection = attrs.connection.kind;
        group.dataset.shapeGroupConnectionColor = attrs.connection.color;
        group.style.setProperty("--shape-group-connection-width", `${attrs.connection.width}px`);
      }
      for (const child of children) {
        const member = dom.createElement("div"); member.className = "office-print-shape-member";
        const shape = officeShapeElement(child.attrs, dom); shape.classList.add("office-print-shape"); member.append(shape); group.append(member);
      }
      return group;
    }
    if (value.type === "bookmark") {
      const attrs = officeBookmarkAttributes(value.attrs), marker = dom.createElement("span");
      marker.id = officeBookmarkFragment(attrs.id); marker.className = "office-print-bookmark";
      marker.setAttribute("data-office-bookmark", attrs.id); marker.setAttribute("aria-label", `Lesezeichen: ${attrs.label}`);
      return marker;
    }
    if (value.type === "documentField") {
      const field = officeFieldAttributes(value.attrs, semantics.fieldMap), marker = dom.createElement("span");
      marker.className = "office-print-field"; marker.dataset.officeField = field.key;
      if (!field.field) marker.dataset.officeBroken = "true";
      marker.textContent = field.value; return marker;
    }
    if (value.type === "noteReference") {
      const note = officeNoteAttributes(value.attrs), number = note.kind === "footnote" ? ++footnote : ++endnote;
      const marker = dom.createElement("sup"); marker.className = `office-print-${note.kind}`;
      marker.textContent = String(number); marker.setAttribute("aria-label", `${note.kind === "footnote" ? "Fußnote" : "Endnote"} ${number}: ${note.text}`);
      return marker;
    }
    if (value.type === "citationReference") {
      const citation = officeCitationAttributes(value.attrs, semantics.sourceMap), marker = dom.createElement("span");
      marker.className = "office-print-citation"; marker.textContent = officeCitationLabel(citation.source, citation.locator);
      if (!citation.source) marker.dataset.officeBroken = "true";
      return marker;
    }
    if (value.type === "tableOfContents") {
      const section = dom.createElement("nav"); section.className = "office-print-toc"; section.setAttribute("aria-label", "Inhaltsverzeichnis");
      const heading = dom.createElement("h2"); heading.textContent = "Inhaltsverzeichnis"; section.append(heading);
      const list = dom.createElement("ol");
      for (const entry of semantics.headings.filter((item) => item.level <= value.attrs.maxLevel)) {
        const item = dom.createElement("li"); item.textContent = entry.text; item.dataset.officeHeadingLevel = String(entry.level); list.append(item);
      }
      section.append(list); return section;
    }
    if (value.type === "bibliography") {
      const section = dom.createElement("section"); section.className = "office-print-bibliography";
      const heading = dom.createElement("h2"); heading.textContent = "Literaturverzeichnis"; section.append(heading);
      const list = dom.createElement("ol");
      for (const source of semantics.sources) { const item = dom.createElement("li"); item.textContent = officeBibliographyLabel(source); list.append(item); }
      section.append(list); return section;
    }
    if (value.type === "equation") {
      const equation = officeEquationAttributes(value.attrs), figure = dom.createElement("figure"); figure.className = "office-print-equation";
      const code = dom.createElement("code"); code.textContent = equation.source; code.setAttribute("aria-label", equation.alt);
      const caption = dom.createElement("figcaption");
      const number = semantics.equations.find((item) => item.id === equation.id)?.number; caption.textContent = `Formel ${number}: ${equation.alt}`;
      figure.append(code, caption); return figure;
    }
    if (value.type === "referenceIndex") {
      const section = dom.createElement("section"); section.className = "office-print-reference-index";
      const heading = dom.createElement("h2"); heading.textContent = "Referenznavigator"; section.append(heading);
      const list = dom.createElement("ul");
      for (const reference of semantics.references) { const item = dom.createElement("li"); item.textContent = `${reference.kind}: ${reference.label}${reference.broken ? " (fehlt)" : ""}`; list.append(item); }
      section.append(list); return section;
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
        if (mark.type === "documentReference") {
          const attrs = officeDocumentReferenceAttributes(mark.attrs), wrapper = dom.createElement("span");
          const resolution = documentReferences.get(officeDocumentReferenceKey(attrs));
          wrapper.className = "office-print-document-reference";
          wrapper.dataset.officeDocumentReference = attrs.targetObjectId;
          wrapper.dataset.officeDocumentVersion = attrs.targetVersionId;
          wrapper.dataset.officeReferenceStatus = resolution?.status === "resolved" ? "resolved" : "unavailable";
          wrapper.setAttribute("aria-label", officeDocumentReferenceDescription(attrs, documentReferences));
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
      officeTableGrid(value);
      const table = dom.createElement("table");
      const attrs = officeTableAttributes(value.attrs);
      for (const [name, attribute] of Object.entries(officeTableDOMAttributes(attrs))) table.setAttribute(name, attribute);
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
        for (const [cellIndex, cell] of (row.content || []).entries()) {
          if (!["tableCell", "tableHeader"].includes(cell.type)) throw new Error("Invalid print cell");
          const element = render(cell, depth + 2);
          if (header) element.setAttribute("scope", "col");
          else if (cellIndex === 0 && cell.type === "tableHeader") element.setAttribute("scope", "row");
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
    if (["tableCell", "tableHeader"].includes(value.type)) {
      const attrs = officeTableCellAttributes(value.attrs);
      if (attrs.colspan > 1) element.setAttribute("colspan", String(attrs.colspan));
      if (attrs.rowspan > 1) element.setAttribute("rowspan", String(attrs.rowspan));
      for (const [name, attribute] of Object.entries(officeTableCellDOMAttributes(attrs))) {
        element.setAttribute(name, attribute);
      }
    }
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
  const classification = dom.createElement("p"); classification.className = "office-print-classification";
  classification.dataset.classification = informationClassification;
  classification.textContent = classifications[informationClassification];
  const heading = dom.createElement("h1"); heading.className = "office-print-title"; heading.textContent = title;
  let body = dom.createElement("div"); body.className = "office-print-content";
  article.append(classification, heading, body);
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
  for (const kind of ["footnote", "endnote"]) {
    const notes = semantics.notes.filter((note) => note.kind === kind);
    if (!notes.length) continue;
    const sectionElement = dom.createElement("section"); sectionElement.className = `office-print-${kind}s`;
    const titleElement = dom.createElement("h2"); titleElement.textContent = kind === "footnote" ? "Fußnoten" : "Endnoten"; sectionElement.append(titleElement);
    const list = dom.createElement("ol"); for (const note of notes) { const item = dom.createElement("li"); item.textContent = note.text; list.append(item); }
    sectionElement.append(list); article.append(sectionElement);
  }
  return article;
}
