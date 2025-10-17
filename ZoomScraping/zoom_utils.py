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

_net_re = re.compile(r'\.(mp4|vtt)(\?|$)', re.IGNORECASE)

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


def sanitize(name):
    return ''.join(c if (c.isalnum() or c in (' ', '_', '-')) else '_' for c in name).strip()


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
                time.sleep(0.12)
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


def list_finished(folder):
    try:
        return [f for f in os.listdir(folder) if not f.endswith('.crdownload')]
    except Exception:
        return []


def wait_for_first_file(src_tmp, timeout):
    deadline = time.time() + timeout
    while time.time() < deadline:
        finished = list_finished(src_tmp)
        if finished:
            return finished
        time.sleep(0.5)
    return []


def move_files_to_parent(src_folder, dest_folder):
    moved = []
    for fname in list(os.listdir(src_folder)):
        if fname.endswith('.crdownload'):
            continue
        src = os.path.join(src_folder, fname)
        base_fname = fname
        dest_path = os.path.join(dest_folder, base_fname)
        if os.path.exists(dest_path):
            base, ext = os.path.splitext(base_fname)
            counter = 1
            candidate = f"{base}__dup{counter}{ext}"
            dest_candidate = os.path.join(dest_folder, candidate)
            while os.path.exists(dest_candidate):
                counter += 1
                candidate = f"{base}__dup{counter}{ext}"
                dest_candidate = os.path.join(dest_folder, candidate)
            dest_path = dest_candidate
            base_fname = candidate
        try:
            os.replace(src, dest_path)
            moved.append(base_fname)
        except Exception:
            try:
                with open(src, 'rb') as r, open(dest_path, 'wb') as w:
                    w.write(r.read())
                os.remove(src)
                moved.append(base_fname)
            except Exception:
                pass
    return moved


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


def collect_network_media_urls(driver):
    urls = set()
    try:
        logs = driver.get_log('performance')
    except Exception:
        return []
    for entry in logs:
        try:
            msg = json.loads(entry['message'])['message']
            method = msg.get('method')
            if method in ('Network.responseReceived', 'Network.requestWillBeSent'):
                params = msg.get('params', {})
                resp = params.get('response') or {}
                url = resp.get('url', '') or params.get('request', {}).get('url', '')
                if url and _net_re.search(url):
                    urls.add(url)
        except Exception:
            continue
    return list(urls)


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


def snapshot_page(driver, dest_folder):
    # snapshots removed completely; this function kept as no-op for compatibility
    return


def search_and_force_click_download_in_all_frames(driver, tmp_folder):
    frames = driver.find_elements(By.TAG_NAME, 'iframe')
    contexts = [(None, None)] + [(i, f) for i, f in enumerate(frames)]
    for idx, fr in contexts:
        try:
            if fr is None:
                driver.switch_to.default_content()
            else:
                driver.switch_to.default_content()
                driver.switch_to.frame(fr)
            time.sleep(0.35)

            xpaths = [
                "//*[contains(translate(normalize-space(text()),'DOWNLOAD','download'),'download')]",
                "//*[contains(translate(@aria-label,'DOWNLOAD','download'),'download')]",
                "//button[contains(translate(.,'DOWNLOAD','download'),'download')]",
                "//a[contains(translate(.,'DOWNLOAD','download'),'download')]",
                "//*[contains(translate(@title,'DOWNLOAD','download'),'download')]"
            ]

            candidates = []
            for xp in xpaths:
                try:
                    els = driver.find_elements(By.XPATH, xp)
                    for e in els:
                        try:
                            txt = (e.text or e.get_attribute('aria-label') or e.get_attribute('title') or '').strip()
                        except Exception:
                            txt = ''
                        if txt:
                            candidates.append(e)
                except Exception:
                    continue

            seen = set()
            unique = []
            for e in candidates:
                try:
                    key = (e.tag_name, (e.get_attribute('id') or ''), (e.get_attribute('class') or ''), (e.text or '')[:60])
                except Exception:
                    key = (e.tag_name, '')
                if key in seen:
                    continue
                seen.add(key)
                unique.append(e)

            if not unique:
                driver.switch_to.default_content()
                continue

            for e in unique:
                try:
                    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", e)
                    time.sleep(0.12)
                    e.click()
                    driver.switch_to.default_content()
                    return True
                except Exception:
                    pass

                try:
                    driver.execute_script("arguments[0].click();", e)
                    driver.switch_to.default_content()
                    return True
                except Exception:
                    pass

                try:
                    ActionChains(driver).move_to_element(e).pause(0.12).click(e).perform()
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
                    """, e)
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
    print(f'   ⏳ Waiting for active downloads to finish in {folder} (max {timeout}s)...')
    deadline = time.time() + timeout
    try:
        while time.time() < deadline:
            partials = [f for f in os.listdir(folder) if f.endswith('.crdownload')]
            if not partials:
                print('   ✅ All downloads completed.')
                return True
            time.sleep(poll)
    except Exception:
        pass
    print('   ⚠️ Timeout reached — some downloads may still be incomplete.')
    return False
