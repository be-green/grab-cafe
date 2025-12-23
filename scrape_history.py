from database import init_database, get_all_postings
from scraper import scrape_all_history
import sys

def main():
    print("GradCafe Historical Scraper")
    print("="*80)
    print("This will scrape ALL historical GradCafe economics postings.")
    print("There are approximately 1,529 pages (~30,000 postings).")
    print("This will take several hours to complete.")
    print("="*80)

    start_page = 1
    end_page = None

    if len(sys.argv) > 1:
        start_page = int(sys.argv[1])

    if len(sys.argv) > 2:
        end_page = int(sys.argv[2])

    print(f"\nStarting from page: {start_page}")
    print(f"Ending at page: {end_page if end_page else 1529}")
    print("\nInitializing database...")
    init_database()

    existing = get_all_postings()
    print(f"Database currently has {len(existing)} postings")

    print("\nStarting historical scrape...")
    total_added = scrape_all_history(start_page=start_page, end_page=end_page, batch_size=10)

    print("\n" + "="*80)
    print("SCRAPING COMPLETE!")
    print("="*80)
    print(f"Total new postings added: {total_added}")

    final_count = len(get_all_postings())
    print(f"Total postings in database: {final_count}")

if __name__ == '__main__':
    main()
