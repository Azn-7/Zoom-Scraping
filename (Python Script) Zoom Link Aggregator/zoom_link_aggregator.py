# zoom_link_aggregator.py
#
# Prototype replacement for "(Google Script) Zoom Link Aggregator/zoom_link_aggregator.gs".
# Scans a batch of Google Docs for Zoom recording links and writes them out to a CSV with the
# same six columns the Apps Script version produced -- but runs locally, so there's no Google
# account, Apps Script project, or Drive-hosted file list required. Every Doc still needs to be
# shared as "Anyone with the link can view", since this fetches them anonymously over HTTP.
#
# Requires: pip install requests beautifulsoup4

import os
import re
import csv
import time
from datetime import datetime, timezone
from email.message import Message
from urllib.parse import urlparse, parse_qs, unquote

import requests
from bs4 import BeautifulSoup

# ==============================================================================
# ======================== CONFIGURATION VARIABLES =============================
# ==============================================================================

# A local .txt file listing the Google Docs to scan, one URL per line.
DOC_LIST_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'google_docs.txt')

# Where the results get written. Which columns it contains is controlled by OUTPUT_COLUMNS below.
OUTPUT_CSV = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'zoom_links_export.csv')

# Only used to build the optional "Redirect Link" column -- only meaningful if you host your own
# copies of recordings at a BASE_PATH/DOCUMENT_NAME/... URL pattern. Leave as-is otherwise.
DOCUMENT_NAME = 'Class-of-2023'
BASE_PATH = 'https://johndoe.com/video/zoom/'

# Seconds to wait between fetching each Doc, so a large batch doesn't look like abuse to Google.
REQUEST_DELAY_SECONDS = 1

# Which columns to write to OUTPUT_CSV, and in what order. Remove any you don't want -- e.g. if
# you're feeding this straight into zoom_downloader.py, trim it down to just the 3 columns that
# actually matter there, so there's nothing extra left to copy/paste or edit out by hand:
#   OUTPUT_COLUMNS = ['Document Title', 'Hyperlink Title', 'Zoom Link']
# Default values
#   OUTPUT_COLUMNS = ['Document Title', 'Hyperlink Title', 'Zoom Link', 'Epoch', 'GMT', 'Redirect Link']
OUTPUT_COLUMNS = ['Document Title', 'Hyperlink Title', 'Zoom Link', 'Epoch', 'GMT', 'Redirect Link']

# ==============================================================================
# ========================= END OF CONFIGURATION ===============================
# ==============================================================================

_DOC_ID_RE = re.compile(r'[-\w]{25,}')
_RAW_URL_RE = re.compile(r'https?://[^\s)\]]+')
_START_TIME_RE = re.compile(r'startTime=(\d+)')


def sanitize_title(name: str) -> str:
    """Matches the .gs script's sanitizeTitle(): whitespace -> hyphens, collapsed, trimmed."""
    name = re.sub(r'\s+', '-', name.strip())
    name = re.sub(r'-+', '-', name)
    return name.strip('-')


def format_epoch_to_gmt(epoch_ms: str) -> str:
    """Matches the .gs script's formatEpochToGMT(). epoch_ms is milliseconds, like the Zoom
    "startTime" URL parameter it's extracted from."""
    try:
        dt = datetime.fromtimestamp(int(epoch_ms) / 1000, tz=timezone.utc)
    except (ValueError, TypeError, OSError):
        return ''
    return f'GMT{dt.strftime("%Y%m%d-%H%M%S")}'


def unwrap_google_redirect(url: str) -> str:
    """Google Docs' HTML export wraps external links as https://www.google.com/url?q=<target>&...
    -- pull the real target back out. Leaves already-plain URLs untouched."""
    parsed = urlparse(url)
    if parsed.netloc in ('www.google.com', 'google.com') and parsed.path == '/url':
        query_params = parse_qs(parsed.query)
        if query_params.get('q'):
            return unquote(query_params['q'][0])
    return url


def extract_doc_id(doc_url: str) -> str:
    match = _DOC_ID_RE.search(doc_url)
    return match.group(0) if match else None


def extract_title_from_content_disposition(header_value: str) -> str:
    """Google's export download names the response after the actual document, e.g.
    'attachment; filename="My Document.html"' (or the RFC 5987 filename*=UTF-8''... form for
    non-ASCII titles). Message.get_filename() understands both forms. Returns None if the header
    is missing or has no filename in it.
    """
    if not header_value:
        return None
    message = Message()
    message['content-disposition'] = header_value
    filename = message.get_filename()
    if not filename:
        return None
    if filename.lower().endswith('.html'):
        filename = filename[:-len('.html')]
    return filename or None


def fetch_doc_links(doc_url: str, session: requests.Session):
    """Fetches a public Google Doc's HTML export and extracts (document_title, zoom_rows).
    zoom_rows is a list of dicts, each keyed by all 6 possible column names (Document Title,
    Hyperlink Title, Zoom Link, Epoch, GMT, Redirect Link) regardless of OUTPUT_COLUMNS -- the
    column filtering only happens at write time, in main().
    Raises on network/HTTP errors or if the doc isn't publicly accessible.
    """
    doc_id = extract_doc_id(doc_url)
    if not doc_id:
        raise ValueError(f'Could not find a Google Doc ID in: {doc_url}')

    export_url = f'https://docs.google.com/document/d/{doc_id}/export?format=html'
    response = session.get(export_url, timeout=30)
    response.raise_for_status()

    if 'accounts.google.com' in response.url:
        raise PermissionError('Redirected to a Google sign-in page -- this Doc is probably not shared as "Anyone with the link can view".')

    soup = BeautifulSoup(response.text, 'html.parser')

    # The Content-Disposition header (Google names the export download after the real document)
    # is a more reliable source for the title than the HTML itself -- fall back to the <title>
    # tag, and finally the doc ID, only if that header isn't present or unparseable.
    raw_title = extract_title_from_content_disposition(response.headers.get('Content-Disposition'))
    if not raw_title:
        title_tag = soup.find('title')
        if title_tag and title_tag.get_text().strip():
            raw_title = title_tag.get_text()
    document_title = sanitize_title(raw_title) if raw_title else doc_id

    # Walk every link in the doc, same two-pass approach as the .gs script's walkElementTree():
    # real hyperlinks first, then plain pasted URLs that aren't already captured as a real link.
    link_map = {}
    for anchor in soup.find_all('a', href=True):
        real_url = unwrap_google_redirect(anchor['href'])
        if real_url not in link_map:
            link_map[real_url] = anchor.get_text().strip()

    for raw_url in _RAW_URL_RE.findall(soup.get_text()):
        if raw_url not in link_map:
            link_map[raw_url] = ''

    zoom_rows = []
    for url, title in link_map.items():
        if 'zoom.us' not in url.lower():
            continue
        start_time_match = _START_TIME_RE.search(url)
        epoch = start_time_match.group(1) if start_time_match else ''
        gmt = format_epoch_to_gmt(epoch) if epoch else ''
        redirect = f'{BASE_PATH}{DOCUMENT_NAME}/{document_title}/{gmt}_Recording_1920x1080.mp4' if gmt else ''
        zoom_rows.append({
            'Document Title': document_title,
            'Hyperlink Title': title,
            'Zoom Link': url,
            'Epoch': epoch,
            'GMT': gmt,
            'Redirect Link': redirect,
        })

    return document_title, zoom_rows


def main():
    if not os.path.isfile(DOC_LIST_FILE):
        print(f'[Error] {DOC_LIST_FILE} not found. Create it with one Google Doc URL per line.')
        return

    # Same convention as zoom_links.txt: only keep lines that actually look like a URL, so a
    # header line (for your own readability) gets skipped automatically rather than needing to
    # be on a specific line number.
    with open(DOC_LIST_FILE, 'r', encoding='utf-8') as file_handle:
        doc_urls = [line.strip() for line in file_handle if line.strip().lower().startswith('http')]

    print(f'Total docs to process: {len(doc_urls)}')

    session = requests.Session()
    all_rows = []
    for index, doc_url in enumerate(doc_urls, start=1):
        print(f'\n[{index}/{len(doc_urls)}] {doc_url}')
        try:
            document_title, rows = fetch_doc_links(doc_url, session)
            print(f'   Found {len(rows)} Zoom link(s) in "{document_title}"')
            all_rows.extend(rows)
        except Exception as error:
            print(f'   [Error] {error.__class__.__name__}: {error}')
        if index < len(doc_urls):
            time.sleep(REQUEST_DELAY_SECONDS)

    print(f'\nWriting columns: {", ".join(OUTPUT_COLUMNS)}')
    os.makedirs(os.path.dirname(OUTPUT_CSV), exist_ok=True)
    with open(OUTPUT_CSV, 'w', newline='', encoding='utf-8') as file_handle:
        # extrasaction='ignore' drops any of the 6 possible keys not listed in OUTPUT_COLUMNS --
        # this is what actually implements "remove a column by removing it from that list".
        writer = csv.DictWriter(file_handle, fieldnames=OUTPUT_COLUMNS, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(all_rows)

    print(f'Done. Wrote {len(all_rows)} row(s) to {OUTPUT_CSV}')


if __name__ == '__main__':
    main()
