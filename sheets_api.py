function doPost(e) {
  var sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName("Requests");
  var data = JSON.parse(e.postData.contents);
  var rows = sheet.getDataRange().getValues();
  if (data.method === "CREATE") {
    sheet.appendRow([data.id, data.desc, data.address, data.lat, data.lng, "IDLE", "", "", ""]);
  } else if (data.method === "VERIFY") {
    for (var i = 1; i < rows.length; i++) {
      if (rows[i][0].toString() === data.request_id.toString()) {
        sheet.getRange(i + 1, 6).setValue("VERIFIED");
        sheet.getRange(i + 1, 7).setValue(data.user_id);
        sheet.getRange(i + 1, 8).setValue(data.verdict);
        sheet.getRange(i + 1, 9).setValue(new Date().toISOString());
        break;
      }
    }
  }
  return ContentService.createTextOutput("Success");
}
function doGet(e) {
  var sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName("Requests");
  var rows = sheet.getDataRange().getValues();
  var headers = rows[0];
  var data = rows.slice(1).map(row => {
    var obj = {};
    headers.forEach((h, i) => obj[h.toLowerCase().replace(" ", "_")] = row[i]);
    return obj;
  });
  return ContentService.createTextOutput(JSON.stringify(data)).setMimeType(ContentService.MimeType.JSON);
}
