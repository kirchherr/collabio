const figureIdentifier = /^figure-[a-f0-9]{24}$/u;

export function officeFigureId(value) {
  if (typeof value !== "string" || !figureIdentifier.test(value)) throw new TypeError("Invalid Office figure ID");
  return value;
}

export function officeFigureFragment(id) {
  return `office-figure-${officeFigureId(id)}`;
}

export function officeFigureInventory(document) {
  let nodes = 0;
  const entries = [], ids = new Set();
  const walk = (value, depth = 0) => {
    if (!value || typeof value !== "object" || ++nodes > 10000 || depth > 32) throw new TypeError("Invalid Office figure document");
    if (value.type === "image" && value.attrs?.figureId != null) {
      const id = officeFigureId(value.attrs.figureId), caption = value.attrs.caption;
      if (ids.has(id) || typeof caption !== "string" || !caption.trim()) throw new TypeError("Invalid Office figure");
      ids.add(id);
      entries.push({ id, kind: "figure", number: entries.length + 1, label: `Abbildung ${entries.length + 1}: ${caption}` });
    }
    for (const child of value.content || []) walk(child, depth + 1);
  };
  walk(document);
  return entries;
}

export function officeFigureCaption(attrs, number = null) {
  const caption = attrs?.caption;
  if (typeof caption !== "string") throw new TypeError("Invalid Office figure caption");
  if (attrs.figureId == null) return caption;
  officeFigureId(attrs.figureId);
  if (!caption.trim() || !Number.isInteger(number) || number < 1 || number > 40) throw new TypeError("Invalid Office figure number");
  return `Abbildung ${number}: ${caption}`;
}
