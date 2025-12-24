#!/usr/bin/env python3
"""
Test all scraper parsing logic
"""
from scraper import scrape_gradcafe_page
import json

def test_all_parsing():
    print("Scraping first page to test parsing...")
    postings = scrape_gradcafe_page(1)

    print(f"\nFound {len(postings)} postings\n")
    print("="*100)

    # Show all fields for each posting
    for i, posting in enumerate(postings[:15], 1):
        print(f"\n{i}. {posting['school']} - {posting['program']}")
        print(f"   Degree: {posting['degree']}")
        print(f"   Decision: {posting['decision']}")
        print(f"   Date Added: {posting['date_added']} (ISO: {posting['date_added_iso']})")
        print(f"   Season: {posting['season']}")
        print(f"   Status: {posting['status']}")
        print(f"   GPA: {posting['gpa']}")
        print(f"   GRE Quant: {posting['gre_quant']}")
        print(f"   GRE Verbal: {posting['gre_verbal']}")
        print(f"   GRE AW: {posting['gre_aw']}")
        print(f"   Comment: {posting['comment'][:100] if posting['comment'] else '(none)'}")
        print(f"   GradCafe ID: {posting['gradcafe_id']}")

    # Summary statistics
    print("\n" + "="*100)
    print("\nSUMMARY STATISTICS:")
    print("="*100)

    total = len(postings)
    with_degree = sum(1 for p in postings if p['degree'])
    with_season = sum(1 for p in postings if p['season'])
    with_status = sum(1 for p in postings if p['status'])
    with_gpa = sum(1 for p in postings if p['gpa'])
    with_gre_q = sum(1 for p in postings if p['gre_quant'])
    with_gre_v = sum(1 for p in postings if p['gre_verbal'])
    with_gre_aw = sum(1 for p in postings if p['gre_aw'])
    with_comment = sum(1 for p in postings if p['comment'])
    with_date_iso = sum(1 for p in postings if p['date_added_iso'])

    print(f"Total postings: {total}")
    print(f"With degree: {with_degree} ({with_degree/total*100:.1f}%)")
    print(f"With season: {with_season} ({with_season/total*100:.1f}%)")
    print(f"With status: {with_status} ({with_status/total*100:.1f}%)")
    print(f"With GPA: {with_gpa} ({with_gpa/total*100:.1f}%)")
    print(f"With GRE Quant: {with_gre_q} ({with_gre_q/total*100:.1f}%)")
    print(f"With GRE Verbal: {with_gre_v} ({with_gre_v/total*100:.1f}%)")
    print(f"With GRE AW: {with_gre_aw} ({with_gre_aw/total*100:.1f}%)")
    print(f"With comment: {with_comment} ({with_comment/total*100:.1f}%)")
    print(f"With ISO date: {with_date_iso} ({with_date_iso/total*100:.1f}%)")

    # Check for potential parsing issues
    print("\n" + "="*100)
    print("\nPOTENTIAL ISSUES:")
    print("="*100)

    # Check for missing degree on economics postings
    econ_no_degree = [p for p in postings if 'economic' in p['program'].lower() and not p['degree']]
    if econ_no_degree:
        print(f"\nEconomics postings without degree ({len(econ_no_degree)}):")
        for p in econ_no_degree[:5]:
            print(f"  - {p['school']} - {p['program']}")

    # Check for missing dates
    no_date = [p for p in postings if not p['date_added_iso']]
    if no_date:
        print(f"\nPostings without ISO date ({len(no_date)}):")
        for p in no_date[:5]:
            print(f"  - {p['school']} - Date: {p['date_added']}")

    # Check for unusual GPA values
    unusual_gpa = [p for p in postings if p['gpa'] and (float(p['gpa']) > 4.0 or float(p['gpa']) < 0)]
    if unusual_gpa:
        print(f"\nUnusual GPA values ({len(unusual_gpa)}):")
        for p in unusual_gpa[:5]:
            print(f"  - {p['school']} - GPA: {p['gpa']}")

    # Check for unusual GRE values
    unusual_gre = [p for p in postings if p['gre_quant'] and (int(p['gre_quant']) > 170 or int(p['gre_quant']) < 130)]
    if unusual_gre:
        print(f"\nUnusual GRE Quant values ({len(unusual_gre)}):")
        for p in unusual_gre[:5]:
            print(f"  - {p['school']} - GRE Q: {p['gre_quant']}")

if __name__ == '__main__':
    test_all_parsing()
