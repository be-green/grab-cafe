import sqlite3
from contextlib import contextmanager
from typing import List, Dict, Optional
import os
import json

DB_PATH = os.getenv('DB_PATH', 'gradcafe_messages.db')

def _null_if_empty(value):
    if value in ("", None):
        return None
    return value

def _column_exists(conn: sqlite3.Connection, column_name: str) -> bool:
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(postings)")
    return any(row[1] == column_name for row in cursor.fetchall())

@contextmanager
def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def init_database():
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS postings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                gradcafe_id TEXT NOT NULL UNIQUE,
                school TEXT NOT NULL,
                program TEXT NOT NULL,
                degree TEXT,
                decision TEXT NOT NULL,
                date_added TEXT NOT NULL,
                date_added_iso TEXT,
                season TEXT,
                status TEXT,
                gpa REAL,
                gre_quant REAL,
                gre_verbal REAL,
                gre_aw REAL,
                comment TEXT,
                scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                posted_to_discord BOOLEAN DEFAULT 0
            )
        ''')
        if not _column_exists(conn, "date_added_iso"):
            cursor.execute('ALTER TABLE postings ADD COLUMN date_added_iso TEXT')
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_gradcafe_id ON postings(gradcafe_id)
        ''')
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_posted ON postings(posted_to_discord)
        ''')
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_scraped_at ON postings(scraped_at)
        ''')
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_school ON postings(school)
        ''')
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_date_added ON postings(date_added)
        ''')

def posting_exists(gradcafe_id: str) -> bool:
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT 1 FROM postings
            WHERE gradcafe_id = ?
            LIMIT 1
        ''', (gradcafe_id,))
        return cursor.fetchone() is not None

def posting_exists_recent(gradcafe_id: str, days_back: int = 7) -> bool:
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT 1 FROM postings
            WHERE gradcafe_id = ?
            AND scraped_at >= datetime('now', '-' || ? || ' days')
            LIMIT 1
        ''', (gradcafe_id, days_back))
        return cursor.fetchone() is not None

def add_posting(posting: Dict) -> bool:
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO postings (
                    gradcafe_id, school, program, degree, decision, date_added,
                    date_added_iso, season, status, gpa, gre_quant, gre_verbal, gre_aw, comment
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                posting['gradcafe_id'],
                posting['school'],
                posting['program'],
                posting.get('degree', ''),
                posting['decision'],
                posting['date_added'],
                _null_if_empty(posting.get('date_added_iso')),
                posting.get('season', ''),
                posting.get('status', ''),
                _null_if_empty(posting.get('gpa')),
                _null_if_empty(posting.get('gre_quant')),
                _null_if_empty(posting.get('gre_verbal')),
                _null_if_empty(posting.get('gre_aw')),
                posting.get('comment', '')
            ))
            return True
    except sqlite3.IntegrityError:
        return False

def get_unposted_postings(days_back: int = 1) -> List[Dict]:
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT * FROM postings
            WHERE posted_to_discord = 0
            AND date_added_iso IS NOT NULL
            AND date_added_iso >= date('now', '-' || ? || ' days')
            ORDER BY id ASC
        ''', (days_back,))
        return [dict(row) for row in cursor.fetchall()]

def mark_posting_as_posted(posting_id: int):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE postings
            SET posted_to_discord = 1
            WHERE id = ?
        ''', (posting_id,))

def get_all_postings() -> List[Dict]:
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM postings ORDER BY id ASC')
        return [dict(row) for row in cursor.fetchall()]

def refresh_aggregation_tables():
    """
    Refresh the phd and masters aggregation tables.
    These tables are simplified views filtered by degree and date for easier LLM querying.

    Filters postings from 2018 onwards and creates separate tables for PhD and Masters degrees
    with columns: school, program, gpa, gre (from gre_quant), result
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()

        # Create phd table
        cursor.execute('DROP TABLE IF EXISTS phd')
        cursor.execute('''
            CREATE TABLE phd AS
            SELECT
                school,
                program,
                gpa,
                gre_quant as gre,
                result
            FROM postings
            WHERE degree = 'PhD'
            AND CAST(strftime('%Y', date_added_iso) AS INTEGER) > 2018
        ''')

        # Create masters table
        cursor.execute('DROP TABLE IF EXISTS masters')
        cursor.execute('''
            CREATE TABLE masters AS
            SELECT
                school,
                program,
                gpa,
                gre_quant as gre,
                result
            FROM postings
            WHERE degree = 'Masters'
            AND CAST(strftime('%Y', date_added_iso) AS INTEGER) > 2018
        ''')

def format_posting_for_discord(posting: Dict) -> str:
    lines = []

    lines.append(f"**{posting['school']}**")

    program_line = posting['program']
    if posting.get('degree'):
        program_line += f" ({posting['degree']})"
    lines.append(program_line)

    lines.append(f"_{posting['decision']}_")

    details = []
    if posting.get('season'):
        details.append(posting['season'])
    if posting.get('status'):
        details.append(posting['status'])
    if posting.get('gpa'):
        details.append(f"GPA: {posting['gpa']}")

    gre_parts = []
    if posting.get('gre_quant'):
        gre_parts.append(f"Q:{posting['gre_quant']}")
    if posting.get('gre_verbal'):
        gre_parts.append(f"V:{posting['gre_verbal']}")
    if posting.get('gre_aw'):
        gre_parts.append(f"AW:{posting['gre_aw']}")
    if gre_parts:
        details.append(f"GRE: {' '.join(gre_parts)}")

    if details:
        lines.append(' | '.join(details))

    if posting.get('comment'):
        lines.append(f'"{posting["comment"]}"')

    lines.append(f"Added: {posting['date_added']}")

    return '\n'.join(lines)
