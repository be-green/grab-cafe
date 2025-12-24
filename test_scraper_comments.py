#!/usr/bin/env python3
"""
Test if the scraper extracts comments correctly
"""
from scraper import scrape_gradcafe_page

def test_comment_extraction():
    print("Scraping first page...")
    postings = scrape_gradcafe_page(1)

    print(f"\nFound {len(postings)} postings\n")

    # Show first 10 postings with their comments
    for i, posting in enumerate(postings[:10], 1):
        print(f"{i}. {posting['school']} - {posting['program']}")
        if posting['comment']:
            print(f"   Comment: {posting['comment']}")
        else:
            print(f"   Comment: (none)")
        print()

if __name__ == '__main__':
    test_comment_extraction()
