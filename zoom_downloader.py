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

# ==============================================================================
# ======================== CONFIGURATION VARIABLES =============================
# ==============================================================================

# Set HEADLESS = Run with visible browser
utils.HEADLESS = True

# How many seconds to wait for any remaining files that are still being downloaded. By default, this is set to 20 minutes.
# This should be increased should you either download large files and have slow internet.
ACTIVE_DOWNLOAD_TIMEOUT_SECONDS = 1200

# Extensions to remove after downloads complete
# To disable deletion leave as an empty list: REMOVE_EXTENSIONS = []
REMOVE_EXTENSIONS = ['.m4a', '.vtt']   # e.g. ['.m4a', '.tmp']

INPUT_TXT = 'zoom_links.txt'
BASE_OUTPUT_PATH = r'C:\Users\Azn\Downloads\Results'

# ==============================================================================
# ========================= END OF CONFIGURATION ===============================
# ==============================================================================

def initialize_webdriver():
    """Initializes and configures the Selenium Chrome webdriver."""
    chrome_options = Options()
    chrome_options.add_argument(f'--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64)')
    chrome_options.add_argument('--window-size=1920,1080')
    if utils.HEADLESS:
        chrome_options.add_argument('--headless=new')
    if utils.MUTE_AUDIO:
        chrome_options.add_argument('--mute-audio')

    chrome_preferences = {
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
        "profile.default_content_setting_values.popups": 0,
        "profile.default_content_setting_values.automatic_downloads": 1
    }
    chrome_options.add_experimental_option("prefs", chrome_preferences)
    chrome_options.set_capability('goog:loggingPrefs', {'performance': 'ALL'})

    chrome_service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=chrome_service, options=chrome_options)
    driver.set_page_load_timeout(60)
    return driver


def parse_zoom_links_file(file_path: str) -> dict:
    """Reads the zoom links text file and groups the URLs by their associated titles."""
    links_by_title = {}
    with open(file_path, 'r', encoding='utf-8') as file_handle:
        for line in file_handle:
            split_line = line.strip().split('\t', 1)
            if len(split_line) != 2:
                continue
            title, link = split_line
            links_by_title.setdefault(title.strip(), []).append(link.strip())
    return links_by_title


def download_zoom_recording(driver, title: str, link: str, file_index: int) -> dict:
    """Navigates to the Zoom recording payload, detects the download button, and extracts files locally."""
    safe_title = utils.sanitize(title).replace(' ', '_')
    destination_directory = BASE_OUTPUT_PATH
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

    driver.get(link)
    utils.click_with_retries(driver, [
        "//button[normalize-space()='Continue']",
        "//a[normalize-space()='Continue']",
        "//*[contains(translate(.,'CONTINUE','continue'),'continue')]"
    ], timeout=max(utils.PAGE_LOAD_WAIT, 10))

    host_prefers_exhaustive = 'mpc-edu.zoom.us' in link.lower()
    clicked_download = False

    if host_prefers_exhaustive:
        end_time = time.time() + 15
        while time.time() < end_time:
            clicked_download = utils.force_click_download_button(driver, temporary_download_dir)
            if clicked_download:
                break
            time.sleep(1.0)
    else:
        clicked_download = utils.click_with_retries(driver, [
            "//button[@aria-label='Download']",
            "//button[contains(.,'Download')]",
            "//a[contains(.,'Download')]"
        ], timeout=max(utils.AFTER_CONTINUE_WAIT + 6, 15))
        if not clicked_download:
            clicked_download = utils.force_click_download_button(driver, temporary_download_dir)

    if not clicked_download:
        return {'status': 'skipped', 'elapsed': time.time() - link_start_time, 'files': [], 'temporary_download_dir': temporary_download_dir, 'destination_directory': destination_directory, 'safe_title': safe_title}

    time.sleep(1.5)

    completed_wait = utils.wait_for_initial_download(temporary_download_dir, timeout_seconds=utils.INACTIVITY_COUNTDOWN)
    if not completed_wait:
        completed_wait = utils.wait_for_initial_download(temporary_download_dir, timeout_seconds=utils.DOWNLOAD_WAIT)

    moved_files = utils.move_downloads_to_destination(temporary_download_dir, destination_directory, title_prefix=safe_title)

    observation_start_time = time.time()
    previously_seen_files = set(utils.get_completed_downloads(temporary_download_dir))
    silence_start_time = None
    additional_files_moved = []
    while True:
        currently_seen_files = set(utils.get_completed_downloads(temporary_download_dir))
        newly_completed_files = sorted(list(currently_seen_files - previously_seen_files))
        if newly_completed_files:
            moved_in_current_tick = utils.move_downloads_to_destination(temporary_download_dir, destination_directory, title_prefix=safe_title)
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
            moved_files = utils.move_downloads_to_destination(temporary_download_dir, destination_directory, title_prefix=safe_title)
            all_moved_files = (moved_files or [])

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

    return {'status': 'done', 'elapsed': time.time() - link_start_time, 'files': all_moved_files, 'removed': file_extensions_removed, 'temporary_download_dir': temporary_download_dir, 'destination_directory': destination_directory, 'safe_title': safe_title}


def main():
    links_by_title = parse_zoom_links_file(INPUT_TXT)
    total_links_count = sum(len(links) for links in links_by_title.values())
    print(f'Total links to process: {total_links_count}')

    driver = initialize_webdriver()
    elapsed_times = []
    overall_progress = {'total': 0, 'success': 0, 'failed': 0, 'skipped': 0}
    unsuccessful_links = []

    links_processed_count = 0
    last_temporary_dir = None
    last_destination_dir = None
    last_title_prefix = None
    for title, links in links_by_title.items():
        for index, link in enumerate(links, start=1):
            links_processed_count += 1
            overall_progress['total'] += 1
            print(f'\n[{links_processed_count}/{total_links_count}] {title} -> {link}')
            download_result = download_zoom_recording(driver, title, link, index)
            elapsed_times.append(download_result.get('elapsed', 0))
            last_temporary_dir = download_result.get('temporary_download_dir') or last_temporary_dir
            last_destination_dir = download_result.get('destination_directory') or last_destination_dir
            last_title_prefix = download_result.get('safe_title') or last_title_prefix

            if download_result['status'] == 'done' and download_result.get('files'):
                overall_progress['success'] += 1
                print('   [Success] Downloaded:', download_result.get('files'))
            elif download_result['status'] == 'skipped':
                overall_progress['skipped'] += 1
                print('   [Skipped] Skipped (no download control)')
                unsuccessful_links.append({'title': title, 'link': link, 'reason': 'No download button'})
            else:
                overall_progress['failed'] += 1
                print('   [Failed] Failed to capture files')
                unsuccessful_links.append({'title': title, 'link': link, 'reason': 'Missing files after attempts'})

            average_time_per_link = sum(elapsed_times) / len(elapsed_times) if elapsed_times else 0
            remaining_links_count = max(0, total_links_count - links_processed_count)
            estimated_remaining_seconds = int(average_time_per_link * remaining_links_count)
            print(f'   [Time] Avg {average_time_per_link:.1f}s/link — est remaining {estimated_remaining_seconds//60}m {estimated_remaining_seconds%60}s')

    # Before quitting browser, ensure last link's active downloads completed and move remaining files
    try:
        if ACTIVE_DOWNLOAD_TIMEOUT_SECONDS > 0 and last_temporary_dir and os.path.isdir(last_temporary_dir):
            utils.wait_for_active_downloads(last_temporary_dir, timeout=ACTIVE_DOWNLOAD_TIMEOUT_SECONDS)

        # Move any files that finished after the wait into the destination folder
        if last_temporary_dir and last_destination_dir and os.path.isdir(last_temporary_dir):
            moved_after_wait = utils.move_downloads_to_destination(last_temporary_dir, last_destination_dir, title_prefix=last_title_prefix)
            if moved_after_wait:
                print('   [Moved] Moved files to title folder after final wait:', moved_after_wait)

            # conditional final cleanup: only run if user configured extensions to remove
            if REMOVE_EXTENSIONS:
                removed_after_wait = utils.remove_files_by_extensions(last_destination_dir, REMOVE_EXTENSIONS)
                for removed_file in removed_after_wait:
                    print('   [Removed] Removed from title folder after final wait:', removed_file)

            # try to remove tmp folder if empty
            try:
                if not os.listdir(last_temporary_dir):
                    os.rmdir(last_temporary_dir)
            except Exception:
                pass

    except Exception:
        pass

    driver.quit()

    print('\nSummary:')
    print(f"  Total: {overall_progress['total']}")
    print(f"  Success: {overall_progress['success']}")
    print(f"  Skipped: {overall_progress['skipped']}")
    print(f"  Failed: {overall_progress['failed']}")
    if unsuccessful_links:
        print('\nFailed links:')
        for failed_link_record in unsuccessful_links:
            print(' -', failed_link_record)


if __name__ == '__main__':
    main()


