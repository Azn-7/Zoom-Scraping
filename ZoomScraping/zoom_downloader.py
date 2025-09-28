# zoom_downloader.py
import os
import time
import shutil
from urllib.parse import urlparse, unquote
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

import zoom_utils as utils

# --- runtime toggles (edit here for each run) ---
# Set HEADLESS = False to run with visible browser
utils.HEADLESS = True

INPUT_TXT = 'zoom_links.txt'
BASE_OUTPUT_PATH = r'C:\Users\Azn\Focused\Zoom Scraping\CSIS10B'


def make_driver():
    opts = Options()
    opts.add_argument(f'--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64)')
    opts.add_argument('--window-size=1920,1080')
    if utils.HEADLESS:
        opts.add_argument('--headless=new')
    if utils.MUTE_AUDIO:
        opts.add_argument('--mute-audio')

    prefs = {
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
        "profile.default_content_setting_values.popups": 0,
        "profile.default_content_setting_values.automatic_downloads": 1
    }
    opts.add_experimental_option("prefs", prefs)
    opts.set_capability('goog:loggingPrefs', {'performance': 'ALL'})

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=opts)
    driver.set_page_load_timeout(60)
    return driver


def load_links(path):
    grouped = {}
    with open(path, 'r', encoding='utf-8') as fh:
        for line in fh:
            parts = line.strip().split('\t', 1)
            if len(parts) != 2:
                continue
            title, link = parts
            grouped.setdefault(title.strip(), []).append(link.strip())
    return grouped


def process_link(driver, title, link, idx):
    safe_title = utils.sanitize(title)
    title_dir = os.path.join(BASE_OUTPUT_PATH, safe_title)
    os.makedirs(title_dir, exist_ok=True)

    per_link_tmp = os.path.join(title_dir, f'_tmp_Video_{idx}')
    try:
        if os.path.isdir(per_link_tmp):
            shutil.rmtree(per_link_tmp)
        os.makedirs(per_link_tmp, exist_ok=True)
    except Exception:
        os.makedirs(per_link_tmp, exist_ok=True)

    utils.prepare_download_folder(driver, per_link_tmp)
    link_start = time.time()

    driver.get(link)
    time.sleep(utils.PAGE_LOAD_WAIT)
    utils.click_with_retries(driver, [
        "//button[normalize-space()='Continue']",
        "//a[normalize-space()='Continue']",
        "//*[contains(translate(.,'CONTINUE','continue'),'continue')]"
    ], timeout=4)
    time.sleep(utils.AFTER_CONTINUE_WAIT)

    host_prefers_exhaustive = 'mpc-edu.zoom.us' in link.lower()
    clicked_download = False

    if host_prefers_exhaustive:
        clicked_download = utils.search_and_force_click_download_in_all_frames(driver, per_link_tmp)
    else:
        clicked_download = utils.click_with_retries(driver, [
            "//button[@aria-label='Download']",
            "//button[contains(.,'Download')]",
            "//a[contains(.,'Download')]"
        ], timeout=6)
        if not clicked_download:
            clicked_download = utils.search_and_force_click_download_in_all_frames(driver, per_link_tmp)

    if not clicked_download:
        return {'status': 'skipped', 'elapsed': time.time() - link_start, 'files': []}

    time.sleep(1.5)

    first = utils.wait_for_first_file(per_link_tmp, timeout=utils.INACTIVITY_COUNTDOWN)
    if not first:
        first = utils.wait_for_first_file(per_link_tmp, timeout=utils.DOWNLOAD_WAIT)

    moved = utils.move_files_to_parent(per_link_tmp, title_dir)

    start = time.time()
    last_seen = set(utils.list_finished(per_link_tmp))
    quiet_start = None
    additional = []
    while True:
        current = set(utils.list_finished(per_link_tmp))
        new_files = sorted(list(current - last_seen))
        if new_files:
            moved_now = utils.move_files_to_parent(per_link_tmp, title_dir)
            for m in moved_now:
                if m not in additional:
                    additional.append(m)
            last_seen = set(utils.list_finished(per_link_tmp))
            quiet_start = None
        else:
            if quiet_start is None:
                quiet_start = time.time()
            elif time.time() - quiet_start >= utils.INACTIVITY_COUNTDOWN:
                break
        if time.time() - start >= utils.MAX_DRAIN_SECONDS:
            break
        time.sleep(0.5)

    all_moved = (moved or []) + (additional or [])

    if not all_moved:
        collected_urls = set()
        net_start = time.time()
        last_new = time.time()
        while time.time() - net_start < utils.NETWORK_FALLBACK_SECONDS:
            found = utils.collect_network_media_urls(driver)
            new = set(found) - collected_urls
            if new:
                collected_urls.update(new)
                last_new = time.time()
            if time.time() - last_new >= utils.INACTIVITY_COUNTDOWN:
                break
            time.sleep(utils.PERF_POLL_INTERVAL)

        if collected_urls:
            for url in collected_urls:
                try:
                    filename = unquote(urlparse(url).path.split('/')[-1]) or f'download_{int(time.time())}'
                    tmp_dest = os.path.join(per_link_tmp, filename)
                    utils.download_with_browser_cookies(driver, url, tmp_dest)
                except Exception:
                    pass
            moved = utils.move_files_to_parent(per_link_tmp, title_dir)
            all_moved = (moved or [])

    removed_m4a = utils.remove_m4a_files(title_dir)

    try:
        if not os.listdir(per_link_tmp):
            os.rmdir(per_link_tmp)
    except Exception:
        pass

    return {'status': 'done', 'elapsed': time.time() - link_start, 'files': all_moved, 'm4a_removed': removed_m4a}


def main():
    grouped = load_links(INPUT_TXT)
    total = sum(len(v) for v in grouped.values())
    print(f'Total links to process: {total}')

    driver = make_driver()
    times = []
    overall = {'total': 0, 'success': 0, 'failed': 0, 'skipped': 0}
    failed_links = []

    processed = 0
    for title, links in grouped.items():
        for idx, link in enumerate(links, start=1):
            processed += 1
            overall['total'] += 1
            print(f'\n[{processed}/{total}] {title} -> {link}')
            res = process_link(driver, title, link, idx)
            times.append(res.get('elapsed', 0))
            if res['status'] == 'done' and res.get('files'):
                overall['success'] += 1
                print('   ✅ Downloaded:', res.get('files'))
            elif res['status'] == 'skipped':
                overall['skipped'] += 1
                print('   ⚠️ Skipped (no download control)')
                failed_links.append({'title': title, 'link': link, 'reason': 'No download button'})
            else:
                overall['failed'] += 1
                print('   ❌ Failed to capture files')
                failed_links.append({'title': title, 'link': link, 'reason': 'Missing files after attempts'})

            avg = sum(times) / len(times) if times else 0
            remaining = max(0, total - processed)
            est = int(avg * remaining)
            print(f'   ⏱ Avg {avg:.1f}s/link — est remaining {est//60}m {est%60}s')

    driver.quit()

    print('\nSummary:')
    print(f"  Total: {overall['total']}")
    print(f"  Success: {overall['success']}")
    print(f"  Skipped: {overall['skipped']}")
    print(f"  Failed: {overall['failed']}")
    if failed_links:
        print('\nFailed links:')
        for rec in failed_links:
            print(' -', rec)


if __name__ == '__main__':
    main()