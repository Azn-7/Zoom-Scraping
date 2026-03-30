# zoom_utils.py
import os
import time
import json
import re
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

def sanitize(name):
    # Replace spaces with underscores
    name = name.replace(' ', '_')
    # Strip characters that are illegal in Windows filenames to prevent crashes, but carefully leave everything else alone (like commas)
    return re.sub(r'[<>:"/\\|?*]', '', name).strip()


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


def move_downloads_to_destination(source_folder: str, destination_folder: str, title_prefix: str = None) -> list:
    """Moves completed downloads from the source folder to the destination folder, optionally renaming them."""
    moved_files = []
    for file_name in list(os.listdir(source_folder)):
        if file_name.endswith('.crdownload'):
            continue
            
        source_path = os.path.join(source_folder, file_name)
        base_filename = file_name
        
        if title_prefix:
            # Try to replace the standard Zoom prefix 'GMT<timestamp>..._Recording' with our title_prefix
            new_filename = re.sub(r'^GMT\d{8}-\d+(?:_Recording)?', title_prefix, base_filename, flags=re.IGNORECASE)
            if new_filename == base_filename:
                # If the string wasn't modified (doesn't follow standard Zoom pattern), default to prepending
                base_filename = f"{title_prefix}_{base_filename}"
            else:
                base_filename = new_filename
                
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

def force_click_download_button(driver, temp_folder: str) -> bool:
    """Searches through all open iframes on the current page to locate and forcefully click the download button."""
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

            download_button_xpaths = [
                "//*[contains(translate(normalize-space(text()),'DOWNLOAD','download'),'download')]",
                "//*[contains(translate(@aria-label,'DOWNLOAD','download'),'download')]",
                "//button[contains(translate(.,'DOWNLOAD','download'),'download')]",
                "//a[contains(translate(.,'DOWNLOAD','download'),'download')]",
                "//*[contains(translate(@title,'DOWNLOAD','download'),'download')]"
            ]

            button_candidates = []
            for current_xpath in download_button_xpaths:
                try:
                    elements = driver.find_elements(By.XPATH, current_xpath)
                    for element in elements:
                        try:
                            element_text = (element.text or element.get_attribute('aria-label') or element.get_attribute('title') or '').strip()
                        except Exception:
                            element_text = ''
                        if element_text:
                            button_candidates.append(element)
                except Exception:
                    continue

            seen_elements = set()
            unique_candidates = []
            for element in button_candidates:
                try:
                    element_key = (element.tag_name, (element.get_attribute('id') or ''), (element.get_attribute('class') or ''), (element.text or '')[:60])
                except Exception:
                    element_key = (element.tag_name, '')
                if element_key in seen_elements:
                    continue
                seen_elements.add(element_key)
                unique_candidates.append(element)

            if not unique_candidates:
                driver.switch_to.default_content()
                continue

            for element in unique_candidates:
                try:
                    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", element)
                    time.sleep(0.05)
                    element.click()
                    driver.switch_to.default_content()
                    return True
                except Exception:
                    pass

                try:
                    driver.execute_script("arguments[0].click();", element)
                    driver.switch_to.default_content()
                    return True
                except Exception:
                    pass

                try:
                    ActionChains(driver).move_to_element(element).pause(0.05).click(element).perform()
                    driver.switch_to.default_content()
                    return True
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
                    return True
                except Exception:
                    pass

            driver.switch_to.default_content()
        except Exception:
            try:
                driver.switch_to.default_content()
            except Exception:
                pass
            continue

    return False


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
