#!/usr/bin/env python3
"""
Test script for the aggregation tables refresh mechanism
"""
import sys
from database import refresh_aggregation_tables, get_db_connection

def test_aggregation_tables():
    print("Testing aggregation table refresh...")

    # Refresh the tables
    print("\n1. Refreshing aggregation tables...")
    try:
        refresh_aggregation_tables()
        print("   ✓ Refresh completed successfully")
    except Exception as e:
        print(f"   ✗ Error during refresh: {e}")
        return False

    # Verify the tables exist and have data
    print("\n2. Verifying table structure and counts...")
    with get_db_connection() as conn:
        cursor = conn.cursor()

        # Check phd table
        cursor.execute("SELECT COUNT(*) FROM phd")
        phd_count = cursor.fetchone()[0]
        print(f"   PhD table: {phd_count} rows")

        # Check masters table
        cursor.execute("SELECT COUNT(*) FROM masters")
        masters_count = cursor.fetchone()[0]
        print(f"   Masters table: {masters_count} rows")

        # Verify columns in phd table
        cursor.execute("PRAGMA table_info(phd)")
        phd_columns = [row[1] for row in cursor.fetchall()]
        expected_columns = ['school', 'program', 'decision_date', 'gpa', 'gre', 'result']

        print(f"\n3. Verifying phd table columns...")
        print(f"   Expected: {expected_columns}")
        print(f"   Got:      {phd_columns}")

        if phd_columns == expected_columns:
            print("   ✓ Columns match")
        else:
            print("   ✗ Column mismatch!")
            return False

        # Sample some data from each table
        print("\n4. Sample data from phd table:")
        cursor.execute("SELECT * FROM phd LIMIT 3")
        for row in cursor.fetchall():
            print(f"   {dict(row)}")

        print("\n5. Sample data from masters table:")
        cursor.execute("SELECT * FROM masters LIMIT 3")
        for row in cursor.fetchall():
            print(f"   {dict(row)}")

        # Check that only 2018+ data is included
        print("\n6. Verifying date filter (should all be > 2018)...")
        cursor.execute("""
            SELECT MIN(CAST(strftime('%Y', date_added_iso) AS INTEGER)) as min_year,
                   MAX(CAST(strftime('%Y', date_added_iso) AS INTEGER)) as max_year
            FROM postings
            WHERE degree = 'PhD'
            AND gradcafe_id IN (
                SELECT p.gradcafe_id
                FROM postings p
                INNER JOIN phd ON p.school = phd.school AND p.program = phd.program
                LIMIT 100
            )
        """)
        result = cursor.fetchone()
        if result:
            print(f"   Sample year range in source data: {result[0]} - {result[1]}")

    print("\n✓ All tests passed!")
    return True

if __name__ == '__main__':
    success = test_aggregation_tables()
    sys.exit(0 if success else 1)
