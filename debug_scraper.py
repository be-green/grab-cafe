#!/usr/bin/env python3
"""
Debug script to examine GradCafe HTML structure and test parsing.
"""

import requests
from bs4 import BeautifulSoup
import re

url = 'https://www.thegradcafe.com/survey/?institution=&program=economics'

print("Fetching GradCafe page...")
response = requests.get(url, timeout=30)
soup = BeautifulSoup(response.content, 'html.parser')

rows = soup.find_all('tr')
print(f'\nFound {len(rows)} total table rows\n')
print('=' * 80)

# Examine first 3 complete postings
count = 0
i = 1

while i < len(rows) and count < 3:
    row = rows[i]
    cells = row.find_all('td')

    if len(cells) == 5:
        print(f'\n### POSTING {count + 1} ###\n')

        # Main row
        school = cells[0].get_text(strip=True)
        program = cells[1].get_text(strip=True)
        date_added = cells[2].get_text(strip=True)
        decision = cells[3].get_text(strip=True)

        link = cells[4].find('a')
        gradcafe_id = ""
        if link and link.get('href'):
            href = link.get('href')
            id_match = re.search(r'/result/(\d+)', href)
            if id_match:
                gradcafe_id = id_match.group(1)

        print(f"School: {school}")
        print(f"Program: {program}")
        print(f"Date: {date_added}")
        print(f"Decision: {decision}")
        print(f"GradCafe ID: {gradcafe_id}")

        # Details row
        if i + 1 < len(rows):
            details_row = rows[i + 1]
            details_class = details_row.get('class', [])
            print(f"\nDetails row classes: {details_class}")

            if 'tw-border-none' in details_class:
                details_text = details_row.get_text()
                print(f"Details text: '{details_text}'")
                print(f"\nDetails HTML:")
                print(details_row.prettify())

                # Test parsing
                print("\n--- Parsing Tests ---")

                # GPA
                gpa_match = re.search(r'GPA\s+([\d.]+)', details_text)
                print(f"GPA match: {gpa_match.group(1) if gpa_match else 'NOT FOUND'}")

                # GRE
                gre_q_match = re.search(r'GRE\s+(\d+)\s*\(Q\)', details_text)
                gre_v_match = re.search(r'(\d+)\s*\(V\)', details_text)
                gre_aw_match = re.search(r'([\d.]+)\s*\(AW\)', details_text)

                print(f"GRE Quant match: {gre_q_match.group(1) if gre_q_match else 'NOT FOUND'}")
                print(f"GRE Verbal match: {gre_v_match.group(1) if gre_v_match else 'NOT FOUND'}")
                print(f"GRE AW match: {gre_aw_match.group(1) if gre_aw_match else 'NOT FOUND'}")

                # Try alternative GRE patterns
                print("\n--- Alternative GRE patterns ---")
                all_numbers = re.findall(r'\d+', details_text)
                print(f"All numbers found: {all_numbers}")

                # Look for patterns like "169 (Q) 170 (V) 5.0 (AW)"
                alt_pattern = re.findall(r'(\d+(?:\.\d+)?)\s*\(([QVAW]+)\)', details_text)
                print(f"Pattern with parentheses: {alt_pattern}")

        # Comment row
        if i + 2 < len(rows):
            comment_row = rows[i + 2]
            comment_class = comment_row.get('class', [])
            print(f"\nComment row classes: {comment_class}")

            if 'tw-border-none' in comment_class:
                comment_p = comment_row.find('p')
                if comment_p:
                    comment_text = comment_p.get_text(strip=True)
                    print(f"Comment: '{comment_text}'")
                else:
                    print("No <p> tag found in comment row")
                    print(f"Comment row HTML:")
                    print(comment_row.prettify())

        print('\n' + '=' * 80)
        count += 1
        i += 3  # Skip main row + details row + comment row
    else:
        i += 1

print(f"\n\nExamined {count} postings")
