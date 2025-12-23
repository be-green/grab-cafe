import sqlite3
from contextlib import contextmanager
from typing import List, Dict, Optional
import os
import json

DB_PATH = os.getenv('DB_PATH', 'gradcafe_messages.db')

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
                season TEXT,
                status TEXT,
                gpa TEXT,
                gre_quant TEXT,
                gre_verbal TEXT,
                gre_aw TEXT,
                comment TEXT,
                scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                posted_to_discord BOOLEAN DEFAULT 0
            )
        ''')
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
                    season, status, gpa, gre_quant, gre_verbal, gre_aw, comment
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                posting['gradcafe_id'],
                posting['school'],
                posting['program'],
                posting.get('degree', ''),
                posting['decision'],
                posting['date_added'],
                posting.get('season', ''),
                posting.get('status', ''),
                posting.get('gpa', ''),
                posting.get('gre_quant', ''),
                posting.get('gre_verbal', ''),
                posting.get('gre_aw', ''),
                posting.get('comment', '')
            ))
            return True
    except sqlite3.IntegrityError:
        return False

def get_unposted_postings() -> List[Dict]:
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT * FROM postings
            WHERE posted_to_discord = 0
            ORDER BY id ASC
        ''')
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
