// Native, already validated document JSON only. No DOM, HTML, network or storage.
import { officeParagraphDescription } from "./office-paragraph.mjs";
import { officeCharacterDescription } from "./office-character.mjs";
import { officeStyleComparisonDocument, officeStyleDescription } from "./office-styles.mjs";

const MAX_LCS_CELLS = 262144;
const markLabels = {
  bold: "Fett", italic: "Kursiv", strike: "Durchgestrichen", code: "Code", underline: "Unterstrichen",
};
const nodeLabels = {
  doc: "Dokument", paragraph: "Absatz", heading: "Überschrift", text: "Text", hardBreak: "Zeilenumbruch",
  bulletList: "Aufzählung", orderedList: "Nummerierte Liste", listItem: "Listeneintrag", blockquote: "Zitat",
  codeBlock: "Codeblock", horizontalRule: "Trennlinie", table: "Tabelle", tableRow: "Tabellenzeile",
  tableCell: "Tabellenzelle", tableHeader: "Tabellenkopf",
};

function canonical(value, key = "") {
  if (Array.isArray(value)) {
    const entries = value.map((entry) => canonical(entry));
    // ProseMirror marks are a set; JSON property and mark order are not edits.
    if (key === "marks") entries.sort();
    return `[${entries.join(",")}]`;
  }
  if (value !== null && typeof value === "object") {
    return `{${Object.keys(value).sort().map((name) => `${JSON.stringify(name)}:${canonical(value[name], name)}`).join(",")}}`;
  }
  return JSON.stringify(value);
}

// Unique exact matches supply monotonic anchors when a full LCS would be large.
// The longest increasing subsequence uses O(n log n) work and linear memory.
function uniqueAnchors(left, right, leftStart, leftEnd, rightStart, rightEnd) {
  const leftPositions = new Map();
  const rightPositions = new Map();
  for (let index = leftStart; index < leftEnd; index += 1) {
    leftPositions.set(left[index], leftPositions.has(left[index]) ? -1 : index);
  }
  for (let index = rightStart; index < rightEnd; index += 1) {
    rightPositions.set(right[index], rightPositions.has(right[index]) ? -1 : index);
  }
  const candidates = [];
  for (let index = leftStart; index < leftEnd; index += 1) {
    const other = rightPositions.get(left[index]);
    if (leftPositions.get(left[index]) === index && other !== undefined && other !== -1) {
      candidates.push({ left: index, right: other });
    }
  }
  const tails = [];
  const previous = new Int32Array(candidates.length).fill(-1);
  for (let index = 0; index < candidates.length; index += 1) {
    let low = 0;
    let high = tails.length;
    while (low < high) {
      const middle = (low + high) >>> 1;
      if (candidates[tails[middle]].right < candidates[index].right) low = middle + 1;
      else high = middle;
    }
    if (low > 0) previous[index] = tails[low - 1];
    tails[low] = index;
  }
  const anchors = [];
  let index = tails.length ? tails[tails.length - 1] : -1;
  while (index !== -1) {
    anchors.push(candidates[index]);
    index = previous[index];
  }
  return anchors.reverse();
}

export function compareOfficeDocuments(leftDoc, rightDoc) {
  const blocks = (document) => {
    const expanded = officeStyleComparisonDocument(document);
    return [...(expanded.content || []), ...(expanded.attrs?.styles?.length ? [{ type: "styleCatalog", styles: expanded.attrs.styles }] : [])];
  };
  const before = blocks(leftDoc);
  const after = blocks(rightDoc);
  const identities = new Map();
  const identity = (block) => {
    const key = canonical(block);
    if (!identities.has(key)) identities.set(key, identities.size);
    return identities.get(key);
  };
  // Intern once, so the bounded matrix compares integers instead of long text.
  const left = before.map(identity);
  const right = after.map(identity);
  const rows = [];
  const counts = { equal: 0, added: 0, removed: 0, changed: 0 };
  let remainingCells = MAX_LCS_CELLS;
  let simplified = false;

  const add = (leftIndex, rightIndex) => {
    const kind = leftIndex === null ? "added" : rightIndex === null ? "removed" :
      left[leftIndex] === right[rightIndex] ? "equal" : "changed";
    rows.push({ kind, before: leftIndex === null ? null : before[leftIndex], after: rightIndex === null ? null : after[rightIndex] });
    counts[kind] += 1;
  };

  const completeGap = (leftStart, leftEnd, rightStart, rightEnd) => {
    let leftIndex = leftStart;
    let rightIndex = rightStart;
    while (leftIndex < leftEnd && rightIndex < rightEnd) add(leftIndex++, rightIndex++);
    while (leftIndex < leftEnd) add(leftIndex++, null);
    while (rightIndex < rightEnd) add(null, rightIndex++);
  };

  const section = (leftStart, leftEnd, rightStart, rightEnd, allowAnchors = true) => {
    while (leftStart < leftEnd && rightStart < rightEnd && left[leftStart] === right[rightStart]) {
      add(leftStart++, rightStart++);
    }
    let suffix = 0;
    while (leftStart < leftEnd && rightStart < rightEnd && left[leftEnd - 1] === right[rightEnd - 1]) {
      leftEnd -= 1;
      rightEnd -= 1;
      suffix += 1;
    }
    const leftLength = leftEnd - leftStart;
    const rightLength = rightEnd - rightStart;
    const cells = (leftLength + 1) * (rightLength + 1);
    if (!leftLength || !rightLength) {
      completeGap(leftStart, leftEnd, rightStart, rightEnd);
    } else if (cells <= remainingCells) {
      remainingCells -= cells;
      const width = rightLength + 1;
      const matrix = new Uint16Array(cells);
      for (let row = leftLength - 1; row >= 0; row -= 1) {
        for (let column = rightLength - 1; column >= 0; column -= 1) {
          const offset = row * width + column;
          matrix[offset] = left[leftStart + row] === right[rightStart + column] ?
            1 + matrix[offset + width + 1] : Math.max(matrix[offset + width], matrix[offset + 1]);
        }
      }
      let row = 0;
      let column = 0;
      let previousLeft = leftStart;
      let previousRight = rightStart;
      while (row < leftLength && column < rightLength) {
        if (left[leftStart + row] === right[rightStart + column]) {
          completeGap(previousLeft, leftStart + row, previousRight, rightStart + column);
          add(leftStart + row, rightStart + column);
          previousLeft = leftStart + ++row;
          previousRight = rightStart + ++column;
        } else if (matrix[(row + 1) * width + column] >= matrix[row * width + column + 1]) {
          row += 1;
        } else {
          column += 1;
        }
      }
      completeGap(previousLeft, leftEnd, previousRight, rightEnd);
    } else {
      simplified = true;
      const anchors = allowAnchors ? uniqueAnchors(left, right, leftStart, leftEnd, rightStart, rightEnd) : [];
      let previousLeft = leftStart;
      let previousRight = rightStart;
      for (const anchor of anchors) {
        section(previousLeft, anchor.left, previousRight, anchor.right, false);
        add(anchor.left, anchor.right);
        previousLeft = anchor.left + 1;
        previousRight = anchor.right + 1;
      }
      if (anchors.length) section(previousLeft, leftEnd, previousRight, rightEnd, false);
      else completeGap(leftStart, leftEnd, rightStart, rightEnd);
    }
    for (let index = 0; index < suffix; index += 1) add(leftEnd + index, rightEnd + index);
  };

  section(0, before.length, 0, after.length);
  return { rows, counts, simplified };
}

function markedText(node) {
  const marks = [...(node.marks || [])].sort((left, right) => left.type.localeCompare(right.type, "en"));
  let text = node.text;
  for (let index = marks.length - 1; index >= 0; index -= 1) {
    const label = marks[index].type === "textStyle" ? officeCharacterDescription(marks[index].attrs) : markLabels[marks[index].type];
    text = `⟦${label}⟧${text}⟦/${label}⟧`;
  }
  return text;
}

function blockText(block, nested = false) {
  const children = block.content || [];
  switch (block.type) {
    case "styleCatalog": return block.styles.map(officeStyleDescription).join("\n");
    case "text": return markedText(block);
    case "hardBreak": return "↵\n";
    case "horizontalRule": return "────────";
    case "image": return `Bild · ${block.attrs.width} × ${block.attrs.height} · ${block.attrs.align}\n${block.attrs.crop ? `Zuschnitt: ${block.attrs.crop.x}, ${block.attrs.crop.y} · ${block.attrs.crop.width} × ${block.attrs.crop.height}` : "Ganzes Bild"}\n${block.attrs.wrap ? `Textumfluss: ${block.attrs.wrap.side === "left" ? "Bild links" : "Bild rechts"} · Abstand ${block.attrs.wrap.gap} px` : "Ohne Textumfluss"}\n${block.attrs.decorative ? "Dekorativ" : block.attrs.alt}\n${block.attrs.caption}\n${block.attrs.contentHash}`;
    case "paragraph": {
      const text = children.map((child) => blockText(child)).join("") || "(Leerer Absatz)";
      const formatting = nested ? [...officeParagraphDescription(block.attrs), block.attrs?.styleDescription].filter(Boolean) : [];
      return formatting.length ? `⟦${formatting.join(" · ")}⟧ ${text}` : text;
    }
    case "heading": {
      const text = children.map((child) => blockText(child)).join("") || "(Leere Überschrift)";
      const formatting = nested ? [...officeParagraphDescription(block.attrs), block.attrs?.styleDescription].filter(Boolean) : [];
      const detail = formatting.length ? ` · ${formatting.join(" · ")}` : "";
      return nested ? `Überschrift ${block.attrs.level}${detail}: ${text}` : text;
    }
    case "codeBlock": {
      const text = children.map((child) => blockText(child)).join("") || "(Leerer Codeblock)";
      return nested ? `Codeblock:\n${text}` : text;
    }
    case "blockquote": return children.map((child) => blockText(child, true)).join("\n\n").split("\n").map((line) => `│ ${line}`).join("\n");
    case "bulletList":
    case "orderedList": return children.map((child, index) => {
      const marker = block.type === "bulletList" ? "• " : `${(block.attrs?.start ?? 1) + index}. `;
      return blockText(child, true).split("\n").map((line, lineIndex) => `${lineIndex ? " ".repeat(marker.length) : marker}${line}`).join("\n");
    }).join("\n");
    case "table": return children.map((row, index) => `Zeile ${index + 1}: ${blockText(row, true)}`).join("\n");
    case "tableRow": return children.map((cell, index) => {
      const label = cell.type === "tableHeader" ? "Kopfzelle" : "Zelle";
      return `${label} ${index + 1}: ${blockText(cell, true)}`;
    }).join(" │ ");
    case "doc":
    case "listItem":
    case "tableCell":
    case "tableHeader": return children.map((child) => blockText(child, true)).join("\n\n");
    default: return "";
  }
}

export function describeOfficeBlock(block) {
  let label = block.type === "image" ? "Bild" : block.type === "styleCatalog" ? "Formatvorlagen" : nodeLabels[block.type];
  if (block.type === "heading") label += ` Ebene ${block.attrs.level}`;
  if (["paragraph", "heading"].includes(block.type)) {
    const formatting = [...officeParagraphDescription(block.attrs), block.attrs?.styleDescription].filter(Boolean);
    if (formatting.length) label += ` · ${formatting.join(" · ")}`;
  }
  if (block.type === "orderedList") label += ` · Beginn ${(block.attrs?.start ?? 1)}`;
  if (block.type === "table") {
    const rows = block.content.length;
    const columns = block.content[0].content.length;
    label += ` · ${rows} ${rows === 1 ? "Zeile" : "Zeilen"} × ${columns} ${columns === 1 ? "Spalte" : "Spalten"}`;
  }
  return { label, text: blockText(block) };
}
