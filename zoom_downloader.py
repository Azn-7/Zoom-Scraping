# zoom_downloader.py
import os
import sys
import time
import shutil
import subprocess
from datetime import datetime
from urllib.parse import urlparse, unquote
from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.edge.options import Options as EdgeOptions
from selenium.webdriver.edge.service import Service as EdgeService
from webdriver_manager.chrome import ChromeDriverManager
from webdriver_manager.microsoft import EdgeChromiumDriverManager

import zoom_utils as utils

# ==============================================================================
# ======================== CONFIGURATION VARIABLES =============================
# ==============================================================================

# Set HEADLESS = Run with visible browser
utils.HEADLESS = False

# How many seconds to wait, per link, for a still-in-progress download to finish before giving up on
# it. By default, this is set to 20 minutes. This should be increased should you either download large
# files or have slow internet — set to 0 to disable this wait entirely.
ACTIVE_DOWNLOAD_TIMEOUT_SECONDS = 1200

# Extensions to remove after downloads complete
# To disable deletion leave as an empty list: REMOVE_EXTENSIONS = []
REMOVE_EXTENSIONS = []   # e.g. ['.m4a', '.tmp']

INPUT_TXT = 'zoom_links.txt'
BASE_OUTPUT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'Results')

# Where diagnostic output goes: a screenshot of the page whenever a link is skipped/fails (helps
# figure out why after the fact), and a full copy of everything printed to the console for the run.
DEBUG_SNAPSHOT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'Debug', 'Snapshot')
DEBUG_LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'Debug', 'Logs')

# If True, links already recorded in FINISHED_LINKS_FILE (a successful download, or a confirmed-deleted
# recording, from any previous run) are skipped instead of re-processed — handy for resuming after a
# crash/interruption without redoing work that already finished. Links that were skipped/failed last
# time are NOT recorded, so they're always retried. Set to False to always do a full run regardless of
# what's in that file (new completions still get recorded either way, for next time).
SKIP_FINISHED_LINKS = True
FINISHED_LINKS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'Debug', 'Finished Links.txt')

# How downloaded files are renamed. Mix and match these tokens in any order — every token is a bare
# value, so add your own spaces/parentheses/etc. around them as you like. If a token like {special}
# renders empty, any leftover double spaces or empty "()" around it get cleaned up automatically.
#   {title}    e.g. "Course_Overview"
#   {special}  e.g. "Video", "Camera", or ""
#   {original} e.g. "GMT20250819-175548_Recording_as_1920x1080"
#   {ext}      e.g. ".mp4"
# Default template renders as: Course_Overview (Video) (GMT20250819-175548_Recording_as_1920x1080).mp4
FILENAME_TEMPLATE = "{title} ({special}) ({original}){ext}"

# Which Chromium-based browser to automate: 'edge' or 'chrome'.
# - 'edge': Microsoft Edge. Ships pre-installed on Windows, so nothing extra to install.
# - 'chrome': Google Chrome, or Chromium (the 'chromium'/'chromium-browser' package that's
#   readily available via most Linux package managers). Requires one of those to already be installed.
BROWSER = 'edge'

# ==============================================================================
# ========================= END OF CONFIGURATION ===============================
# ==============================================================================

def initialize_webdriver():
    """Initializes and configures the Selenium webdriver for the configured BROWSER (Edge or Chrome/Chromium)."""
    browser = BROWSER.strip().lower()
    options = EdgeOptions() if browser == 'edge' else ChromeOptions()

    options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64)')
    options.add_argument('--window-size=1920,1080')
    if utils.HEADLESS:
        options.add_argument('--headless=new')
    if utils.MUTE_AUDIO:
        options.add_argument('--mute-audio')

    if browser == 'edge':
        # Skip Edge's first-run/sign-in/"set as default" nag screens, which can otherwise sit in front
        # of the page and eat through click_with_retries' whole retry budget. Deliberately NOT using
        # --inprivate here — InPrivate mode has been observed to ignore the CDP-directed download path
        # (Browser.setDownloadBehavior in zoom_utils.prepare_download_folder), sending files to Edge's
        # default Downloads folder instead of the per-link temp folder the script expects.
        options.add_argument('--no-first-run')
        options.add_argument('--no-default-browser-check')
        # SmartScreen's per-download reputation check adds real latency and has no Chrome equivalent.
        options.add_argument('--disable-features=msSmartScreenProtection')

    download_preferences = {
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
        "profile.default_content_setting_values.popups": 0,
        "profile.default_content_setting_values.automatic_downloads": 1
    }
    options.add_experimental_option("prefs", download_preferences)
    options.set_capability('goog:loggingPrefs', {'performance': 'ALL'})

    # On Windows, Ctrl+C is broadcast to the whole console process group, which by default includes
    # the driver process (and the browser it spawns) — killing them before driver.quit() gets a chance
    # to close the browser cleanly. Launching the driver in its own process group makes it immune to
    # that broadcast, so our try/finally driver.quit() in main() can actually do its job.
    service_kwargs = {'popen_kw': {'creation_flags': subprocess.CREATE_NEW_PROCESS_GROUP}} if os.name == 'nt' else {}

    if browser == 'edge':
        service = EdgeService(EdgeChromiumDriverManager().install(), **service_kwargs)
        driver = webdriver.Edge(service=service, options=options)
    else:
        service = ChromeService(ChromeDriverManager().install(), **service_kwargs)
        driver = webdriver.Chrome(service=service, options=options)

    driver.set_page_load_timeout(60)
    return driver


def parse_zoom_links_file(file_path: str) -> list:
    """Reads the zoom links text file and returns a list of entries, in order.

    Supports two tab-separated formats, auto-detected per line:
      - 2 columns: Hyperlink Title <TAB> Zoom Link
        Downloaded files land in the flat BASE_OUTPUT_PATH folder, prefixed with the title.
      - 3 columns: Document Title <TAB> Hyperlink Title <TAB> Zoom Link
        Downloaded files land in a BASE_OUTPUT_PATH\\<Document Title> subfolder, renamed
        exactly to the hyperlink title (plus original extension).

    Header rows (where the link column isn't actually a URL) are skipped automatically.
    """
    entries = []
    with open(file_path, 'r', encoding='utf-8') as file_handle:
        for line in file_handle:
            split_line = line.strip().split('\t')
            if len(split_line) == 3:
                document, title, link = (part.strip() for part in split_line)
            elif len(split_line) == 2:
                document = None
                title, link = (part.strip() for part in split_line)
            else:
                continue
            if not link.lower().startswith('http'):
                continue  # header row or malformed line
            entries.append({'document': document, 'title': title, 'link': link})
    return entries


def _log_phase(link_start_time, label):
    """Prints how many seconds have elapsed since a link started downloading, to help pinpoint slow phases."""
    print(f'   [Time] {label}: {time.time() - link_start_time:.1f}s elapsed')


def _save_failure_snapshot(driver, title):
    """Saves a screenshot of whatever's currently on screen when a link is skipped/fails, so unusual
    cases (like a page that isn't actually a recording share link) can be diagnosed after the fact."""
    timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
    saved_path = utils.save_debug_screenshot(driver, DEBUG_SNAPSHOT_DIR, f'Failure at {timestamp} for {title}')
    if saved_path:
        print(f'   [Debug] Saved failure snapshot: {saved_path}')


class _Tee:
    """Duplicates writes across multiple streams, so console output can also be captured to a log file."""
    def __init__(self, *streams):
        self._streams = streams

    def write(self, data):
        for stream in self._streams:
            stream.write(data)

    def flush(self):
        for stream in self._streams:
            stream.flush()


def download_zoom_recording(driver, document: str, title: str, link: str, file_index: int) -> dict:
    """Navigates to the Zoom recording payload, detects the download button, and extracts files locally."""
    safe_title = utils.sanitize(title).replace(' ', '_')
    rename_exact = document is not None
    destination_directory = os.path.join(BASE_OUTPUT_PATH, utils.sanitize(document)) if document else BASE_OUTPUT_PATH
    os.makedirs(destination_directory, exist_ok=True)

    temporary_download_dir = os.path.join(destination_directory, f'_tmp_Video_{file_index}')
    try:
        if os.path.isdir(temporary_download_dir):
            shutil.rmtree(temporary_download_dir)
        os.makedirs(temporary_download_dir, exist_ok=True)
    except Exception:
        os.makedirs(temporary_download_dir, exist_ok=True)

    utils.prepare_download_folder(driver, temporary_download_dir)
    link_start_time = time.time()

    try:
        driver.get(link)
    except Exception as page_load_error:
        # A slow connection can blow past set_page_load_timeout() before the page is actually done
        # rendering — that doesn't mean nothing loaded, so keep going into the normal detect/click
        # flow instead of giving up immediately. If truly nothing ever showed up, that flow already
        # ends in a 'skipped'/'failed' result on its own.
        print(f'   [Warning] Page load timed out or errored ({page_load_error.__class__.__name__}) — checking what did load anyway.')

    # Wait for either the "does not exist" error text or an actionable control to appear in the DOM
    # (checking iframes too, since Zoom's controls are often inside one). Polling stops the moment
    # either shows up, so this is fast on a normal connection and just more patient on a slow one.
    _DELETED_TEXT = 'This recording does not exist.'
    detected_control = utils.wait_for_page_ready(driver, utils.PAGE_DETECT_TIMEOUT, _DELETED_TEXT)
    _log_phase(link_start_time, f'Page detect (found={detected_control})')

    if detected_control == 'deleted' or _DELETED_TEXT in driver.page_source:
        try:
            if os.path.isdir(temporary_download_dir):
                shutil.rmtree(temporary_download_dir)
        except Exception:
            pass
        return {'status': 'deleted', 'elapsed': time.time() - link_start_time, 'files': [], 'temporary_download_dir': None, 'destination_directory': None, 'safe_title': safe_title, 'rename_exact': rename_exact}

    # If the page already went straight to a Download control (no "Continue" step in between, which
    # some Zoom pages skip entirely), there's nothing to click here — attempting it anyway would just
    # silently burn through click_with_retries' whole multi-minute budget confirming what we already
    # know. Anywhere else (a real Continue prompt found, or detection timed out without knowing either
    # way), still attempt it as a safety net.
    if detected_control != 'download':
        # Same reasoning as the Download click below: Continue can also live inside an iframe, so try
        # the frame-aware search first and only fall back to the plain (frame-blind) xpath search —
        # with its much larger retry budget — if that fails.
        continue_clicked = False
        continue_end_time = time.time() + 15
        while time.time() < continue_end_time:
            continue_clicked, _ = utils.force_click_by_keyword(driver, 'continue')
            if continue_clicked:
                break
            time.sleep(1.0)
        if not continue_clicked:
            utils.click_with_retries(driver, [
                "//button[normalize-space()='Continue']",
                "//a[normalize-space()='Continue']",
                "//*[contains(translate(.,'CONTINUE','continue'),'continue')]"
            ], timeout=max(utils.PAGE_LOAD_WAIT, 10))
    _log_phase(link_start_time, 'Continue click attempt')

    print("Attempting to download...")
    # The Download control is frequently inside an iframe, so try the frame-aware search first —
    # the plain xpath search below never looks inside iframes and would otherwise burn its entire
    # retry budget (minutes) on a control it can never find.
    clicked_download = False
    expected_file_count = None
    end_time = time.time() + 15
    while time.time() < end_time:
        clicked_download, expected_file_count = utils.force_click_by_keyword(driver, 'download')
        if clicked_download:
            break
        time.sleep(1.0)
    if not clicked_download:
        clicked_download = utils.click_with_retries(driver, [
            "//button[@aria-label='Download']",
            "//button[contains(.,'Download')]",
            "//a[contains(.,'Download')]"
            ], timeout=max(utils.AFTER_CONTINUE_WAIT + 6, 15))
    _log_phase(link_start_time, f'Download click attempt (clicked={clicked_download}, expected_files={expected_file_count})')

    if not clicked_download:
        return {'status': 'skipped', 'elapsed': time.time() - link_start_time, 'files': [], 'temporary_download_dir': temporary_download_dir, 'destination_directory': destination_directory, 'safe_title': safe_title, 'rename_exact': rename_exact}

    time.sleep(1.5)

    completed_wait = utils.wait_for_initial_download(temporary_download_dir, timeout_seconds=utils.INACTIVITY_COUNTDOWN)
    if not completed_wait:
        completed_wait = utils.wait_for_initial_download(temporary_download_dir, timeout_seconds=utils.DOWNLOAD_WAIT)
    _log_phase(link_start_time, f'Initial download wait (completed={bool(completed_wait)})')

    moved_files = utils.move_downloads_to_destination(temporary_download_dir, destination_directory, title_prefix=safe_title, rename_exact=rename_exact, filename_template=FILENAME_TEMPLATE)

    observation_start_time = time.time()
    previously_seen_files = set(utils.get_completed_downloads(temporary_download_dir))
    silence_start_time = None
    additional_files_moved = []
    while True:
        # Once we've moved as many files as the page told us to expect, there's no reason to keep
        # waiting out the inactivity countdown — we're already done.
        if expected_file_count and len(moved_files) + len(additional_files_moved) >= expected_file_count:
            break
        currently_seen_files = set(utils.get_completed_downloads(temporary_download_dir))
        newly_completed_files = sorted(list(currently_seen_files - previously_seen_files))
        if newly_completed_files:
            moved_in_current_tick = utils.move_downloads_to_destination(temporary_download_dir, destination_directory, title_prefix=safe_title, rename_exact=rename_exact, filename_template=FILENAME_TEMPLATE)
            for file_name in moved_in_current_tick:
                if file_name not in additional_files_moved:
                    additional_files_moved.append(file_name)
            previously_seen_files = set(utils.get_completed_downloads(temporary_download_dir))
            silence_start_time = None
        else:
            if silence_start_time is None:
                silence_start_time = time.time()
            elif time.time() - silence_start_time >= utils.INACTIVITY_COUNTDOWN:
                break
        if time.time() - observation_start_time >= utils.MAX_DRAIN_SECONDS:
            break
        time.sleep(0.5)

    all_moved_files = (moved_files or []) + (additional_files_moved or [])
    _log_phase(link_start_time, f'Drain loop done (files so far={len(all_moved_files)}/{expected_file_count if expected_file_count else "?"})')

    # If the page told us how many files to expect and we're short, retry the download click once
    # (Zoom's combined "Download (N files)" control re-triggers everything, not just what's missing).
    # The retry downloads into its own subfolder so we can compare its files byte-for-byte against what
    # the first pass already moved to the destination — anything identical gets discarded as a redundant
    # re-download, and only files that are genuinely new (i.e. actually filled a gap) get kept. Comparing
    # by content rather than by filename/extension works regardless of the destination naming scheme.
    retry_download_dir = None
    if expected_file_count and 0 < len(all_moved_files) < expected_file_count:
        _log_phase(link_start_time, f'Partial download ({len(all_moved_files)}/{expected_file_count}) — retrying')
        already_downloaded_paths = [os.path.join(destination_directory, f) for f in all_moved_files]

        retry_download_dir = os.path.join(temporary_download_dir, 'retry')
        os.makedirs(retry_download_dir, exist_ok=True)
        utils.prepare_download_folder(driver, retry_download_dir)

        retry_clicked, _ = utils.force_click_by_keyword(driver, 'download')
        if not retry_clicked:
            retry_clicked = utils.click_with_retries(driver, [
                "//button[@aria-label='Download']",
                "//button[contains(.,'Download')]",
                "//a[contains(.,'Download')]"
                ], timeout=max(utils.AFTER_CONTINUE_WAIT + 6, 15))

        if retry_clicked:
            time.sleep(1.5)
            utils.wait_for_initial_download(retry_download_dir, timeout_seconds=utils.DOWNLOAD_WAIT)

            retry_observation_start = time.time()
            retry_previously_seen = set(utils.get_completed_downloads(retry_download_dir))
            retry_silence_start = None
            while True:
                retry_currently_seen = set(utils.get_completed_downloads(retry_download_dir))
                if retry_currently_seen - retry_previously_seen:
                    retry_previously_seen = retry_currently_seen
                    retry_silence_start = None
                else:
                    if retry_silence_start is None:
                        retry_silence_start = time.time()
                    elif time.time() - retry_silence_start >= utils.INACTIVITY_COUNTDOWN:
                        break
                if time.time() - retry_observation_start >= utils.MAX_DRAIN_SECONDS:
                    break
                time.sleep(0.5)

            discarded_duplicates = utils.discard_duplicate_files(retry_download_dir, already_downloaded_paths)
            if discarded_duplicates:
                print('   [Dedup] Discarded already-downloaded duplicates from retry:', discarded_duplicates)

            retried_moved_files = utils.move_downloads_to_destination(retry_download_dir, destination_directory, title_prefix=safe_title, rename_exact=rename_exact, filename_template=FILENAME_TEMPLATE)
            for file_name in retried_moved_files:
                if file_name not in all_moved_files:
                    all_moved_files.append(file_name)

        try:
            if not os.listdir(retry_download_dir):
                os.rmdir(retry_download_dir)
        except Exception:
            pass

        _log_phase(link_start_time, f'Retry done (files now={len(all_moved_files)}/{expected_file_count})')

    # A large file on a slow connection can still be mid-download (.crdownload) when the drain loop
    # above gives up — give it a real chance to finish rather than abandoning it and moving to the
    # next link. This used to only happen for the very last link in the whole run (in main()); every
    # link gets the same treatment now.
    if ACTIVE_DOWNLOAD_TIMEOUT_SECONDS > 0:
        for pending_download_dir in filter(None, [retry_download_dir, temporary_download_dir]):
            if not os.path.isdir(pending_download_dir):
                continue
            has_active_download = any(f.endswith('.crdownload') for f in os.listdir(pending_download_dir))
            if has_active_download:
                utils.wait_for_active_downloads(pending_download_dir, timeout=ACTIVE_DOWNLOAD_TIMEOUT_SECONDS)
            newly_moved_files = utils.move_downloads_to_destination(pending_download_dir, destination_directory, title_prefix=safe_title, rename_exact=rename_exact, filename_template=FILENAME_TEMPLATE)
            for file_name in newly_moved_files:
                if file_name not in all_moved_files:
                    all_moved_files.append(file_name)
        _log_phase(link_start_time, f'Active-download wait done (files now={len(all_moved_files)})')

    # Fallback Mechanism: If no files were downloaded above, attempt to intercept raw media URLs dynamically from browser performance logs
    if not all_moved_files:
        collected_network_urls = set()
        network_fallback_start = time.time()
        last_new_url_discovered = time.time()
        while time.time() - network_fallback_start < utils.NETWORK_FALLBACK_SECONDS:
            found_urls = utils.extract_media_urls_from_network_logs(driver)
            new_urls = set(found_urls) - collected_network_urls
            if new_urls:
                collected_network_urls.update(new_urls)
                last_new_url_discovered = time.time()
            if time.time() - last_new_url_discovered >= utils.INACTIVITY_COUNTDOWN:
                break
            time.sleep(utils.PERF_POLL_INTERVAL)

        if collected_network_urls:
            for media_url in collected_network_urls:
                try:
                    raw_filename = unquote(urlparse(media_url).path.split('/')[-1]) or f'download_{int(time.time())}'
                    temporary_dest_path = os.path.join(temporary_download_dir, raw_filename)
                    utils.download_with_browser_cookies(driver, media_url, temporary_dest_path)
                except Exception:
                    pass
            moved_files = utils.move_downloads_to_destination(temporary_download_dir, destination_directory, title_prefix=safe_title, rename_exact=rename_exact, filename_template=FILENAME_TEMPLATE)
            all_moved_files = (moved_files or [])
        _log_phase(link_start_time, f'Network fallback done (files so far={len(all_moved_files)})')

    # conditional cleanup: only run if user configured extensions to remove
    file_extensions_removed = []
    if REMOVE_EXTENSIONS:
        file_extensions_removed = utils.remove_files_by_extensions(destination_directory, REMOVE_EXTENSIONS)
        for file_removed in file_extensions_removed:
            print('   [REMOVE_EXTENSIONS] Removed from title folder:', file_removed)

    try:
        # attempt to clean up the temporary directory if it's now empty
        if not os.listdir(temporary_download_dir):
            os.rmdir(temporary_download_dir)
    except Exception:
        pass

    return {'status': 'done', 'elapsed': time.time() - link_start_time, 'files': all_moved_files, 'removed': file_extensions_removed, 'temporary_download_dir': temporary_download_dir, 'destination_directory': destination_directory, 'safe_title': safe_title, 'rename_exact': rename_exact}


def main(run_timestamp):
    entries = parse_zoom_links_file(INPUT_TXT)
    total_links_count = len(entries)
    print(f'Total links to process: {total_links_count}')

    driver = initialize_webdriver()
    elapsed_times = []
    overall_progress = {'total': 0, 'success': 0, 'failed': 0, 'skipped': 0, 'deleted': 0, 'resumed': 0}
    unsuccessful_links = []
    deleted_links = []
    failed_links_log = []  # deleted/skipped/failed, in true chronological order, for the Failed Links file
    finished_links = utils.load_finished_links(FINISHED_LINKS_FILE) if SKIP_FINISHED_LINKS else set()
    if SKIP_FINISHED_LINKS and finished_links:
        print(f'Resuming: {len(finished_links)} link(s) already finished in a previous run will be skipped.')

    interrupted = False
    try:
        for links_processed_count, entry in enumerate(entries, start=1):
            document, title, link = entry['document'], entry['title'], entry['link']
            overall_progress['total'] += 1
            location_label = f'{document} / {title}' if document else title
            print(f'\n[{links_processed_count}/{total_links_count}] {location_label} -> {link}')

            if SKIP_FINISHED_LINKS and link in finished_links:
                overall_progress['resumed'] += 1
                print('   [Resumed] Already completed in a previous run — skipping.')
                continue

            try:
                download_result = download_zoom_recording(driver, document, title, link, links_processed_count)
            except Exception as unexpected_error:
                # Whatever went wrong with this one link (page load timeout, a stale/crashed
                # element reference, etc.), don't let it take down the rest of the batch.
                print(f'   [Error] Unexpected failure on this link ({unexpected_error.__class__.__name__}: {unexpected_error}) — moving on.')
                download_result = {'status': 'failed', 'elapsed': 0, 'files': []}
            elapsed_times.append(download_result.get('elapsed', 0))

            if download_result['status'] == 'done' and download_result.get('files'):
                overall_progress['success'] += 1
                print('   [Success] Downloaded:', download_result.get('files'))
                utils.append_finished_link(FINISHED_LINKS_FILE, link, finished_links)
            elif download_result['status'] == 'deleted':
                overall_progress['deleted'] += 1
                print('   [Deleted] Recording does not exist')
                deleted_links.append({'document': document, 'title': title, 'link': link, 'reason': 'This recording does not exist.'})
                failed_links_log.append({'document': document, 'title': title, 'link': link, 'status_label': 'Deleted'})
                utils.append_finished_link(FINISHED_LINKS_FILE, link, finished_links)
            elif download_result['status'] == 'skipped':
                overall_progress['skipped'] += 1
                print('   [Skipped] Skipped (no download control)')
                unsuccessful_links.append({'document': document, 'title': title, 'link': link, 'reason': 'No download button'})
                failed_links_log.append({'document': document, 'title': title, 'link': link, 'status_label': 'Skipped'})
                _save_failure_snapshot(driver, title)
            else:
                overall_progress['failed'] += 1
                print('   [Failed] Failed to capture files')
                unsuccessful_links.append({'document': document, 'title': title, 'link': link, 'reason': 'Missing files after attempts'})
                failed_links_log.append({'document': document, 'title': title, 'link': link, 'status_label': 'Failed'})
                _save_failure_snapshot(driver, title)

            average_time_per_link = sum(elapsed_times) / len(elapsed_times) if elapsed_times else 0
            remaining_links_count = max(0, total_links_count - links_processed_count)
            estimated_remaining_seconds = int(average_time_per_link * remaining_links_count)
            print(f'   [Time] Avg {average_time_per_link:.1f}s/link — est remaining {estimated_remaining_seconds//60}m {estimated_remaining_seconds%60}s')
    except KeyboardInterrupt:
        interrupted = True
        print('\n[Interrupted] Stopping early and closing the browser...')
    finally:
        driver.quit()

    if interrupted:
        print('\n(Partial) Summary — run interrupted before all links were processed:')
    else:
        print('\nSummary:')
    print(f"  Total: {overall_progress['total']}")
    print(f"  Resumed (already done previously): {overall_progress['resumed']}")
    print(f"  Success: {overall_progress['success']}")
    print(f"  Skipped: {overall_progress['skipped']}")
    print(f"  Failed: {overall_progress['failed']}")
    print(f"  Failed (Deleted Links): {overall_progress['deleted']}")
    if unsuccessful_links:
        print('\nFailed links:')
        for failed_link_record in unsuccessful_links:
            print(' -', failed_link_record)
    if failed_links_log:
        failed_links_path = os.path.join(DEBUG_LOG_DIR, f'{run_timestamp} Failed Links.txt')
        utils.write_grouped_links_file(failed_links_path, failed_links_log)
        print(f'\n[Debug] Wrote failed-links summary: {failed_links_path}')
    if deleted_links:
        print('\nFailed (Deleted Links):')
        for deleted_link_record in deleted_links:
            print(' -', deleted_link_record)


if __name__ == '__main__':
    run_timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
    os.makedirs(DEBUG_LOG_DIR, exist_ok=True)
    log_path = os.path.join(DEBUG_LOG_DIR, f'{run_timestamp}.txt')
    with open(log_path, 'a', encoding='utf-8') as log_file:
        original_stdout, original_stderr = sys.stdout, sys.stderr
        sys.stdout = _Tee(original_stdout, log_file)
        sys.stderr = _Tee(original_stderr, log_file)
        try:
            main(run_timestamp)
        finally:
            sys.stdout, sys.stderr = original_stdout, original_stderr


