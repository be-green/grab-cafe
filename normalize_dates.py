import sqlite3
from datetime import datetime
import os

DB_PATH = os.getenv("DB_PATH", "gradcafe_messages.db")

FORMAT = "%B %d, %Y"

def normalize_date(value: str) -> str | None:
    if not value:
        return None

    value = value.strip()
    try:
        return datetime.strptime(value, FORMAT).strftime("%Y-%m-%d")
    except ValueError:
        return None

def main() -> None:
    conn = sqlite3.connect(DB_PATH, timeout=30)
    cursor = conn.cursor()

    cursor.execute("PRAGMA table_info(postings)")
    columns = {row[1] for row in cursor.fetchall()}
    if "date_added_iso" not in columns:
        cursor.execute("ALTER TABLE postings ADD COLUMN date_added_iso TEXT")
        conn.commit()

    cursor.execute(
        """
        SELECT id, date_added
        FROM postings
        WHERE date_added IS NOT NULL
        AND date_added != ''
        """
    )
    rows = cursor.fetchall()

    updated = 0
    failed = 0
    processed = 0
    batch = []
    batch_size = 1000

    for row_id, date_added in rows:
        processed += 1
        normalized = normalize_date(date_added)
        if normalized is None:
            failed += 1
            continue
        batch.append((normalized, row_id))
        updated += 1

        if len(batch) >= batch_size:
            cursor.executemany(
                "UPDATE postings SET date_added_iso = ? WHERE id = ?",
                batch,
            )
            conn.commit()
            batch.clear()

    if batch:
        cursor.executemany(
            "UPDATE postings SET date_added_iso = ? WHERE id = ?",
            batch,
        )
        conn.commit()

    conn.close()

    print(f"Processed rows: {processed}")
    print(f"Updated rows: {updated}")
    print(f"Unparseable rows: {failed}")

if __name__ == "__main__":
    main()
