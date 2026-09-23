import { closeHistory } from "@tiptap/pm/history";
import { OFFICE_PAGE_DEFAULT, OFFICE_PAGE_SIDES, officePageSettings, officePageDescription, officePagePreview } from "./office-page.mjs";

export function installOfficePageControls({ state, allowed, actionCurrent, sessionCurrent, validate, focus, updateEditor, notice }) {
  const $ = (id) => document.getElementById(id);
  let action = null;
  const close = (restoreFocus = false) => {
    const previous = action; action = null;
    $("page-dialog").close(); $("page-form").reset(); $("page-status").textContent = "";
    $("page-description").textContent = ""; $("page-preview").removeAttribute("style");
    if (restoreFocus && previous?.editor === state.editor && sessionCurrent(previous.session)) focus();
  };
  const read = () => officePageSettings({ paper: $("page-paper").value, orientation: $("page-orientation").value,
    margins: Object.fromEntries(OFFICE_PAGE_SIDES.map((side) => [side, $(`page-${side}`).valueAsNumber])) });
  const preview = () => {
    if (!actionCurrent(action)) { close(); return; }
    try {
      const page = read(); officePagePreview($("page-preview"), page);
      $("page-description").textContent = officePageDescription(page);
      $("page-status").textContent = ""; $("page-apply").disabled = false;
    } catch {
      $("page-description").textContent = ""; $("page-apply").disabled = true;
      $("page-status").textContent = "Geben Sie für jeden Rand eine ganze Zahl von 5 bis 50 mm ein.";
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
    fill(officePageSettings(editor.state.doc.attrs.page ?? undefined));
    $("page-dialog").showModal(); $("page-paper").focus();
  });
  $("page-form").addEventListener("input", () => { if (action) action.reset = false; preview(); });
  $("page-reset").addEventListener("click", () => {
    if (actionCurrent(action)) { fill(officePageSettings()); action.reset = true; }
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
      const page = read(), current = editor.state.doc.attrs.page;
      // Preserve already stored explicit defaults on a no-op; reset from a custom
      // profile removes optional metadata and returns to legacy canonical content.
      if (!(action.reset && current != null) && JSON.stringify(page) === JSON.stringify(officePageSettings(current ?? undefined))) {
        $("page-status").textContent = "Keine Änderung: Diese Seiteneinstellungen gelten bereits."; return;
      }
      const value = JSON.stringify(page) === JSON.stringify(OFFICE_PAGE_DEFAULT) ? null : page;
      transaction = editor.state.tr.setDocAttribute("page", value);
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
