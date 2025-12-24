import requests
from bs4 import BeautifulSoup
import re
import time
from datetime import datetime
from typing import List, Dict, Optional
from database import posting_exists, posting_exists_recent, add_posting

GRADCAFE_BASE_URL = "https://www.thegradcafe.com/survey/?institution=&program=economics"

def _normalize_date(date_str: str) -> str:
    if not date_str:
        return ""

    date_str = date_str.strip()
    formats = [
        "%b %d, %Y",
        "%B %d, %Y",
        "%m/%d/%Y",
        "%Y-%m-%d",
    ]
    for fmt in formats:
        try:
            parsed = datetime.strptime(date_str, fmt)
            return parsed.strftime("%Y-%m-%d")
        except ValueError:
            continue

    return date_str

def scrape_gradcafe_page(page: int = 1) -> List[Dict]:
    url = GRADCAFE_BASE_URL if page == 1 else f"{GRADCAFE_BASE_URL}&page={page}"

    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
    except requests.RequestException as e:
        print(f"Error fetching GradCafe page {page}: {e}")
        return []

    soup = BeautifulSoup(response.content, 'html.parser')
    rows = soup.find_all('tr')

    if not rows:
        print("No table rows found on page")
        return []

    postings = []
    i = 1

    while i < len(rows):
        row = rows[i]
        cells = row.find_all('td')

        if len(cells) != 5:
            i += 1
            continue

        school = cells[0].get_text(strip=True)
        program_raw = cells[1].get_text(strip=True)
        date_added = cells[2].get_text(strip=True)
        date_added_iso = _normalize_date(date_added)
        decision = cells[3].get_text(strip=True)

        gradcafe_id = ""
        link = cells[4].find('a')
        if link and link.get('href'):
            href = link.get('href')
            id_match = re.search(r'/result/(\d+)', href)
            if id_match:
                gradcafe_id = id_match.group(1)

        if not school or not gradcafe_id:
            i += 1
            continue

        program_match = re.search(r'(.+?)(PhD|Masters|Master|Doctorate)', program_raw)
        program = program_match.group(1).strip() if program_match else program_raw
        degree = program_match.group(2) if program_match else ""

        details_row = rows[i + 1] if i + 1 < len(rows) else None
        season = ""
        status = ""
        gpa = None
        gre_quant = None
        gre_verbal = None
        gre_aw = None
        comment = ""

        if details_row and details_row.get('class') and 'tw-border-none' in details_row.get('class'):
            # Find all badge divs containing details
            badge_divs = details_row.find_all('div', class_='tw-inline-flex')

            for badge in badge_divs:
                badge_text = badge.get_text(strip=True)

                # Season
                if not season:
                    season_match = re.search(r'(Fall|Spring|Summer|Winter)\s+\d{4}', badge_text)
                    if season_match:
                        season = season_match.group(0)
                        continue

                # Status
                if not status:
                    if badge_text in ['International', 'American', 'Other']:
                        status = badge_text
                        continue

                # GPA - match "GPA X.XX" or "GPA XX"
                if not gpa:
                    gpa_match = re.search(r'GPA\s+([\d.]+)', badge_text)
                    if gpa_match:
                        gpa = gpa_match.group(1)
                        continue

                # GRE patterns - handle multiple formats
                if badge_text.startswith('GRE'):
                    # Format: "GRE V 170" or "GRE AW 6.0"
                    gre_labeled = re.search(r'GRE\s+(V|AW|Q)\s+([\d.]+)', badge_text)
                    if gre_labeled:
                        component = gre_labeled.group(1)
                        score = gre_labeled.group(2)
                        if component == 'Q':
                            gre_quant = score
                        elif component == 'V':
                            gre_verbal = score
                        elif component == 'AW':
                            gre_aw = score
                        continue

                    # Format: "GRE 161" (Quant, no label) or "GRE 330" (combined score)
                    if not gre_quant:
                        gre_unlabeled = re.search(r'GRE\s+(\d+)', badge_text)
                        if gre_unlabeled:
                            gre_quant = gre_unlabeled.group(1)
                            continue

                # GRE with parentheses: "169 (Q)", "170 (V)", "5.0 (AW)"
                if '(Q)' in badge_text or '(V)' in badge_text or '(AW)' in badge_text:
                    gre_component_match = re.search(r'([\d.]+)\s*\(([QVA]+W?)\)', badge_text)
                    if gre_component_match:
                        score = gre_component_match.group(1)
                        component = gre_component_match.group(2)

                        if component == 'Q' and not gre_quant:
                            gre_quant = score
                        elif component == 'V' and not gre_verbal:
                            gre_verbal = score
                        elif component == 'AW' and not gre_aw:
                            gre_aw = score
                        continue

        # Check for comment row (i+2)
        comment_row = rows[i + 2] if i + 2 < len(rows) else None
        if comment_row and comment_row.get('class') and 'tw-border-none' in comment_row.get('class'):
            # Look for <p> tag containing the comment
            comment_p = comment_row.find('p')
            if comment_p:
                comment = comment_p.get_text(strip=True)

        posting = {
            'gradcafe_id': gradcafe_id,
            'school': school,
            'program': program,
            'degree': degree,
            'date_added': date_added,
            'decision': decision,
            'season': season,
            'status': status,
            'gpa': gpa,
            'gre_quant': gre_quant,
            'gre_verbal': gre_verbal,
            'gre_aw': gre_aw,
            'comment': comment,
            'date_added_iso': date_added_iso
        }

        postings.append(posting)
        i += 2

    return postings

def scrape_gradcafe(num_pages: int = 1) -> List[Dict]:
    all_postings = []

    for page in range(1, num_pages + 1):
        print(f"Scraping page {page}/{num_pages}...")
        postings = scrape_gradcafe_page(page)
        all_postings.extend(postings)

        if page < num_pages:
            time.sleep(1)

    return all_postings

def fetch_and_store_new_postings(use_recent_check: bool = True, days_back: int = 7) -> int:
    postings = scrape_gradcafe_page(1)
    new_count = 0

    for posting in postings:
        exists = (
            posting_exists_recent(posting['gradcafe_id'], days_back)
            if use_recent_check else
            posting_exists(posting['gradcafe_id'])
        )

        if not exists:
            if add_posting(posting):
                new_count += 1
                print(f"New posting: {posting['school']} - {posting['program']} ({posting['decision']})")

    return new_count

def scrape_all_history(start_page: int = 1, end_page: Optional[int] = None, batch_size: int = 50) -> int:
    if end_page is None:
        end_page = 1529

    total_added = 0
    total_duplicates = 0

    page = start_page
    while page <= end_page:
        batch_end = min(page + batch_size - 1, end_page)
        actual_batch_size = batch_end - page + 1

        print(f"\n{'='*80}")
        print(f"Processing pages {page} to {batch_end} (of {end_page})")
        print(f"{'='*80}")

        for current_page in range(page, batch_end + 1):
            postings = scrape_gradcafe_page(current_page)

            for posting in postings:
                if not posting_exists(posting['gradcafe_id']):
                    if add_posting(posting):
                        total_added += 1
                else:
                    total_duplicates += 1

            if current_page % 10 == 0:
                print(f"  Page {current_page}: {total_added} added, {total_duplicates} duplicates so far")

            time.sleep(0.1)

        print(f"Batch complete: {total_added} total added, {total_duplicates} total duplicates")
        time.sleep(0.3)

        page += batch_size

    return total_added
