import requests
from bs4 import BeautifulSoup
import re
import time
from datetime import datetime
from typing import List, Dict, Optional
from database import posting_exists, posting_exists_recent, add_posting

GRADCAFE_BASE_URL = "https://www.thegradcafe.com/survey/?institution=&program=economics"

# Degree pattern - order matters (longer patterns first to avoid partial matches)
DEGREE_PATTERN = r'(PhD|Doctorate|Masters|Master|MBA|MPhil|MRes|MSc|MFA|MS|MA|JD|Other)$'


def _validate_gpa(gpa_str: str) -> Optional[str]:
    """Return GPA if valid (0-10 range for international scales), else None."""
    if not gpa_str:
        return None
    try:
        gpa = float(gpa_str)
        if 0.0 <= gpa <= 10.0:
            return gpa_str
    except ValueError:
        pass
    return None


def _validate_gre_section(score_str: str, section: str) -> Optional[str]:
    """Validate GRE score. Q/V: 130-170, AW: 0-6."""
    if not score_str:
        return None
    try:
        score = float(score_str)
        if section in ('Q', 'V') and 130 <= score <= 170:
            return score_str
        if section == 'AW' and 0.0 <= score <= 6.0:
            return score_str
    except ValueError:
        pass
    return None

def _normalize_date(date_str: str) -> Optional[str]:
    """Normalize date string to ISO format (YYYY-MM-DD). Returns None if unparseable."""
    if not date_str:
        return None

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

    return None

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

        # Parse degree from program name (e.g., "EconomicsPhD" -> "Economics", "PhD")
        program_match = re.search(DEGREE_PATTERN, program_raw)
        if program_match:
            degree = program_match.group(1)
            program = program_raw[:program_match.start()].strip() or program_raw
        else:
            program = program_raw
            degree = None

        # Initialize optional fields with None for consistency
        details_row = rows[i + 1] if i + 1 < len(rows) else None
        season = None
        status = None
        gpa = None
        gre_quant = None
        gre_verbal = None
        gre_aw = None
        gre_combined = None
        comment = None

        # Track if we actually consumed the details row
        details_row_consumed = False

        if details_row and details_row.get('class') and 'tw-border-none' in details_row.get('class'):
            details_row_consumed = True
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

                # GPA - validate before storing
                if not gpa:
                    gpa_match = re.search(r'GPA\s+([\d.]+)', badge_text)
                    if gpa_match:
                        gpa = _validate_gpa(gpa_match.group(1))
                        continue

                # GRE patterns - handle multiple formats
                if badge_text.startswith('GRE'):
                    # Format: "GRE V 170" or "GRE AW 6.0" or "GRE Q 165"
                    gre_labeled = re.search(r'GRE\s+(V|AW|Q)\s+([\d.]+)', badge_text)
                    if gre_labeled:
                        component = gre_labeled.group(1)
                        score = gre_labeled.group(2)
                        if component == 'Q' and not gre_quant:
                            gre_quant = _validate_gre_section(score, 'Q')
                        elif component == 'V' and not gre_verbal:
                            gre_verbal = _validate_gre_section(score, 'V')
                        elif component == 'AW' and not gre_aw:
                            gre_aw = _validate_gre_section(score, 'AW')
                        continue

                    # Format: "GRE 161" (unlabeled - could be quant or combined)
                    if not gre_quant and not gre_combined:
                        gre_unlabeled = re.search(r'GRE\s+(\d+)', badge_text)
                        if gre_unlabeled:
                            score = int(gre_unlabeled.group(1))
                            if 130 <= score <= 170:
                                # Valid individual section score (assume quant)
                                gre_quant = str(score)
                            elif 260 <= score <= 340:
                                # Combined score
                                gre_combined = str(score)
                            continue

                # GRE with parentheses: "169 (Q)", "170 (V)", "5.0 (AW)"
                if '(Q)' in badge_text or '(V)' in badge_text or '(AW)' in badge_text:
                    gre_component_match = re.search(r'([\d.]+)\s*\((Q|V|AW)\)', badge_text)
                    if gre_component_match:
                        score = gre_component_match.group(1)
                        component = gre_component_match.group(2)

                        if component == 'Q' and not gre_quant:
                            gre_quant = _validate_gre_section(score, 'Q')
                        elif component == 'V' and not gre_verbal:
                            gre_verbal = _validate_gre_section(score, 'V')
                        elif component == 'AW' and not gre_aw:
                            gre_aw = _validate_gre_section(score, 'AW')
                        continue

        # Calculate combined score if we have both Q and V but no combined
        if gre_quant and gre_verbal and not gre_combined:
            try:
                combined = int(gre_quant) + int(gre_verbal)
                if 260 <= combined <= 340:
                    gre_combined = str(combined)
            except ValueError:
                pass

        # Check for comment row - only if we consumed a details row
        comment_row = None
        comment_row_consumed = False
        if details_row_consumed:
            comment_row = rows[i + 2] if i + 2 < len(rows) else None
            if comment_row and comment_row.get('class') and 'tw-border-none' in comment_row.get('class'):
                comment_row_consumed = True
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
            'gre_combined': gre_combined,
            'comment': comment,
            'date_added_iso': date_added_iso
        }

        postings.append(posting)

        # Dynamic row advancement based on what we actually consumed
        rows_consumed = 1  # Main row
        if details_row_consumed:
            rows_consumed += 1
        if comment_row_consumed:
            rows_consumed += 1
        i += rows_consumed

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
