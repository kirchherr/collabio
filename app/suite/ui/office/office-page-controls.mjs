import { OFFICE_RUNNING_DEFAULT, officeRunningSettings, officeRunningNumber } from "./office-running.mjs";
import { closeHistory } from "@tiptap/pm/history";
import { OFFICE_PAGE_DEFAULT, OFFICE_PAGE_SIDES, officePageSettings, officePageDescription, officePagePreview } from "./office-page.mjs";

export function installOfficePageControls({ state, allowed, actionCurrent, sessionCurrent, validate, focus, updateEditor, notice }) {
  const $ = (id) => document.getElementById(id);
  let action = null;
  const close = (restoreFocus = false) => {
    const previous = action; action = null;
    $("page-dialog").close(); $("page-form").reset(); $("page-status").textContent = "";
    $("page-description").textContent = ""; $("page-preview").removeAttribute("style");
    $("page-running-details").open = false; $("page-running-preview").textContent = "";
    $("page-running-preview-following").textContent = "";
    if (restoreFocus && previous?.editor === state.editor && sessionCurrent(previous.session)) focus();
  };
  const read = () => officePageSettings({ paper: $("page-paper").value, orientation: $("page-orientation").value,
    margins: Object.fromEntries(OFFICE_PAGE_SIDES.map((side) => [side, $(`page-${side}`).valueAsNumber])) });
  const readRunning = (page) => officeRunningSettings({ header: $("page-header").value, footer: $("page-footer").value,
    numbering: $("page-numbering").value, ...($("page-first-different").checked ? { firstPage: {
      header: $("page-first-header").value, footer: $("page-first-footer").value,
      showNumber: $("page-first-number").checked,
    } } : {}) }, page);
  const previewText = (profile, number) => [profile.header || "(keine Kopfzeile)", "— Beispiel für Dokumentinhalt —",
    profile.footer || "(keine Fußzeile)", number].filter(Boolean).join("\n");
  const preview = () => {
    if (!actionCurrent(action)) { close(); return; }
    try {
      const different = $("page-first-different").checked;
      if (!different) {
        $("page-first-header").value = $("page-header").value;
        $("page-first-footer").value = $("page-footer").value;
        $("page-first-number").checked = $("page-numbering").value !== "none";
      } else if ($("page-numbering").value === "none") $("page-first-number").checked = false;
      $("page-first-header").disabled = !different; $("page-first-footer").disabled = !different;
      $("page-first-number").disabled = !different || $("page-numbering").value === "none";
      const page = read(), running = readRunning(page);
      const first = running.firstPage || running;
      $("page-running-preview").textContent = previewText(first, officeRunningNumber(running, 1, 3, true));
      $("page-running-preview-following").textContent = previewText(running, officeRunningNumber(running, 2, 3));
      officePagePreview($("page-preview"), page);
      $("page-description").textContent = officePageDescription(page);
      $("page-status").textContent = ""; $("page-apply").disabled = false;
    } catch {
      $("page-description").textContent = ""; $("page-apply").disabled = true;
      $("page-status").textContent = "Ränder: ganze Zahlen von 5 bis 50 mm; mit Kopf-/Fußzeile oder Seitenzahl mindestens 16 mm am jeweiligen Rand. Texte: höchstens 64 Zeichen ohne Zeilenumbrüche.";
    }
  };
  const fill = (page) => {
    $("page-paper").value = page.paper; $("page-orientation").value = page.orientation;
    for (const side of OFFICE_PAGE_SIDES) $(`page-${side}`).value = String(page.margins[side]);
    preview();
  };
  const update = () => {
    if (action && !actionCurrent(action)) close();
    $("page-options").disabled = !allowed();
    const value = state.editor?.state.doc.attrs.page;
    const sheet = $("document-page");
    sheet.classList.toggle("has-page-settings", value != null);
    if (value != null) officePagePreview(sheet, value);
    else sheet.removeAttribute("style");
    $("page-options").title = officePageDescription(value ?? undefined);
  };
  $("page-options").addEventListener("mousedown", (event) => { if (event.button === 0) event.preventDefault(); });
  $("page-options").addEventListener("click", () => {
    if (!allowed()) return;
    close();
    const editor = state.editor;
    action = { editor, session: state.session, context: state.context, revision: state.session.revision,
      document: editor.state.doc, selection: editor.state.selection, storedMarks: editor.state.storedMarks };
    const running = officeRunningSettings(editor.state.doc.attrs.running ?? undefined);
    $("page-header").value = running.header; $("page-footer").value = running.footer; $("page-numbering").value = running.numbering;
    $("page-first-different").checked = Boolean(running.firstPage);
    $("page-first-header").value = running.firstPage?.header ?? running.header;
    $("page-first-footer").value = running.firstPage?.footer ?? running.footer;
    $("page-first-number").checked = running.firstPage?.showNumber ?? (running.numbering !== "none");
    fill(officePageSettings(editor.state.doc.attrs.page ?? undefined));
    $("page-dialog").showModal(); $("page-paper").focus();
  });
  $("page-form").addEventListener("input", (event) => {
    if (action) {
      if (["page-header", "page-footer", "page-numbering", "page-first-different", "page-first-header",
        "page-first-footer", "page-first-number"].includes(event.target.id)) action.runningReset = false;
      else action.reset = false;
    }
    preview();
  });
  $("page-reset").addEventListener("click", () => {
    if (actionCurrent(action)) { fill(officePageSettings()); action.reset = true; }
  });
  $("page-running-reset").addEventListener("click", () => {
    if (!actionCurrent(action)) return;
    $("page-header").value = ""; $("page-footer").value = ""; $("page-numbering").value = "none";
    $("page-first-different").checked = false; $("page-first-header").value = "";
    $("page-first-footer").value = ""; $("page-first-number").checked = false;
    action.runningReset = true; preview();
  });
  for (const id of ["page-close", "page-cancel"]) $(id).addEventListener("click", () => close(true));
  $("page-dialog").addEventListener("cancel", (event) => { event.preventDefault(); close(true); });
  $("page-dialog").addEventListener("close", () => { if (!$("page-dialog").open && action) close(); });
  $("page-form").addEventListener("submit", (event) => {
    event.preventDefault();
    if (!actionCurrent(action)) { close(); return; }
    const editor = action.editor;
    let transaction;
    try {
      const page = read(), current = editor.state.doc.attrs.page, running = readRunning(page), currentRunning = editor.state.doc.attrs.running;
      const samePage = JSON.stringify(page) === JSON.stringify(officePageSettings(current ?? undefined));
      const sameRunning = JSON.stringify(running) === JSON.stringify(officeRunningSettings(currentRunning ?? undefined));
      // Preserve already stored explicit defaults on a no-op; reset from a custom
      // profile removes optional metadata and returns to legacy canonical content.
      if (!(action.reset && current != null) && !(action.runningReset && currentRunning != null) && samePage && sameRunning) {
        $("page-status").textContent = "Keine Änderung: Diese Seiteneinstellungen gelten bereits."; return;
      }
      const value = samePage && !action.reset ? current : JSON.stringify(page) === JSON.stringify(OFFICE_PAGE_DEFAULT) ? null : page;
      const runningValue = sameRunning && !action.runningReset ? currentRunning : JSON.stringify(running) === JSON.stringify(OFFICE_RUNNING_DEFAULT) ? null : running;
      transaction = editor.state.tr.setDocAttribute("page", value).setDocAttribute("running", runningValue);
      if (editor.state.storedMarks) transaction.setStoredMarks(editor.state.storedMarks);
      validate(transaction.doc);
    } catch {
      $("page-status").textContent = "Die Seiteneinstellungen sind ungültig oder überschreiten die Dokumentgrenzen. Ihr Entwurf bleibt unverändert.";
      return;
    }
    close();
    editor.view.dispatch(closeHistory(transaction));
    editor.view.dispatch(closeHistory(editor.state.tr).setStoredMarks(editor.state.storedMarks));
    focus(); updateEditor(); notice("Seiteneinstellungen geändert. Rückgängig ist möglich; gespeichert wird erst mit der nächsten bestätigten Version.");
  });
  return { close, update };
}
