#!/usr/bin/env python3
"""
Test script to inspect HTML structure and extract comments from GradCafe
"""
import requests
from bs4 import BeautifulSoup
import re

GRADCAFE_URL = "https://www.thegradcafe.com/survey/?institution=&program=economics"

def inspect_individual_result(result_id):
    """Fetch and inspect an individual result page."""
    url = f"https://www.thegradcafe.com/survey/result/{result_id}/"
    print(f"\nFetching individual result page: {url}")

    response = requests.get(url, timeout=30)
    soup = BeautifulSoup(response.content, 'html.parser')

    print("\n" + "="*80)
    print("INDIVIDUAL RESULT PAGE HTML")
    print("="*80)

    # Look for comment-like elements
    print("\nLooking for <p> tags:")
    for p in soup.find_all('p'):
        text = p.get_text(strip=True)
        if len(text) > 20:  # Only show substantial paragraphs
            print(f"  - {text[:200]}")

    print("\nLooking for divs with 'comment' in class:")
    for div in soup.find_all('div'):
        classes = div.get('class', [])
        if any('comment' in str(c).lower() for c in classes):
            print(f"  - Class: {classes} | Text: {div.get_text(strip=True)[:200]}")

    print("\nLooking for elements with 'comment' in text content:")
    for elem in soup.find_all(text=re.compile('comment', re.I)):
        if elem.parent.name not in ['script', 'style']:
            print(f"  - {elem.parent.name}: {str(elem)[:200]}")

    # Print entire page (truncated)
    print("\n\nFull page body (first 2000 chars):")
    print(soup.get_text()[:2000])

def inspect_listing_page():
    print("Fetching GradCafe listing page...")
    response = requests.get(GRADCAFE_URL, timeout=30)
    soup = BeautifulSoup(response.content, 'html.parser')

    rows = soup.find_all('tr')
    print(f"Found {len(rows)} rows\n")

    # Look at first few postings in detail
    i = 1
    posting_count = 0

    while i < len(rows) and posting_count < 10:
        row = rows[i]
        cells = row.find_all('td')

        if len(cells) != 5:
            i += 1
            continue

        posting_count += 1
        school = cells[0].get_text(strip=True)
        program = cells[1].get_text(strip=True)

        print(f"\n{'='*80}")
        print(f"POSTING #{posting_count}: {school} - {program}")
        print(f"{'='*80}")

        # Look at next 3 rows
        for offset in range(1, 4):
            if i + offset < len(rows):
                next_row = rows[i + offset]

                # Look for paragraphs
                paragraphs = next_row.find_all('p')
                if paragraphs:
                    print(f"\nRow {offset} after main row HAS PARAGRAPHS:")
                    print(f"  Classes: {next_row.get('class')}")
                    print(f"  Columns: {len(next_row.find_all('td'))}")
                    print(f"  Full HTML:")
                    print(next_row.prettify())
                    print(f"\n  Paragraph texts:")
                    for idx, p in enumerate(paragraphs):
                        print(f"    [{idx}]: {p.get_text(strip=True)}")

        i += 2

    return None

if __name__ == '__main__':
    inspect_listing_page()
