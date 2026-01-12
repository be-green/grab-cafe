#!/usr/bin/env python3
"""
Migration script to fix historical bad data from parser bugs.
Run AFTER implementing parser fixes to clean existing records.

Fixes:
1. Migrate combined GRE scores (>170) from gre_quant to gre_combined
2. Calculate gre_combined for records with both Q and V scores
3. Split concatenated degree from program names
4. Convert empty strings to NULL for consistency
5. Set invalid GPA values (>10) to NULL
"""
import sqlite3
import os
import re

DB_PATH = os.getenv('DB_PATH', 'gradcafe_messages.db')

# Known degrees that may be concatenated with program names
KNOWN_DEGREES = ['MBA', 'MPhil', 'JD', 'MRes', 'MA', 'MS', 'MSc', 'MFA', 'Other']


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def migrate_combined_gre_scores():
    """Move scores > 170 from gre_quant to gre_combined."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE postings
        SET gre_combined = gre_quant,
            gre_quant = NULL
        WHERE gre_quant IS NOT NULL
        AND CAST(gre_quant AS INTEGER) > 170
    """)

    affected = cursor.rowcount
    conn.commit()
    conn.close()
    print(f"[1/5] Migrated {affected} combined GRE scores to gre_combined column")
    return affected


def calculate_combined_scores():
    """Calculate gre_combined = Q + V where both exist and combined is NULL."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE postings
        SET gre_combined = CAST(gre_quant AS INTEGER) + CAST(gre_verbal AS INTEGER)
        WHERE gre_quant IS NOT NULL
        AND gre_verbal IS NOT NULL
        AND gre_combined IS NULL
        AND CAST(gre_quant AS INTEGER) BETWEEN 130 AND 170
        AND CAST(gre_verbal AS INTEGER) BETWEEN 130 AND 170
    """)

    affected = cursor.rowcount
    conn.commit()
    conn.close()
    print(f"[2/5] Calculated {affected} combined GRE scores from Q + V")
    return affected


def fix_degree_parsing():
    """Fix records where degree is concatenated with program name."""
    conn = get_connection()
    cursor = conn.cursor()

    total_fixed = 0
    for deg in KNOWN_DEGREES:
        cursor.execute("""
            SELECT id, program FROM postings
            WHERE program LIKE ?
            AND (degree IS NULL OR degree = '')
        """, (f'%{deg}',))

        rows = cursor.fetchall()
        for row in rows:
            row_id = row['id']
            program = row['program']
            if program.endswith(deg):
                new_program = program[:-len(deg)].strip()
                if new_program:
                    cursor.execute("""
                        UPDATE postings
                        SET program = ?, degree = ?
                        WHERE id = ?
                    """, (new_program, deg, row_id))
                    total_fixed += 1

    conn.commit()
    conn.close()
    print(f"[3/5] Fixed {total_fixed} records with concatenated degree in program name")
    return total_fixed


def fix_empty_strings_to_null():
    """Convert empty strings to NULL for consistency."""
    conn = get_connection()
    cursor = conn.cursor()

    columns = ['degree', 'season', 'status', 'comment', 'date_added_iso']
    total_fixed = 0

    for col in columns:
        cursor.execute(f"""
            UPDATE postings
            SET {col} = NULL
            WHERE {col} = ''
        """)
        total_fixed += cursor.rowcount

    conn.commit()
    conn.close()
    print(f"[4/5] Converted {total_fixed} empty strings to NULL across {len(columns)} columns")
    return total_fixed


def fix_invalid_gpa_values():
    """Set invalid GPA values (>10) to NULL."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE postings
        SET gpa = NULL
        WHERE gpa IS NOT NULL
        AND gpa > 10.0
    """)

    affected = cursor.rowcount
    conn.commit()
    conn.close()
    print(f"[5/5] Fixed {affected} invalid GPA values (>10)")
    return affected


def print_stats():
    """Print database statistics after migration."""
    conn = get_connection()
    cursor = conn.cursor()

    print("\n" + "=" * 60)
    print("POST-MIGRATION STATISTICS")
    print("=" * 60)

    cursor.execute("SELECT COUNT(*) FROM postings")
    total = cursor.fetchone()[0]
    print(f"Total postings: {total}")

    cursor.execute("SELECT COUNT(*) FROM postings WHERE gre_combined IS NOT NULL")
    with_combined = cursor.fetchone()[0]
    print(f"With combined GRE: {with_combined}")

    cursor.execute("SELECT COUNT(*) FROM postings WHERE gre_quant > 170")
    bad_quant = cursor.fetchone()[0]
    print(f"Invalid gre_quant (>170): {bad_quant}")

    cursor.execute("SELECT COUNT(*) FROM postings WHERE gpa > 10")
    bad_gpa = cursor.fetchone()[0]
    print(f"Invalid GPA (>10): {bad_gpa}")

    cursor.execute("SELECT COUNT(*) FROM postings WHERE degree = ''")
    empty_degree = cursor.fetchone()[0]
    print(f"Empty string degrees: {empty_degree}")

    cursor.execute("""
        SELECT COUNT(*) FROM postings
        WHERE program LIKE '%MBA' OR program LIKE '%MPhil'
        OR program LIKE '%JD' OR program LIKE '%Other'
    """)
    concat_degree = cursor.fetchone()[0]
    print(f"Programs ending with degree suffix: {concat_degree}")

    conn.close()


def run_all_migrations():
    """Run all data migrations in order."""
    print("=" * 60)
    print("GRADCAFE DATA MIGRATION")
    print("=" * 60)
    print(f"Database: {DB_PATH}")
    print()

    # Order matters - migrate combined GRE first before calculating
    migrate_combined_gre_scores()
    calculate_combined_scores()
    fix_degree_parsing()
    fix_empty_strings_to_null()
    fix_invalid_gpa_values()

    print_stats()

    print("\n" + "=" * 60)
    print("MIGRATION COMPLETE")
    print("=" * 60)
    print("\nNext steps:")
    print("1. Run: python -c \"from database import refresh_aggregation_tables; refresh_aggregation_tables()\"")
    print("2. Run: python test_scraper_parsing.py")


if __name__ == '__main__':
    run_all_migrations()
