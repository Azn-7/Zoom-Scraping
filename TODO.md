# TODO

## README

- [x] Add a closing step to the "Getting your links" section pointing back to the install/run
      steps — since done one better: merged "Quick Start" and "Getting your links" into a single
      "Getting Started" section with one continuous numbered flow (get links first, then
      install/run), instead of two separate sections that cross-referenced each other.
- [x] Fill in / verify the Google Apps Script instructions. Read the full script and rewrote the
      section accordingly: updated file path and confirmed the domain check is now a single broad
      `link.includes('zoom.us')` (no per-domain hunting needed), documented `COURSE_NAME`/`BASE_PATH`
      as only feeding the Redirect Link column, and added the trim-to-3-columns step before pasting
      into `zoom_links.txt`. Still worth a read-through since I haven't run the script myself.
- [x] Reordered so the downloader (install/run) leads as the main product, with the Google Docs
      scraping script demoted to a clearly-marked "Optional: Extracting links from Google Docs"
      section near the bottom — the two workflows serve different audiences and shouldn't compete
      for the reader's attention up front.
- [x] Added a bare 1-column `zoom_links.txt` format (just a link per line, no title/organizing) for
      anyone who just wants to mass-download without dealing with renaming — `parse_zoom_links_file`,
      `download_zoom_recording`, and `write_grouped_links_file` all updated to handle a missing title
      gracefully (falls back to keeping the original Zoom filename / showing the link itself).
- [x] Added a "Running it again" section covering per-run/repeat-run behavior that wasn't documented
      anywhere: how `SKIP_FINISHED_LINKS` resuming works and how to reset it (delete `Debug/Finished
      Links.txt`, gets recreated automatically), that matching is by link not title, that a forced
      full re-run produces `__dup1`-suffixed duplicates rather than overwriting `Results/`, that
      `REMOVE_EXTENSIONS`/`SKIP_SCREEN_SHARE_ONLY_VIDEO` retroactively clean up the whole destination
      folder (not just the current link) whenever any link in it gets processed, and that `Debug/Logs`
      and `Debug/Snapshot` accumulate forever with no auto-cleanup.
- [x] Replaced `README.md` with the rewritten draft — old version archived at `.dev/README_OLD.md`.

## Verification (checked against the 2026-08-15 19:10 run)

- [x] `Debug/Snapshot` — confirmed, and it earned its keep: all 3 skipped links this run turned out
      to be auth-walled (2 redirected to institutional SSO login pages, 1 was a live `/j/...` join
      link Zoom flagged as "may not be supported on your browser") rather than a script bug. Without
      the screenshot these would've just been unexplained "no download button" entries.
- [x] `Debug/Logs/(timestamp).txt` — confirmed, log file content matches console output line for line
      (phase timings, resume messages, final summary all present).
- [x] `Debug/Finished Links.txt` + `SKIP_FINISHED_LINKS` — confirmed by an actual crash/resume cycle:
      the first run was Ctrl+C'd after 3 successful links, and the second run correctly printed
      "Resuming: 3 link(s) already finished..." and skipped exactly those 3 before continuing.
- [x] `Debug/Logs/(timestamp) Failed Links.txt` — confirmed, 27 Deleted + 3 Skipped links all showed
      up correctly grouped by Document Title and tagged with the right reason.
- [ ] Partial-download retry/dedupe (`Download (N files)` detection) — still unverified. Every
      download in this run completed in full on the first attempt (no `[Dedup]`/"Partial download"
      lines anywhere in the log), so the retry path was never actually exercised. Needs a run where a
      link genuinely comes up short to confirm.

- [x] The `(Video)`-for-both cosmetic note above — researched it: Zoom explicitly tags its recording
      layouts in the filename (`_as_` = screen/app share only, `_avo_` = active-speaker only, `_gvo_`
      = gallery only, no tag = the default combined view). They're not guaranteed identical, just
      possibly similar-looking depending on the recording. `move_downloads_to_destination`'s special
      tag detection now checks those markers directly instead of guessing from resolution alone, so
      `_as_` gets its own `Screen Share` label (and `_gvo_` gets `Gallery`) rather than colliding with
      `Video`. Also added `SKIP_SCREEN_SHARE_ONLY_VIDEO` (default `False`) to optionally drop the
      `_as_` file entirely if you decide you don't want it kept.

## Python Zoom Link Aggregator

`(Python Script) Zoom Link Aggregator/zoom_link_aggregator.py` — now the recommended way to pull
Zoom links out of Google Docs, replacing the Google Apps Script workflow (no Google account/Apps
Script project/Drive upload needed; fetches each Doc's public HTML export directly and writes the
same 6-column CSV the `.gs` script produced). Core logic (title sanitizing, epoch→GMT conversion,
redirect-unwrapping, zoom-link filtering) is unit-tested and confirmed working end-to-end against a
real Google Doc. Documented in `README.md`'s "Optional: Extracting links from Google Docs" section;
the `.gs` script is no longer documented there, kept in the repo for reference only.

- [x] **Verify against a real Doc**: confirmed — anonymous `requests.get()` against
      `docs.google.com/document/d/<id>/export?format=html` works cleanly for a Doc shared as
      "Anyone with the link can view."
- [x] Confirmed the `google.com/url?q=...` redirect-wrapping assumption holds for real exported
      links — the exported CSV's Zoom Link column came out clean, not still wrapped.
- [x] The `<title>` tag turned out to be an unreliable source for the document title on a real Doc
      (came back as the raw doc ID). Fixed by reading it from the `Content-Disposition` response
      header instead (`extract_title_from_content_disposition()`, via `email.message.Message`) —
      confirmed correct on a real run.
- [ ] **Headers/footers may still be missing.** The `.gs` script explicitly scans `doc.getHeader()`/
      `doc.getFooter()` separately from the body — still unknown whether Google's HTML export
      includes header/footer content at all. If a real Doc has Zoom links in a header/footer and
      they don't show up in the output, this is why — would need a different extraction approach for
      those (Apps Script's DocumentApp API can reach them directly; a plain HTML export might not
      expose them in the body markup).
- [x] Decided: this replaces the `.gs` script as the documented/recommended path. `README.md`
      updated accordingly; `.gs` script kept in the repo undocumented, for reference only.
- [x] Added `OUTPUT_COLUMNS` — a config array of the 6 possible column names; removing an entry
      drops it from the export. `fetch_doc_links()` now builds each row as a dict (keyed by all 6
      names regardless of the setting), and `main()` writes with `csv.DictWriter(...,
      fieldnames=OUTPUT_COLUMNS, extrasaction='ignore')`, so filtering only happens at write time.
      Lets a user trim straight to the 3 columns `zoom_downloader.py` needs instead of manually
      editing the CSV. Verified with both the full 6-column and a trimmed 3-column config.
- [ ] **Found while documenting this**: the exported CSV is comma-delimited; `zoom_links.txt` is
      tab-delimited. Even with `OUTPUT_COLUMNS` trimmed to the matching 3 columns, pointing
      `INPUT_TXT` directly at the export won't parse correctly today — copy/paste into
      `zoom_links.txt` is the only route that actually works. README documents this honestly rather
      than implying direct interchangeability. No delimiter toggle added since it wasn't asked for —
      worth adding if direct `INPUT_TXT` pointing turns out to matter.

## Data

- [ ] (Optional) `zoom_links.txt`'s header row still reads "Assignment Title" — left alone since
      it's your data file, not code. Update it yourself if you want it to match "Document Title".

## Source code update
