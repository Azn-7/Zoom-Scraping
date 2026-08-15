# zoom_utils.py
import os
import time
import json
import re
import filecmp
import requests
from urllib.parse import urlparse, unquote
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains

# ==============================================================================
# ======================== CONFIGURATION VARIABLES =============================
# ==============================================================================

# Configuration defaults (override from runner if needed)
HEADLESS = True
MUTE_AUDIO = True

# Max seconds to poll the page (including iframes) for either the "deleted" message or a
# Continue/Download control before giving up on detecting it directly. Polling exits as soon as
# either shows up, so a fast-loading page never actually waits this long — this is just the ceiling
# for a slow one.
PAGE_DETECT_TIMEOUT = 30

PAGE_LOAD_WAIT = 5
AFTER_CONTINUE_WAIT = 2
CLICK_RETRY_ATTEMPTS = 6
CLICK_RETRY_PAUSE = 0.8

INACTIVITY_COUNTDOWN = 10
DOWNLOAD_WAIT = 60
MAX_DRAIN_SECONDS = 120
NETWORK_FALLBACK_SECONDS = 60
PERF_POLL_INTERVAL = 0.5


# ==============================================================================
# ========================= END OF CONFIGURATION ===============================
# ==============================================================================

_net_re = re.compile(r'\.(mp4|vtt)(\?|$)', re.IGNORECASE)
_expected_count_re = re.compile(r'\(\s*(\d+)\s*files?\s*\)', re.IGNORECASE)


def parse_expected_file_count(text: str):
    """Extracts the file count from Zoom's "Download (N files)" label, or None if not present/parseable."""
    if not text:
        return None
    match = _expected_count_re.search(text)
    return int(match.group(1)) if match else None

def sanitize(name):
    # Replace spaces with underscores
    name = name.replace(' ', '_')
    # Strip characters that are illegal in Windows filenames to prevent crashes, but carefully leave everything else alone (like commas)
    return strip_illegal_chars(name)


def strip_illegal_chars(name):
    """Strips characters that are illegal in Windows filenames, without touching spaces (unlike sanitize())."""
    return re.sub(r'[<>:"/\\|?*]', '', name).strip()


def save_debug_screenshot(driver, output_dir, label):
    """Saves a screenshot of the current page to output_dir, named after label (illegal characters
    stripped, extension added). Best-effort -- never raises; returns the saved path, or None if it
    couldn't be saved (e.g. the browser session is already gone).
    """
    try:
        os.makedirs(output_dir, exist_ok=True)
        screenshot_path = os.path.join(output_dir, f'{strip_illegal_chars(label)}.png')
        driver.save_screenshot(screenshot_path)
        return screenshot_path
    except Exception:
        return None


def load_finished_links(path) -> set:
    """Reads a newline-separated list of links from path into a set. Returns an empty set if the
    file doesn't exist yet (e.g. first run)."""
    if not os.path.isfile(path):
        return set()
    with open(path, 'r', encoding='utf-8') as file_handle:
        return {line.strip() for line in file_handle if line.strip()}


def append_finished_link(path, link, already_finished: set):
    """Appends link to the finished-links file at path and to the already_finished set, unless it's
    already recorded there. Writes (and flushes) immediately so progress survives a crash mid-run.
    """
    if link in already_finished:
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'a', encoding='utf-8') as file_handle:
        file_handle.write(link + '\n')
    already_finished.add(link)


def write_grouped_links_file(path, entries):
    """Writes entries (each a dict with 'document', 'title', 'link', and optionally 'status_label')
    to path, grouped under "-= Document Title =-" headers in first-seen order, with a blank line
    between groups. Entries with no document (the legacy two-column format) are grouped under
    "-= (No Document) =-". Each line under a group reads "(status_label) Title: Link" (just
    "Title: Link" if status_label isn't given). Does nothing if entries is empty.
    """
    if not entries:
        return
    groups = {}
    group_order = []
    for entry in entries:
        group_key = entry.get('document') or '(No Document)'
        if group_key not in groups:
            groups[group_key] = []
            group_order.append(group_key)
        groups[group_key].append(entry)

    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as file_handle:
        for index, group_key in enumerate(group_order):
            if index > 0:
                file_handle.write('\n')
            file_handle.write(f'-= {group_key} =-\n')
            for entry in groups[group_key]:
                status_prefix = f"({entry['status_label']}) " if entry.get('status_label') else ''
                file_handle.write(f"{status_prefix}{entry['title']}: {entry['link']}\n")


def collapse_spacing(name):
    """Squashes repeated spaces down to one. A custom FILENAME_TEMPLATE can end up with double spaces
    when an optional token like {special} renders empty — this just cleans that up."""
    return re.sub(r' {2,}', ' ', name).strip()


def strip_empty_parens(name):
    """Removes "()" left behind when a template wraps an optional token, like {special}, in literal
    parentheses and that token renders empty."""
    return re.sub(r'\(\s*\)', '', name)


def prepare_download_folder(driver, path):
    os.makedirs(path, exist_ok=True)
    driver.execute_cdp_cmd("Browser.setDownloadBehavior",
                           {"behavior": "allow", "downloadPath": path, "eventsEnabled": True})


def click_with_retries(driver, xpaths, timeout=5, attempts=None, pause=None):
    attempts = attempts or CLICK_RETRY_ATTEMPTS
    pause = pause or CLICK_RETRY_PAUSE
    for _ in range(attempts):
        for xp in xpaths:
            try:
                wait = WebDriverWait(driver, timeout)
                elem = wait.until(EC.element_to_be_clickable((By.XPATH, xp)))
                driver.execute_script("arguments[0].scrollIntoView({block:'center', inline:'center'});", elem)
                time.sleep(0.05)
                try:
                    elem.click()
                    return True
                except Exception:
                    try:
                        driver.execute_script("arguments[0].click();", elem)
                        return True
                    except Exception:
                        pass
            except Exception:
                pass
        time.sleep(pause)
    return False


# Matches any element (not just <button>/<a> -- Zoom's controls are sometimes a plain <div>/<span>
# with a click handler), by text, aria-label, or title, same idiom as force_click_by_keyword's
# proven-working selectors. Checked as two separate xpaths (rather than one combined one) so the
# caller can tell which kind of control it actually found.
_DOWNLOAD_READY_XPATH = (
    "//*[contains(translate(normalize-space(text()),'DOWNLOAD','download'),'download')]"
    " | //*[contains(translate(@aria-label,'DOWNLOAD','download'),'download')]"
    " | //*[contains(translate(@title,'DOWNLOAD','download'),'download')]"
)
_CONTINUE_READY_XPATH = (
    "//*[contains(translate(normalize-space(text()),'CONTINUE','continue'),'continue')]"
    " | //*[contains(translate(@aria-label,'CONTINUE','continue'),'continue')]"
    " | //*[contains(translate(@title,'CONTINUE','continue'),'continue')]"
)


def _find_ready_control_kind(driver):
    """Checks the current frame only. Returns 'download', 'continue', or None."""
    if driver.find_elements(By.XPATH, _DOWNLOAD_READY_XPATH):
        return 'download'
    if driver.find_elements(By.XPATH, _CONTINUE_READY_XPATH):
        return 'continue'
    return None


def wait_for_page_ready(driver, timeout, deleted_text):
    """Polls the page every ~0.5s, checking iframes too, until deleted_text appears or a Continue/
    Download control shows up anywhere -- or timeout runs out. Doesn't click anything; just shortens
    the wait before the caller's own click logic takes over. Always leaves the driver on the default
    content when it returns.

    Returns 'deleted', 'download', 'continue', or None (timed out without finding anything).
    """
    deadline = time.time() + timeout
    try:
        while time.time() < deadline:
            try:
                driver.switch_to.default_content()
                if deleted_text in driver.page_source:
                    return 'deleted'
                found = _find_ready_control_kind(driver)
                if found:
                    return found
                for frame in driver.find_elements(By.TAG_NAME, 'iframe'):
                    try:
                        driver.switch_to.default_content()
                        driver.switch_to.frame(frame)
                        found = _find_ready_control_kind(driver)
                        if found:
                            return found
                    except Exception:
                        continue
            except Exception:
                pass
            time.sleep(0.5)
    finally:
        try:
            driver.switch_to.default_content()
        except Exception:
            pass
    return None


def get_completed_downloads(folder: str) -> list:
    """Returns a list of completed downloads in the specified folder, ignoring partial downloads (.crdownload)."""
    try:
        return [file_name for file_name in os.listdir(folder) if not file_name.endswith('.crdownload')]
    except Exception:
        return []


def wait_for_initial_download(temp_folder: str, timeout_seconds: int) -> list:
    """Waits for the first completed file to appear in the temp folder within the specified timeout."""
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        completed_files = get_completed_downloads(temp_folder)
        if completed_files:
            return completed_files
        time.sleep(0.5)
    return []


# Fallback used whenever filename_template is None, or fails to render (e.g. a typo'd token).
DEFAULT_FILENAME_TEMPLATE = "{title} ({special}) ({original}){ext}"


def move_downloads_to_destination(source_folder: str, destination_folder: str, title_prefix: str = None, rename_exact: bool = False, filename_template: str = None) -> list:
    """Moves completed downloads from the source folder to the destination folder, optionally renaming them.

    When title_prefix is given, the file is renamed using filename_template (see FILENAME_TEMPLATE in
    zoom_downloader.py for the available tokens and examples), falling back to DEFAULT_FILENAME_TEMPLATE
    if none is given or it fails to render.
    """
    moved_files = []
    for file_name in list(os.listdir(source_folder)):
        if file_name.endswith('.crdownload'):
            continue

        source_path = os.path.join(source_folder, file_name)
        base_filename = file_name

        if title_prefix:
            original_base_name, extension = os.path.splitext(file_name)
            if re.search(r'1920x1080', file_name, re.IGNORECASE):
                special_tag = 'Video'
            elif re.search(r'640x360', file_name, re.IGNORECASE):
                special_tag = 'Camera'
            else:
                special_tag = ''
            template_tokens = {'title': title_prefix, 'special': special_tag, 'original': original_base_name, 'ext': extension}
            try:
                base_filename = (filename_template or DEFAULT_FILENAME_TEMPLATE).format(**template_tokens)
            except Exception:
                base_filename = DEFAULT_FILENAME_TEMPLATE.format(**template_tokens)
            base_filename = collapse_spacing(strip_empty_parens(strip_illegal_chars(base_filename)))

        destination_path = os.path.join(destination_folder, base_filename)
        
        # Handle filename collisions by appending __dup{counter}
        if os.path.exists(destination_path):
            base_name, extension = os.path.splitext(base_filename)
            collision_counter = 1
            candidate_name = f"{base_name}__dup{collision_counter}{extension}"
            candidate_path = os.path.join(destination_folder, candidate_name)
            while os.path.exists(candidate_path):
                collision_counter += 1
                candidate_name = f"{base_name}__dup{collision_counter}{extension}"
                candidate_path = os.path.join(destination_folder, candidate_name)
            destination_path = candidate_path
            base_filename = candidate_name
            
        try:
            os.replace(source_path, destination_path)
            moved_files.append(base_filename)
        except Exception:
            try:
                # Fallback to manual copy-delete if os.replace fails
                with open(source_path, 'rb') as read_file, open(destination_path, 'wb') as write_file:
                    write_file.write(read_file.read())
                os.remove(source_path)
                moved_files.append(base_filename)
            except Exception:
                pass
    return moved_files


def remove_files_by_extensions(folder, exts):
    """
    Remove files in folder whose names end with any extension in exts.
    exts: list of strings like ['.m4a', '.tmp'] (case-insensitive).
    Returns list of removed filenames.
    """
    removed = []
    if not os.path.isdir(folder):
        return removed
    normalized = [e.lower() for e in exts]
    for f in list(os.listdir(folder)):
        fname_lower = f.lower()
        for ext in normalized:
            if fname_lower.endswith(ext):
                try:
                    os.remove(os.path.join(folder, f))
                    removed.append(f)
                except Exception:
                    pass
                break
    return removed


def discard_duplicate_files(folder: str, compare_against_paths: list) -> list:
    """Deletes completed downloads in folder that are byte-for-byte identical to any file in compare_against_paths.

    Used after a retry-download: rather than letting a redundant re-download of a file we already
    successfully captured pile up as a "__dup1" copy (or worse, get treated as a "new" file under a
    naming scheme that isn't fully deterministic), compare actual file content and drop true duplicates
    outright, keeping only files that are genuinely new.
    """
    discarded = []
    existing_paths = [path for path in compare_against_paths if os.path.isfile(path)]
    if not existing_paths:
        return discarded
    for file_name in get_completed_downloads(folder):
        candidate_path = os.path.join(folder, file_name)
        for existing_path in existing_paths:
            try:
                if os.path.getsize(candidate_path) != os.path.getsize(existing_path):
                    continue
                if filecmp.cmp(candidate_path, existing_path, shallow=False):
                    os.remove(candidate_path)
                    discarded.append(file_name)
                    break
            except Exception:
                continue
    return discarded


def extract_media_urls_from_network_logs(driver) -> list:
    """Parses Chrome's performance logs to identify any embedded media URLs (like .mp4 or .vtt)."""
    media_urls = set()
    try:
        network_logs = driver.get_log('performance')
    except Exception:
        return []
        
    for log_entry in network_logs:
        try:
            log_message = json.loads(log_entry['message'])['message']
            request_method = log_message.get('method')
            if request_method in ('Network.responseReceived', 'Network.requestWillBeSent'):
                request_params = log_message.get('params', {})
                response_data = request_params.get('response') or {}
                extracted_url = response_data.get('url', '') or request_params.get('request', {}).get('url', '')
                if extracted_url and _net_re.search(extracted_url):
                    media_urls.add(extracted_url)
        except Exception:
            continue
    return list(media_urls)


def download_with_browser_cookies(driver, url, dest_path, timeout=120):
    s = requests.Session()
    for c in driver.get_cookies():
        domain = c.get('domain')
        try:
            s.cookies.set(c['name'], c['value'], domain=domain, path=c.get('path', '/'))
        except Exception:
            s.cookies.set(c['name'], c['value'])
    r = s.get(url, stream=True, timeout=timeout)
    r.raise_for_status()
    with open(dest_path, 'wb') as fh:
        for chunk in r.iter_content(1024 * 64):
            if chunk:
                fh.write(chunk)
    return True

def force_click_by_keyword(driver, keyword: str):
    """Searches through all open iframes on the current page to locate and forcefully click a control
    whose text/aria-label/title contains keyword (case-insensitive) -- e.g. keyword='download' or
    keyword='continue'.

    Returns a (clicked, expected_file_count) tuple. expected_file_count is parsed from the clicked
    element's own text/label (e.g. Zoom's "Download (4 files)"), or None if it isn't present there
    (which is the normal case for anything other than a Download control).
    """
    keyword_upper = keyword.upper()
    keyword_lower = keyword.lower()
    iframes = driver.find_elements(By.TAG_NAME, 'iframe')
    frame_contexts = [(None, None)] + [(i, frame) for i, frame in enumerate(iframes)]
    for idx, frame in frame_contexts:
        try:
            if frame is None:
                driver.switch_to.default_content()
            else:
                driver.switch_to.default_content()
                driver.switch_to.frame(frame)
            time.sleep(0.05)

            candidate_xpaths = [
                f"//*[contains(translate(normalize-space(text()),'{keyword_upper}','{keyword_lower}'),'{keyword_lower}')]",
                f"//*[contains(translate(@aria-label,'{keyword_upper}','{keyword_lower}'),'{keyword_lower}')]",
                f"//button[contains(translate(.,'{keyword_upper}','{keyword_lower}'),'{keyword_lower}')]",
                f"//a[contains(translate(.,'{keyword_upper}','{keyword_lower}'),'{keyword_lower}')]",
                f"//*[contains(translate(@title,'{keyword_upper}','{keyword_lower}'),'{keyword_lower}')]"
            ]

            button_candidates = []
            for current_xpath in candidate_xpaths:
                try:
                    elements = driver.find_elements(By.XPATH, current_xpath)
                    for element in elements:
                        try:
                            element_text = (element.text or element.get_attribute('aria-label') or element.get_attribute('title') or '').strip()
                        except Exception:
                            element_text = ''
                        if element_text:
                            button_candidates.append((element, element_text))
                except Exception:
                    continue

            seen_elements = set()
            unique_candidates = []
            for element, element_text in button_candidates:
                try:
                    element_key = (element.tag_name, (element.get_attribute('id') or ''), (element.get_attribute('class') or ''), (element.text or '')[:60])
                except Exception:
                    element_key = (element.tag_name, '')
                if element_key in seen_elements:
                    continue
                seen_elements.add(element_key)
                unique_candidates.append((element, element_text))

            if not unique_candidates:
                driver.switch_to.default_content()
                continue

            for element, element_text in unique_candidates:
                expected_file_count = parse_expected_file_count(element_text)

                try:
                    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", element)
                    time.sleep(0.05)
                    element.click()
                    driver.switch_to.default_content()
                    return True, expected_file_count
                except Exception:
                    pass

                try:
                    driver.execute_script("arguments[0].click();", element)
                    driver.switch_to.default_content()
                    return True, expected_file_count
                except Exception:
                    pass

                try:
                    ActionChains(driver).move_to_element(element).pause(0.05).click(element).perform()
                    driver.switch_to.default_content()
                    return True, expected_file_count
                except Exception:
                    pass

                try:
                    driver.execute_script("""
                    const el = arguments[0];
                    const rect = el.getBoundingClientRect();
                    const x = rect.left + rect.width/2;
                    const y = rect.top + rect.height/2;
                    ['pointerdown','pointerup','click'].forEach(evt=>{
                      el.dispatchEvent(new MouseEvent(evt,{bubbles:true,cancelable:true,clientX:x,clientY:y}));
                    });
                    """, element)
                    driver.switch_to.default_content()
                    return True, expected_file_count
                except Exception:
                    pass

            driver.switch_to.default_content()
        except Exception:
            try:
                driver.switch_to.default_content()
            except Exception:
                pass
            continue

    return False, None


def wait_for_active_downloads(folder, timeout=180, poll=1.5):
    """
    Wait until Chrome '.crdownload' partial files in folder disappear or timeout.
    Returns True if no active partials remain, False if timeout reached.
    """
    if not folder or not os.path.isdir(folder):
        return True
    print(f'   [Wait] Waiting for active downloads to finish in {folder} (max {timeout}s)...')
    deadline = time.time() + timeout
    try:
        while time.time() < deadline:
            partials = [f for f in os.listdir(folder) if f.endswith('.crdownload')]
            if not partials:
                print('   [Success] All downloads completed.')
                return True
            time.sleep(poll)
    except Exception:
        pass
    print('   [Warning] Timeout reached — some downloads may still be incomplete.')
    return False
