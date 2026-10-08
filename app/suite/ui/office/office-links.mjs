export const OFFICE_LINK_MAX = 2048;

const forbidden = /[\u0000-\u0020\u007f-\u009f<>"'\\]/u;
const mail = /^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]{1,64}@[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?$/u;
const tokenPattern = /[^\s\u0000-\u001f\u007f-\u009f<>"'\\]+/gu;
const leadingPunctuation = new Set(["(", "[", "{"]);
const trailingPunctuation = new Set([".", ",", ";", ":", "!", "?"]);

export function officeLinkHref(value) {
  if (typeof value !== "string" || !value || value.length > OFFICE_LINK_MAX || forbidden.test(value)) {
    throw new TypeError("Invalid Office link");
  }
  if (value.startsWith("mailto:")) {
    const address = value.slice(7);
    if (!mail.test(address) || address.includes("..")) throw new TypeError("Invalid Office link");
    return `mailto:${address}`;
  }
  if (!value.startsWith("https://")) throw new TypeError("Invalid Office link");
  let parsed;
  try { parsed = new URL(value); } catch { throw new TypeError("Invalid Office link"); }
  if (parsed.protocol !== "https:" || !parsed.hostname || parsed.username || parsed.password || parsed.href.length > OFFICE_LINK_MAX) {
    throw new TypeError("Invalid Office link");
  }
  return parsed.href;
}

export function officeLinkDOMAttributes(value, { printable = false } = {}) {
  const href = officeLinkHref(value);
  return { href, rel: "noopener noreferrer", ...(printable ? {} : { target: "_blank", "data-office-link": "true" }) };
}

export function officeLinkDescription(value) {
  const href = officeLinkHref(value);
  return href.startsWith("mailto:") ? `E-Mail: ${href.slice(7)}` : `Link: ${href}`;
}

function automaticCandidate(token) {
  let from = 0, to = token.length;
  while (from < to && leadingPunctuation.has(token[from])) from += 1;
  while (to > from && trailingPunctuation.has(token[to - 1])) to -= 1;
  for (const [open, close] of [["(", ")"], ["[", "]"], ["{", "}"]]) {
    while (to > from && token[to - 1] === close &&
        [...token.slice(from, to)].filter((value) => value === close).length >
        [...token.slice(from, to)].filter((value) => value === open).length) to -= 1;
  }
  const text = token.slice(from, to);
  let href = text;
  if (!text.startsWith("https://") && !text.startsWith("mailto:")) href = `mailto:${text}`;
  try { return { from, to, href: officeLinkHref(href) }; } catch { return null; }
}

export function officeAutomaticLinks(text) {
  if (typeof text !== "string") throw new TypeError("Invalid Office link text");
  const links = [];
  for (const match of text.matchAll(tokenPattern)) {
    const candidate = automaticCandidate(match[0]);
    if (candidate) links.push({ from: match.index + candidate.from, to: match.index + candidate.to, href: candidate.href });
  }
  return links;
}

export function officeAutomaticLinkContent(text) {
  const links = officeAutomaticLinks(text), content = [];
  let position = 0;
  const append = (value, href = null) => {
    if (value) content.push({ type: "text", text: value,
      ...(href ? { marks: [{ type: "link", attrs: { href } }] } : {}) });
  };
  for (const link of links) {
    append(text.slice(position, link.from));
    append(text.slice(link.from, link.to), link.href);
    position = link.to;
  }
  append(text.slice(position));
  return content;
}
