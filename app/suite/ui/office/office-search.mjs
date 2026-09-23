// Already schema-validated native Office JSON. No DOM, storage, HTML or regex input.
const TEXT_BLOCKS = new Set(["paragraph", "heading", "codeBlock"]);
const LEAVES = new Set(["hardBreak", "horizontalRule", "image"]);
const WORD_CHARACTER = /[\p{L}\p{N}\p{M}\p{Pc}\u200c\u200d]/u;
const MAX_CHARACTERS = 100000;
const MAX_NODES = 10000;
const MAX_DEPTH = 32;
const MAX_BYTES = 400000;

export class OfficeSearchLimitError extends Error {
  constructor() {
    super("Der Ersatz ist ungültig oder überschreitet die Dokumentgrenzen.");
    this.name = "OfficeSearchLimitError";
  }
}

function characterCount(text) {
  let count = 0;
  for (const character of text) {
    const code = character.codePointAt(0);
    if ((code < 32 && code !== 9 && code !== 10) || (code >= 0xd800 && code <= 0xdfff)) {
      throw new OfficeSearchLimitError();
    }
    if (++count > MAX_CHARACTERS) throw new OfficeSearchLimitError();
  }
  return count;
}

function jsonBytes(value) {
  const serialized = JSON.stringify(value);
  let bytes = serialized.length;
  for (let index = 0; index < serialized.length; index += 1) {
    if (serialized.charCodeAt(index) >= 0x7f) bytes += 5;
  }
  return bytes;
}

function textBytes(text) {
  let bytes = 0;
  for (let index = 0; index < text.length; index += 1) {
    const unit = text.charCodeAt(index);
    bytes += unit >= 0x7f ? 6 : unit === 34 || unit === 92 || unit === 9 || unit === 10 ? 2 : 1;
  }
  return bytes;
}

function documentBounds(document) {
  let nodes = 0;
  let characters = 0;
  const visit = (node, depth) => {
    if (!node || typeof node !== "object" || ++nodes > MAX_NODES || depth > MAX_DEPTH) {
      throw new OfficeSearchLimitError();
    }
    if (node.type === "text") {
      if (typeof node.text !== "string" || !node.text) throw new OfficeSearchLimitError();
      characters += characterCount(node.text);
      if (characters > MAX_CHARACTERS) throw new OfficeSearchLimitError();
    }
    for (const child of node.content || []) visit(child, depth + 1);
  };
  if (document?.type !== "doc") throw new OfficeSearchLimitError();
  visit(document, 0);
  // Python canonical_json uses compact JSON with ensure_ascii=True. Key ordering
  // does not affect byte length; each non-ASCII UTF-16 unit becomes six bytes.
  const bytes = jsonBytes(document);
  if (bytes > MAX_BYTES) throw new OfficeSearchLimitError();
  return { characters, bytes, nodes };
}

function projectRuns(document) {
  const runs = [];
  const walk = (node, position) => {
    if (node.type === "text") return node.text.length;
    if (LEAVES.has(node.type)) return 1;
    let next = position + (node.type === "doc" ? 0 : 1);
    if (TEXT_BLOCKS.has(node.type)) {
      let run = null;
      const finish = () => {
        if (!run) return;
        run.text = run.parts.map((part) => part.node.text).join("");
        runs.push(run);
        run = null;
      };
      (node.content || []).forEach((child, index) => {
        if (child.type === "text") {
          if (!run) run = { block: node, blockPosition: position, first: index, last: index, from: next, to: next, parts: [] };
          run.parts.push({ node: child, from: next, to: next + child.text.length });
          run.to = next + child.text.length;
          run.last = index;
          next = run.to;
        } else {
          finish();
          next += walk(child, next);
        }
      });
      finish();
    } else {
      for (const child of node.content || []) next += walk(child, next);
    }
    return next - position + (node.type === "doc" ? 0 : 1);
  };
  walk(document, 0);
  return runs;
}

function previousCharacter(text, offset) {
  if (!offset) return "";
  const unit = text.charCodeAt(offset - 1);
  return text.slice(offset - (unit >= 0xdc00 && unit <= 0xdfff ? 2 : 1), offset);
}

function nextCharacter(text, offset) {
  return offset === text.length ? "" : String.fromCodePoint(text.codePointAt(offset));
}

/** Non-overlapping literal matches, using original ProseMirror UTF-16 positions.
 * Case-insensitive matching uses Unicode simple folding (/iu), without locale,
 * accent normalization or expansions: ß=ẞ, but ß!=ss and İ!=i.
 * Whole words use Unicode letters/numbers/marks/connectors and join controls.
 */
export function findDocumentMatches(document, query, { caseSensitive = false, wholeWord = false } = {}) {
  documentBounds(document);
  if (typeof query !== "string") throw new TypeError("A literal search string is required");
  if (!query) return [];
  characterCount(query);
  const expression = new RegExp(query.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), caseSensitive ? "gu" : "giu");
  const matches = [];
  for (const run of projectRuns(document)) {
    expression.lastIndex = 0;
    let match;
    while ((match = expression.exec(run.text)) !== null) {
      const end = match.index + match[0].length;
      if (wholeWord && (WORD_CHARACTER.test(previousCharacter(run.text, match.index)) ||
          WORD_CHARACTER.test(nextCharacter(run.text, end)))) continue;
      matches.push({ from: run.from + match.index, to: run.from + end });
    }
  }
  return matches;
}

function isCharacterBoundary(text, offset) {
  const before = text.charCodeAt(offset - 1);
  const after = text.charCodeAt(offset);
  return !(before >= 0xd800 && before <= 0xdbff && after >= 0xdc00 && after <= 0xdfff);
}

function markKey(node) {
  // Attribute differences are formatting boundaries, even for the same mark type.
  return JSON.stringify((node.marks || []).map((mark) => [mark.type,
    Object.entries(mark.attrs || {}).sort(([left], [right]) => left.localeCompare(right, "en"))])
    .sort(([left], [right]) => left.localeCompare(right, "en")));
}

// A forward cursor visits each old segment once. Text chunks are joined only at
// the end, avoiding repeated string growth or one transaction per occurrence.
function replaceRun(run, matches, replacement) {
  const pieces = [];
  let partIndex = 0;
  let position = run.from;
  let changedCount = 0;
  const append = (prototype, text) => {
    if (!text) return;
    const key = markKey(prototype);
    const last = pieces[pieces.length - 1];
    if (last && last.key === key) last.chunks.push(text);
    else pieces.push({ prototype, key, chunks: [text] });
  };
  const advance = (end, copy) => {
    while (position < end) {
      const part = run.parts[partIndex];
      const next = Math.min(end, part.to);
      if (copy) append(part.node, part.node.text.slice(position - part.from, next - part.from));
      position = next;
      if (position === part.to) partIndex += 1;
    }
  };
  for (const match of matches) {
    advance(match.from, true);
    if (run.text.slice(match.from - run.from, match.to - run.from) === replacement) {
      // A literal no-op must not flatten mixed formatting across the match.
      advance(match.to, true);
    } else {
      append(run.parts[partIndex].node, replacement);
      advance(match.to, false);
      changedCount += 1;
    }
  }
  advance(run.to, true);
  return { changedCount, pieces };
}

/** Replace all matches, or exactly currentIndex. New text inherits the first
 * matched character's marks; untouched text/structure keep their formatting.
 * Returns the original document for a literal no-op. Never mutates its inputs.
 * Limits include Python code points and ASCII-escaped canonical JSON bytes.
 */
export function replaceDocumentMatches(document, matches, replacement, { currentIndex } = {}) {
  const original = documentBounds(document);
  if (typeof replacement !== "string" || !Array.isArray(matches)) throw new TypeError("Invalid replacement input");
  const replacementCharacters = characterCount(replacement);
  if (currentIndex !== undefined && (!Number.isInteger(currentIndex) || currentIndex < 0 || currentIndex >= matches.length)) {
    throw new RangeError("Invalid current match");
  }
  const selected = currentIndex === undefined ? matches : [matches[currentIndex]];
  if (!selected.length) return { document, changedCount: 0, noOp: true };
  const runs = projectRuns(document);
  const grouped = new Map();
  let runIndex = 0;
  let previousEnd = -1;
  let removedCharacters = 0;
  for (const match of selected) {
    if (!match || !Number.isInteger(match.from) || !Number.isInteger(match.to) ||
        match.from < previousEnd || match.to <= match.from) throw new RangeError("Invalid search match");
    while (runIndex < runs.length && match.from >= runs[runIndex].to) runIndex += 1;
    const run = runs[runIndex];
    if (!run || match.from < run.from || match.to > run.to ||
        !isCharacterBoundary(run.text, match.from - run.from) || !isCharacterBoundary(run.text, match.to - run.from)) {
      throw new RangeError("Search match crosses a text boundary");
    }
    const group = grouped.get(run) || [];
    group.push(match);
    grouped.set(run, group);
    removedCharacters += characterCount(run.text.slice(match.from - run.from, match.to - run.from));
    previousEnd = match.to;
  }
  if (original.characters - removedCharacters + replacementCharacters * selected.length > MAX_CHARACTERS) {
    throw new OfficeSearchLimitError();
  }
  const blocks = new Map();
  let changedCount = 0;
  for (const [run, group] of grouped) {
    const result = replaceRun(run, group, replacement);
    changedCount += result.changedCount;
    if (!result.changedCount) continue;
    if (!blocks.has(run.blockPosition)) blocks.set(run.blockPosition, { node: run.block, replacements: new Map() });
    blocks.get(run.blockPosition).replacements.set(run.first, { last: run.last, pieces: result.pieces });
  }
  if (!changedCount) return { document, changedCount: 0, noOp: true };
  // Exact prospective JSON/node bounds before joining replacement chunks or
  // constructing output nodes. Plans retain references to the one literal
  // replacement string, even for 100,000 occurrences.
  let prospectiveBytes = original.bytes;
  let prospectiveNodes = original.nodes;
  for (const { node, replacements } of blocks.values()) {
    let children = 0;
    let childBytes = 0;
    for (let index = 0; index < node.content.length; index += 1) {
      const plan = replacements.get(index);
      if (plan) {
        prospectiveNodes += plan.pieces.length - (plan.last - index + 1);
        children += plan.pieces.length;
        for (const piece of plan.pieces) {
          childBytes += jsonBytes({ ...piece.prototype, text: "" });
          for (const chunk of piece.chunks) childBytes += textBytes(chunk);
        }
        index = plan.last;
      } else {
        children += 1;
        childBytes += jsonBytes(node.content[index]);
      }
    }
    prospectiveBytes += jsonBytes({ ...node, content: [] }) + childBytes + Math.max(0, children - 1) - jsonBytes(node);
  }
  if (prospectiveBytes > MAX_BYTES || prospectiveNodes > MAX_NODES) throw new OfficeSearchLimitError();
  for (const { replacements } of blocks.values()) {
    for (const plan of replacements.values()) {
      plan.content = plan.pieces.map((piece) => ({ ...piece.prototype, text: piece.chunks.join("") }));
    }
  }
  const rebuild = (node, position) => {
    if (node.type === "text") return { node, size: node.text.length };
    if (LEAVES.has(node.type)) return { node, size: 1 };
    let next = position + (node.type === "doc" ? 0 : 1);
    let changed = false;
    const content = [];
    const replacements = TEXT_BLOCKS.has(node.type) ? blocks.get(position)?.replacements : null;
    const children = node.content || [];
    for (let index = 0; index < children.length; index += 1) {
      const replacementRun = replacements?.get(index);
      if (replacementRun) {
        content.push(...replacementRun.content);
        for (; index <= replacementRun.last; index += 1) next += children[index].text.length;
        index -= 1;
        changed = true;
      } else {
        const child = rebuild(children[index], next);
        next += child.size;
        changed ||= child.node !== children[index];
        content.push(child.node);
      }
    }
    return { node: changed ? { ...node, content } : node, size: next - position + (node.type === "doc" ? 0 : 1) };
  };
  const result = rebuild(document, 0).node;
  documentBounds(result);
  return { document: result, changedCount, noOp: false };
}
