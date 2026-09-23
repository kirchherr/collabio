import { officeImageCrop, officeImageFigure } from "./office-images.mjs";

export function installImageCropControls(getAction, isCurrent) {
  const $ = (id) => document.getElementById(id), names = ["x", "y", "width", "height"];
  const stage = $("image-crop-stage"), rectangle = $("image-crop-rectangle");
  let drag = null;
  const current = () => { const owner = getAction(); return owner?.attrs && !owner.busy && isCurrent() ? owner : null; };
  const read = (owner) => officeImageCrop({ ...owner.attrs, crop: Object.fromEntries(names.map((name) => [name, $(`image-crop-${name}`).valueAsNumber])) });
  const preview = (owner) => {
    if (!owner?.url) return;
    const width = Number($("image-width").value), height = Number($("image-height").value);
    if (!Number.isInteger(width) || !Number.isInteger(height) || width < 1 || height < 1 || width > 1600 || height > 1600) return;
    $("image-preview").replaceChildren(officeImageFigure({ ...owner.attrs, crop: owner.crop, width, height }, owner.url));
  };
  const paint = (owner, resize = false) => {
    const crop = owner.crop;
    for (const name of names) { $(`image-crop-${name}`).value = crop[name]; $(`image-crop-${name}`).setCustomValidity(""); }
    Object.assign(rectangle.style, { left: `${crop.x / owner.attrs.pixelWidth * 100}%`, top: `${crop.y / owner.attrs.pixelHeight * 100}%`,
      width: `${crop.width / owner.attrs.pixelWidth * 100}%`, height: `${crop.height / owner.attrs.pixelHeight * 100}%` });
    if (resize && $("image-lock").checked) {
      let width = Number($("image-width").value);
      if (Number.isInteger(width) && width > 0 && width <= 1600) {
        let height = Math.max(1, Math.round(width * crop.height / crop.width));
        if (height > 1600) { width = Math.max(1, Math.round(width * 1600 / height)); height = 1600; }
        $("image-width").value = width; $("image-height").value = height;
      }
    }
    $("image-crop-status").textContent = `Ausschnitt: ${crop.width} × ${crop.height} Pixel, links ${crop.x}, oben ${crop.y}.`;
    preview(owner);
  };
  const fill = (owner) => {
    drag = null; owner.crop = officeImageCrop(owner.attrs);
    $("image-crop-section").hidden = false;
    for (const name of names) $(`image-crop-${name}`).max = name === "x" ? owner.attrs.pixelWidth - 1 : name === "y" ? owner.attrs.pixelHeight - 1 : owner.attrs[name === "width" ? "pixelWidth" : "pixelHeight"];
    paint(owner);
  };
  const source = (owner) => {
    $("image-crop-source").src = owner.url;
    stage.style.aspectRatio = `${owner.attrs.pixelWidth} / ${owner.attrs.pixelHeight}`;
    stage.style.maxWidth = `min(100%, ${200 * owner.attrs.pixelWidth / owner.attrs.pixelHeight}px)`;
    if (!owner.crop) fill(owner); else paint(owner);
  };
  const value = () => {
    const owner = getAction(), crop = read(owner);
    return crop.x === 0 && crop.y === 0 && crop.width === owner.attrs.pixelWidth && crop.height === owner.attrs.pixelHeight ? null : crop;
  };
  for (const name of names) $(`image-crop-${name}`).addEventListener("input", () => {
    const owner = current(); if (!owner) return;
    for (const key of names) $(`image-crop-${key}`).setCustomValidity("");
    try { owner.crop = read(owner); paint(owner, true); }
    catch { $(`image-crop-${name}`).setCustomValidity("Der Ausschnitt muss vollständig im Bild liegen."); $("image-crop-status").textContent = "Gültige ganze Pixelwerte innerhalb des Bildes eingeben."; }
  });
  $("image-crop-reset").addEventListener("click", () => {
    const owner = current(); if (!owner) return;
    owner.crop = officeImageCrop({ ...owner.attrs, crop: null }); paint(owner, true);
  });
  const point = (event, owner) => {
    const bounds = stage.getBoundingClientRect();
    return { x: Math.max(0, Math.min(owner.attrs.pixelWidth, Math.round((event.clientX - bounds.left) / bounds.width * owner.attrs.pixelWidth))),
      y: Math.max(0, Math.min(owner.attrs.pixelHeight, Math.round((event.clientY - bounds.top) / bounds.height * owner.attrs.pixelHeight))) };
  };
  stage.addEventListener("pointerdown", (event) => {
    const owner = current(); if (!owner || !owner.url || event.button !== 0) return;
    drag = { owner, id: event.pointerId, start: point(event, owner), previous: owner.crop,
      width: $("image-width").value, height: $("image-height").value };
    stage.setPointerCapture(event.pointerId); stage.focus(); event.preventDefault();
  });
  stage.addEventListener("pointermove", (event) => {
    if (!drag || drag.id !== event.pointerId || current() !== drag.owner) return;
    const { owner, start } = drag, end = point(event, owner);
    if (start.x === end.x || start.y === end.y) return;
    owner.crop = { x: Math.min(start.x, end.x), y: Math.min(start.y, end.y), width: Math.abs(end.x - start.x), height: Math.abs(end.y - start.y) };
    paint(owner, true);
  });
  stage.addEventListener("pointerup", (event) => { if (drag?.id === event.pointerId) { if (stage.hasPointerCapture(event.pointerId)) stage.releasePointerCapture(event.pointerId); drag = null; } });
  stage.addEventListener("lostpointercapture", () => { drag = null; });
  stage.addEventListener("pointercancel", () => {
    if (drag && current() === drag.owner) {
      drag.owner.crop = drag.previous; $("image-width").value = drag.width; $("image-height").value = drag.height; paint(drag.owner);
    }
    drag = null;
  });
  stage.addEventListener("keydown", (event) => {
    const owner = current(), directions = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] };
    if (!owner || !directions[event.key] || event.ctrlKey || event.metaKey || event.altKey) return;
    event.preventDefault(); const [dx, dy] = directions[event.key], step = event.shiftKey ? 10 : 1;
    owner.crop = { ...owner.crop, x: Math.max(0, Math.min(owner.attrs.pixelWidth - owner.crop.width, owner.crop.x + dx * step)),
      y: Math.max(0, Math.min(owner.attrs.pixelHeight - owner.crop.height, owner.crop.y + dy * step)) }; paint(owner);
  });
  return { fill, source, value, preview,
    close() { drag = null; $("image-crop-section").hidden = true; $("image-crop-section").open = false; $("image-crop-source").removeAttribute("src");
      for (const name of names) $(`image-crop-${name}`).setCustomValidity(""); },
  };
}
