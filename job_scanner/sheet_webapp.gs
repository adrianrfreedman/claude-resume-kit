// Tracker sheet writer: paste into the sheet's Extensions → Apps Script, deploy as a Web app
// (Execute as: Me, Who has access: Anyone). The /exec URL is the write key; keep it private.
function doPost(e) {
  const tabs = JSON.parse(e.postData.contents).tabs;
  const ss = SpreadsheetApp.getActive();
  for (const name in tabs) {
    const t = tabs[name], v = t.values, n = v[0].length;
    let sh = ss.getSheetByName(name);
    if (!sh) {  // reuse the blank default tab before adding new ones
      const blank = ss.getSheets().find(s => s.getLastRow() === 0 && !(s.getName() in tabs));
      sh = blank ? blank.setName(name) : ss.insertSheet(name);
    }
    sh.clear();
    const r = sh.getRange(1, 1, v.length, n);
    r.setValues(v);
    if (t.backgrounds) r.setBackgrounds(t.backgrounds);
    sh.getRange(1, 1, 1, n).setFontWeight('bold');
    sh.setFrozenRows(1);
    if (n > 1) sh.autoResizeColumns(1, n - 1);  // last column (summary/note) overflows instead
  }
  return ContentService.createTextOutput('ok');
}
