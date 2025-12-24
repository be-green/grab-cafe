import sqlite3
from database import get_all_postings, posting_exists, posting_exists_recent, format_posting_for_discord
from scraper import scrape_gradcafe_page
import time

print("=" * 80)
print("GRADCAFE BOT DIAGNOSTICS")
print("=" * 80)

# Test 1: Database Integrity
print("\n1. DATABASE INTEGRITY CHECKS")
print("-" * 80)

conn = sqlite3.connect('gradcafe_messages.db')
cursor = conn.cursor()

cursor.execute('SELECT COUNT(*) FROM postings')
total = cursor.fetchone()[0]
print(f"✓ Total postings: {total}")

cursor.execute('SELECT COUNT(DISTINCT gradcafe_id) FROM postings')
unique_ids = cursor.fetchone()[0]
print(f"✓ Unique GradCafe IDs: {unique_ids}")

if total == unique_ids:
    print("✓ NO DUPLICATES - All postings have unique IDs")
else:
    print(f"✗ WARNING: {total - unique_ids} duplicate IDs found!")

cursor.execute('SELECT gradcafe_id, COUNT(*) as cnt FROM postings GROUP BY gradcafe_id HAVING cnt > 1')
duplicates = cursor.fetchall()
if duplicates:
    print(f"  Duplicate IDs: {duplicates[:5]}")

# Test 2: Required Fields
print("\n2. REQUIRED FIELDS CHECK")
print("-" * 80)

cursor.execute('SELECT COUNT(*) FROM postings WHERE gradcafe_id IS NULL OR gradcafe_id = ""')
missing_id = cursor.fetchone()[0]
print(f"{'✓' if missing_id == 0 else '✗'} Missing GradCafe ID: {missing_id}")

cursor.execute('SELECT COUNT(*) FROM postings WHERE school IS NULL OR school = ""')
missing_school = cursor.fetchone()[0]
print(f"{'✓' if missing_school == 0 else '✗'} Missing School: {missing_school}")

cursor.execute('SELECT COUNT(*) FROM postings WHERE program IS NULL OR program = ""')
missing_program = cursor.fetchone()[0]
print(f"{'✓' if missing_program == 0 else '✗'} Missing Program: {missing_program}")

cursor.execute('SELECT COUNT(*) FROM postings WHERE decision IS NULL OR decision = ""')
missing_decision = cursor.fetchone()[0]
print(f"{'✓' if missing_decision == 0 else '✗'} Missing Decision: {missing_decision}")

cursor.execute('SELECT COUNT(*) FROM postings WHERE date_added IS NULL OR date_added = ""')
missing_date = cursor.fetchone()[0]
print(f"{'✓' if missing_date == 0 else '✗'} Missing Date Added: {missing_date}")

# Test 3: Data Quality
print("\n3. DATA QUALITY CHECKS")
print("-" * 80)

cursor.execute('SELECT COUNT(*) FROM postings WHERE gpa IS NOT NULL AND gpa != ""')
with_gpa = cursor.fetchone()[0]
print(f"✓ Postings with GPA: {with_gpa} ({with_gpa/total*100:.1f}%)")

cursor.execute('SELECT COUNT(*) FROM postings WHERE gre_quant IS NOT NULL AND gre_quant != ""')
with_gre = cursor.fetchone()[0]
print(f"✓ Postings with GRE: {with_gre} ({with_gre/total*100:.1f}%)")

cursor.execute('SELECT COUNT(*) FROM postings WHERE season IS NOT NULL AND season != ""')
with_season = cursor.fetchone()[0]
print(f"✓ Postings with Season: {with_season} ({with_season/total*100:.1f}%)")

cursor.execute('SELECT COUNT(*) FROM postings WHERE status IS NOT NULL AND status != ""')
with_status = cursor.fetchone()[0]
print(f"✓ Postings with Status: {with_status} ({with_status/total*100:.1f}%)")

# Test 4: Scraper Functionality
print("\n4. SCRAPER FUNCTIONALITY TEST")
print("-" * 80)

print("Testing live scrape of page 1...")
try:
    postings = scrape_gradcafe_page(1)
    print(f"✓ Successfully scraped {len(postings)} postings")

    if postings:
        test_posting = postings[0]
        required_fields = ['gradcafe_id', 'school', 'program', 'decision', 'date_added']
        missing = [f for f in required_fields if not test_posting.get(f)]

        if missing:
            print(f"✗ Missing required fields: {missing}")
        else:
            print("✓ All required fields present in scraped data")
            print(f"  Sample ID: {test_posting['gradcafe_id']}")
            print(f"  Sample: {test_posting['school']} - {test_posting['program']}")
except Exception as e:
    print(f"✗ Scraper error: {e}")

# Test 5: Uniqueness Functions
print("\n5. UNIQUENESS CHECK FUNCTIONS")
print("-" * 80)

cursor.execute('SELECT gradcafe_id FROM postings LIMIT 1')
test_id = cursor.fetchone()[0]

exists_full = posting_exists(test_id)
print(f"✓ posting_exists('{test_id}'): {exists_full}")

exists_recent = posting_exists_recent(test_id, days_back=7)
print(f"✓ posting_exists_recent('{test_id}', 7 days): {exists_recent}")

fake_id = "999999999"
not_exists = posting_exists(fake_id)
print(f"✓ posting_exists('{fake_id}'): {not_exists} (should be False)")

# Test 6: Performance
print("\n6. PERFORMANCE TESTS")
print("-" * 80)

start = time.time()
for _ in range(100):
    posting_exists_recent(test_id, days_back=7)
elapsed_recent = time.time() - start
print(f"✓ 100 recent checks: {elapsed_recent:.3f}s ({elapsed_recent/100*1000:.2f}ms each)")

start = time.time()
for _ in range(100):
    posting_exists(test_id)
elapsed_full = time.time() - start
print(f"✓ 100 full checks: {elapsed_full:.3f}s ({elapsed_full/100*1000:.2f}ms each)")

speedup = elapsed_full / elapsed_recent
print(f"✓ Recent check is {speedup:.1f}x faster")

# Test 7: Discord Message Formatting
print("\n7. DISCORD MESSAGE FORMATTING")
print("-" * 80)

cursor.execute('SELECT * FROM postings WHERE gpa IS NOT NULL AND gpa != "" AND gre_quant IS NOT NULL AND gre_quant != "" LIMIT 1')
row = cursor.fetchone()
if row:
    posting_dict = dict(zip([d[0] for d in cursor.description], row))
    message = format_posting_for_discord(posting_dict)
    print("✓ Sample formatted message:")
    print("-" * 40)
    print(message)
    print("-" * 40)
else:
    print("✗ No posting with GPA and GRE found for formatting test")

# Test 8: Posted Status
print("\n8. POSTED STATUS CHECK")
print("-" * 80)

cursor.execute('SELECT COUNT(*) FROM postings WHERE posted_to_discord = 1')
posted = cursor.fetchone()[0]
cursor.execute('SELECT COUNT(*) FROM postings WHERE posted_to_discord = 0')
unposted = cursor.fetchone()[0]

print(f"✓ Posted to Discord: {posted}")
print(f"✓ Not yet posted: {unposted}")
print(f"✓ Total: {posted + unposted}")

if posted + unposted == total:
    print("✓ All postings accounted for")
else:
    print("✗ Mismatch in posted status counts!")

# Summary
print("\n" + "=" * 80)
print("DIAGNOSTIC SUMMARY")
print("=" * 80)

issues = []
if total != unique_ids:
    issues.append(f"Duplicate IDs found ({total - unique_ids})")
if missing_id > 0:
    issues.append(f"Missing GradCafe IDs ({missing_id})")
if missing_school > 0:
    issues.append(f"Missing Schools ({missing_school})")
if missing_program > 0:
    issues.append(f"Missing Programs ({missing_program})")
if missing_decision > 0:
    issues.append(f"Missing Decisions ({missing_decision})")

if issues:
    print("✗ ISSUES FOUND:")
    for issue in issues:
        print(f"  - {issue}")
else:
    print("✓ ALL CHECKS PASSED - System is ready!")

print(f"\nDatabase: {total} unique postings ready for Discord bot")

conn.close()
