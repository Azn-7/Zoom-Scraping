# Zoom Scraping

Bulk-downloads the files (video, audio, transcript) attached to a list of Zoom recording links, using Selenium to automate the same "click Download" steps a person would do by hand. Useful when you have many lecture recordings to save locally and don't want to click through each one individually.

## Getting Started

1. Install [Python](https://www.python.org/downloads/windows/) (check "Add python.exe to PATH" during setup).
2. Open a terminal in this folder and install dependencies:
   ```
   pip install -r requirements.txt
   ```
3. Put your links in `zoom_links.txt` — even one bare link per line works, no titles or organizing required. See [format](#zoom_linkstxt-format) below for the other options.
4. Run it:
   ```
   python zoom_downloader.py
   ```
5. Downloaded files land in `Results/` next to `zoom_downloader.py`.

Don't have your links yet? If they're scattered across a batch of Google Docs, there's an optional helper script for that — see [Extracting links from Google Docs](#optional-extracting-links-from-google-docs) near the bottom.

---

## zoom_links.txt format

The file is tab-separated. Each line is auto-detected by how many columns it has, so you can mix formats freely in the same file.

| Columns | Format | Behavior |
|---|---|---|
| 1 | `Zoom Link` | Just want to mass-download links with no organizing or renaming? This is it. All files download into one flat `Results/` folder, keeping their original Zoom filename as-is. |
| 2 | `Hyperlink Title` `Zoom Link` | All files download into one flat `Results/` folder, renamed after the title. |
| 3 | `Document Title` `Hyperlink Title` `Zoom Link` | A subfolder is created per Document Title inside `Results/`, files renamed after the title. |

```
https://zoom.us/rec/share/...
Course Overview	https://zoom.us/rec/share/...
CSCI-10A-Video-Links-F25	Course Overview	https://zoom.us/rec/share/...
```

A header row (e.g. `Document Title  Hyperlink Title  Zoom Link`) is skipped automatically — its link column won't be a real URL.

For the 2- and 3-column formats, every downloaded file is renamed to `Hyperlink Title (SPECIAL) (original filename).ext`, e.g. `Course Overview (Video) (GMT20250819-175548_Recording_1920x1080).mp4`. `SPECIAL` reflects which of Zoom's recording layouts the file is — `Video` (the default combined view), `Screen Share` (screen/app share only), `Camera` (active-speaker only), `Gallery` (gallery view only) — or omitted if none of those apply. The naming pattern is fully configurable — see `FILENAME_TEMPLATE` below.

Zoom sometimes exports both the default `Video` file and a separate `Screen Share`-only file for the same recording — they're not guaranteed identical, but can look very similar if the presenter's camera contributed little to the frame. Set `SKIP_SCREEN_SHARE_ONLY_VIDEO = True` (see Configuration below) if you'd rather not keep that one.

---

## Configuration

All of these live near the top of `zoom_downloader.py`.

| Variable | Default | What it does |
|---|---|---|
| `BROWSER` | `'edge'` | `'edge'` (nothing to install on Windows) or `'chrome'` (better on Linux, where Chromium is a package-manager install away). |
| `utils.HEADLESS` | `False` | Set `True` to run without a visible browser window. |
| `BASE_OUTPUT_PATH` | `Results/` next to the script | Where downloaded files go. |
| `INPUT_TXT` | `'zoom_links.txt'` | Which file to read links from. |
| `FILENAME_TEMPLATE` | `"{title} ({special}) ({original})"` | How downloaded files are renamed — see token reference below. |
| `REMOVE_EXTENSIONS` | `[]` | File extensions to delete after downloading, e.g. `['.m4a', '.vtt']`. |
| `SKIP_SCREEN_SHARE_ONLY_VIDEO` | `False` | Skip keeping Zoom's `Screen Share`-only recording layout (see [format](#zoom_linkstxt-format) above). |
| `SKIP_FINISHED_LINKS` | `True` | Skip links already recorded as done in `Debug/Finished Links.txt` — lets you resume after a crash without redoing completed work. Set `False` to force a full run. |
| `ACTIVE_DOWNLOAD_TIMEOUT_SECONDS` | `1200` (20 min) | Max time to wait, per link, for a slow/large download to finish before giving up. `0` disables the wait. |

`FILENAME_TEMPLATE` tokens — mix, match, or omit any of them (each is a bare value, so add your own spaces/parentheses around whichever you keep):

| Token | Example |
|---|---|
| `{title}` | `Course_Overview` |
| `{special}` | `Video`, `Screen Share`, `Camera`, `Gallery`, or empty |
| `{original}` | `GMT20250819-175548_Recording_1920x1080` |

The original file extension is always kept — there's no `{ext}` token, since there's no real reason to move or drop it. If a token like `{special}` renders empty, any leftover double spaces or empty `()` left behind get cleaned up automatically, so the default template still renders cleanly either way. And if a template omits (or renders empty for) both `{title}` and `{original}`, leaving nothing meaningful to build a name from, the original Zoom filename is kept as-is instead of risking an empty or colliding filename.

Ctrl+C stops cleanly at any point — the browser closes and a partial summary prints for whatever was completed.

---

## Output

**`Results/`** — your downloaded files, organized per the format table above.

**`Debug/`** — written on every run (the `Snapshot`/`Logs` locations are configurable via `DEBUG_SNAPSHOT_DIR`/`DEBUG_LOG_DIR`):

| Path | Contents |
|---|---|
| `Debug/Logs/(timestamp).txt` | Full copy of everything printed to the console for that run. |
| `Debug/Logs/(timestamp) Failed Links.txt` | Only the links that were skipped, failed, or confirmed deleted, grouped by Document Title, each line tagged with why: `(Deleted) Title: Link`. Not written if nothing went wrong. |
| `Debug/Snapshot/Failure at (time) for (title).png` | A screenshot of the page at the moment a link is skipped or fails — helpful when the reason isn't obvious from the console (e.g. the link wasn't actually a recording share page). |
| `Debug/Finished Links.txt` | Every link successfully downloaded or confirmed deleted, across all runs. Used by `SKIP_FINISHED_LINKS`. |

---

## Running it again

A few things worth knowing before you re-run the program on a `zoom_links.txt` you've already run before:

- **Resuming picks up where you left off, by design.** With `SKIP_FINISHED_LINKS` at its default `True`, any link already recorded in `Debug/Finished Links.txt` — successfully downloaded, or confirmed deleted — is skipped instead of redone. This is what makes it safe to just re-run after a crash or a Ctrl+C partway through; skipped/failed links are never recorded, so those always get retried.
- **To force a one-off full re-run without losing that history**, set `SKIP_FINISHED_LINKS = False` for that run only, then switch it back. New completions still get recorded either way.
- **To reset the resume history entirely**, delete `Debug/Finished Links.txt` (or just clear its contents) — nothing needs to be recreated by hand, it gets written fresh the next time a link finishes.
- **Matching is done by the Zoom link itself, not the title.** If you edit a hyperlink title in `zoom_links.txt` after a link has already been downloaded, it's still correctly recognized as finished — but the file already on disk keeps its old name; it won't retroactively get renamed.
- **A forced full re-run doesn't overwrite existing files in `Results/`.** If a rendered filename already exists there, the new download is saved alongside it with a `__dup1`, `__dup2`, etc. suffix rather than replacing it — so re-running with `SKIP_FINISHED_LINKS = False` on top of an already-populated `Results/` folder gets you duplicates, not clean re-downloads. Clear the relevant folder first if a true redo is what you want.
- **`REMOVE_EXTENSIONS` and `SKIP_SCREEN_SHARE_ONLY_VIDEO` apply retroactively.** Both clean up the *entire* destination folder each time they run, not just the file(s) from the link currently being processed. So turning either on and running again — even with most links skipped via `SKIP_FINISHED_LINKS` — will also delete matching files left over from links you already downloaded in an earlier run, as soon as any other link sharing that folder gets processed.
- **`Debug/Logs` and `Debug/Snapshot` accumulate indefinitely** — one log file per run, one screenshot per skipped/failed link, and nothing is ever deleted automatically. Nothing reads them back, so it's safe to clear old ones out by hand whenever you like.
- **Adding new rows to `zoom_links.txt` between runs is safe** — previously finished links are skipped as usual, and only the new ones get processed.

---

## Optional: Extracting links from Google Docs

*Only relevant if your Zoom recording links are scattered across a batch of Google Docs rather than already in a list. If you already have your links, you don't need this.*

Uses the bundled Python script, `(Python Script) Zoom Link Aggregator/zoom_link_aggregator.py`, to scan those Docs and export any Zoom links found in them to a CSV. It fetches each Doc's public export directly over HTTP, so there's no Google account, Apps Script project, or Google Drive upload involved — just this script, run locally, same as `zoom_downloader.py`. Its dependencies are already covered by `requirements.txt` (step 2 of [Getting Started](#getting-started)).

> Every Google Doc you want scanned should be shared as "Anyone with the link can view" — this fetches them anonymously, with no login.

1. Create `(Python Script) Zoom Link Aggregator/google_docs.txt`, listing the Google Docs you want scanned, one URL per line:
   ```
   https://docs.google.com/document/d/(1)/edit?usp=sharing
   https://docs.google.com/document/d/(2)/edit?usp=sharing
   ```
2. Run it:
   ```
   python "(Python Script) Zoom Link Aggregator/zoom_link_aggregator.py"
   ```
3. It writes `(Python Script) Zoom Link Aggregator/zoom_links_export.csv`, containing whichever columns are listed in `OUTPUT_COLUMNS` near the top of the script:

   | Column | Used by zoom_downloader.py? |
   |---|---|
   | Document Title | Yes |
   | Hyperlink Title | Yes |
   | Zoom Link | Yes |
   | Epoch | No — raw timestamp pulled from the link's `startTime` parameter |
   | GMT | No — that timestamp reformatted |
   | Redirect Link | No — a constructed `BASE_PATH`/`DOCUMENT_NAME`/... URL, only meaningful if you host recordings yourself at that pattern (both are configurable near the top of the script) |

   All six are included by default. If you only want the three `zoom_downloader.py` actually uses, trim `OUTPUT_COLUMNS` down to `['Document Title', 'Hyperlink Title', 'Zoom Link']` — the export will then only ever contain those three, so there's nothing to sort out by hand afterward.

4. Copy the CSV's contents into `zoom_links.txt`, then head back up to [Getting Started](#getting-started) to run the downloader. The export is comma-delimited (real CSV, so it opens cleanly in a spreadsheet), while `zoom_links.txt` is tab-delimited — so this is a copy/paste step, not a matter of just pointing `INPUT_TXT` at the CSV directly.

The script matches any link containing `zoom.us`, so every Zoom subdomain (`csumb.zoom.us`, `mpc-edu.zoom.us`, `cccconfer.zoom.us`, etc.) is picked up automatically — no per-domain setup needed. It catches both real hyperlinks and plain pasted URLs in the Doc body. Whether links placed in a Doc's header/footer (rather than the body) get picked up is currently unverified — if you have links there and they don't show up, that's likely why.

A `DOC_LIST_FILE`/`OUTPUT_CSV` pair of variables near the top of the script control the input/output paths above, if you'd rather use different ones. A short delay between requests (`REQUEST_DELAY_SECONDS`) is built in so scanning a large batch of Docs doesn't look like abuse to Google.

*A previous version of this used a Google Apps Script instead (Google account, Apps Script project, and a Drive-hosted file list required) — it's no longer the recommended path, but the original script is still in the repo at `(Google Script) Zoom Link Aggregator/` for reference.*

---

## Notes

- Actual time per link varies a lot with connection speed and how many files a recording has — there's no reliable fixed estimate anymore, so budget generously for a first run and let the console's live "avg time / est. remaining" line guide you after that.
- This is for downloading recordings you have legitimate access to (e.g. your own course lectures) — respect whatever access controls Zoom/your institution has in place.
