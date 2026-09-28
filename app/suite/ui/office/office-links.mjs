export const OFFICE_LINK_MAX = 2048;

const forbidden = /[\u0000-\u0020\u007f-\u009f<>"'\\]/u;
const mail = /^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]{1,64}@[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?$/u;

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
