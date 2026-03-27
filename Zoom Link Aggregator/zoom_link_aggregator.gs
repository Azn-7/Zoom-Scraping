function extractZoomLinksWithRedirects() {
  // ============================================================= CONFIGURATION =============================================================
  const publicDriveLink =
    "https://drive.google.com/file/d/1mqDJp_NwN_bTXoTMy1U91_ox7d0vZlxB/view?usp=sharing";
  const sheetName = "Zoom Redirect Metadata Export1111";

  const COURSE_NAME = "csci10c"; // 🔧 Set this manually per run
  const BASE_PATH = "https://tomrebold.com/video/zoom/";

  // ============================================================= PROGRAM =============================================================

  const fileIdMatch = publicDriveLink.match(/[-\w]{25,}/);
  if (!fileIdMatch) {
    Logger.log("❌ Invalid Google Drive link format.");
    return;
  }
  const fileId = fileIdMatch[0];
  const txtFileUrl = `https://drive.google.com/uc?export=download&id=${fileId}`;

  let response;
  try {
    response = UrlFetchApp.fetch(txtFileUrl);
  } catch (e) {
    Logger.log(`❌ Unable to access file. (${e.message})`);
    return;
  }

  const docUrls = response
    .getContentText()
    .split("\n")
    .filter((url) => url.trim());
  const zoomRows = [];

  for (let i = 0; i < docUrls.length; i++) {
    const rawUrl = docUrls[i].trim();
    try {
      const docId = rawUrl.match(/[-\w]{25,}/)[0];
      const doc = DocumentApp.openById(docId);
      const assignment = sanitizeTitle(doc.getName());

      Logger.log(`📄 Processing ${i + 1}/${docUrls.length}: ${assignment}`);

      const linkMap = new Map();
      walkElementTree(doc.getBody(), linkMap);
      if (doc.getHeader()) walkElementTree(doc.getHeader(), linkMap);
      if (doc.getFooter()) walkElementTree(doc.getFooter(), linkMap);

      for (let [url, title] of linkMap.entries()) {
        if (isZoomLink(url)) {
          const epochMatch = url.match(/startTime=(\d+)/);
          const epoch = epochMatch ? epochMatch[1] : "";
          const gmt = epoch ? formatEpochToGMT(epoch) : "";
          const redirect = gmt
            ? `${BASE_PATH}${COURSE_NAME}/${assignment}/${gmt}_Recording_1920x1080.mp4`
            : "";
          zoomRows.push([assignment, title, url, epoch, gmt, redirect]);
        }
      }
    } catch (e) {
      Logger.log(`❌ Error processing: ${rawUrl} — ${e.message}`);
    }
  }

  const sheet = SpreadsheetApp.create(sheetName);
  const tab = sheet.getActiveSheet();
  tab.appendRow([
    "Assignment Title",
    "Hyperlink Title",
    "Zoom Link",
    "Epoch",
    "GMT",
    "Redirect Link",
  ]);
  zoomRows.forEach((row) => tab.appendRow(row));

  Logger.log(`✅ Export complete: ${sheet.getUrl()}`);
}

function walkElementTree(element, linkMap) {
  const type = element.getType();

  if (type === DocumentApp.ElementType.TEXT) {
    const text = element.asText();
    const fullText = text.getText();
    const len = fullText.length;

    for (let i = 0; i < len; i++) {
      const link = text.getLinkUrl(i);
      if (link) {
        const snippet = fullText.substring(i, Math.min(i + 60, len)).trim();
        if (!linkMap.has(link)) linkMap.set(link, snippet);
      }
    }

    const rawUrls = fullText.match(/https?:\/\/[^\s)]+/g);
    if (rawUrls) {
      for (let raw of rawUrls) {
        if (!linkMap.has(raw)) linkMap.set(raw, "");
      }
    }
  } else if (element.getNumChildren) {
    const count = element.getNumChildren();
    for (let i = 0; i < count; i++) {
      walkElementTree(element.getChild(i), linkMap);
    }
  }
}

function isZoomLink(link) {
  return link.includes("cccconfer.zoom.us") || link.includes("mpc-edu.zoom.us");
}

function sanitizeTitle(name) {
  return name
    .replace(/\s+/g, "-")
    .replace(/-+/g, "-")
    .replace(/^-+|-+$/g, "");
}

function formatEpochToGMT(epochStr) {
  const epoch = parseInt(epochStr, 10);
  if (isNaN(epoch)) return "";
  const date = new Date(epoch);
  const yyyy = date.getUTCFullYear();
  const mm = String(date.getUTCMonth() + 1).padStart(2, "0");
  const dd = String(date.getUTCDate()).padStart(2, "0");
  const hh = String(date.getUTCHours()).padStart(2, "0");
  const min = String(date.getUTCMinutes()).padStart(2, "0");
  const sec = String(date.getUTCSeconds()).padStart(2, "0");
  return `GMT${yyyy}${mm}${dd}-${hh}${min}${sec}`;
}
