/*
 * Operaciones CRUD sobre la base de datos.
 * Inicialización de tablas, inserción, consultas, deduplicación,
 * actualización de tablas de agregación, y formato para Discord.
 */

use super::DbPool;
use super::models::Posting;
use rusqlite::params;
use std::collections::HashMap;

/// Inicializa la base de datos creando tablas e índices
pub fn init_database(pool: &DbPool) -> crate::error::Result<()> {
    let conn = pool.get();

    conn.execute_batch(
        "CREATE TABLE IF NOT EXISTS postings (
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
            gre_combined REAL,
            comment TEXT,
            scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            posted_to_discord BOOLEAN DEFAULT 0
        );",
    )?;

    /* Verificar y agregar columnas que pueden faltar en bases existentes */
    let has_column = |col: &str| -> bool {
        let mut stmt = conn.prepare("PRAGMA table_info(postings)").unwrap();
        let cols: Vec<String> = stmt
            .query_map([], |row| row.get::<_, String>(1))
            .unwrap()
            .filter_map(|r| r.ok())
            .collect();
        cols.contains(&col.to_string())
    };

    if !has_column("date_added_iso") {
        conn.execute_batch("ALTER TABLE postings ADD COLUMN date_added_iso TEXT")?;
    }
    if !has_column("gre_combined") {
        conn.execute_batch("ALTER TABLE postings ADD COLUMN gre_combined REAL")?;
    }

    conn.execute_batch(
        "CREATE INDEX IF NOT EXISTS idx_gradcafe_id ON postings(gradcafe_id);
         CREATE INDEX IF NOT EXISTS idx_posted ON postings(posted_to_discord);
         CREATE INDEX IF NOT EXISTS idx_scraped_at ON postings(scraped_at);
         CREATE INDEX IF NOT EXISTS idx_school ON postings(school);
         CREATE INDEX IF NOT EXISTS idx_date_added ON postings(date_added);",
    )?;

    Ok(())
}

/// Verifica si un posting ya existe por gradcafe_id
pub fn posting_exists(pool: &DbPool, gradcafe_id: &str) -> crate::error::Result<bool> {
    let conn = pool.get();
    let mut stmt = conn.prepare(
        "SELECT 1 FROM postings WHERE gradcafe_id = ? LIMIT 1",
    )?;
    let exists = stmt.exists(params![gradcafe_id])?;
    Ok(exists)
}

/// Verifica si un posting existe dentro de los últimos N días
pub fn posting_exists_recent(
    pool: &DbPool,
    gradcafe_id: &str,
    days_back: i64,
) -> crate::error::Result<bool> {
    let conn = pool.get();
    let mut stmt = conn.prepare(
        "SELECT 1 FROM postings
         WHERE gradcafe_id = ?
         AND scraped_at >= datetime('now', '-' || ? || ' days')
         LIMIT 1",
    )?;
    let exists = stmt.exists(params![gradcafe_id, days_back])?;
    Ok(exists)
}

/// Inserta un nuevo posting. Retorna true si se insertó, false si ya existía.
pub fn add_posting(pool: &DbPool, posting: &Posting) -> crate::error::Result<bool> {
    let conn = pool.get();
    let result = conn.execute(
        "INSERT INTO postings (
            gradcafe_id, school, program, degree, decision, date_added,
            date_added_iso, season, status, gpa, gre_quant, gre_verbal, gre_aw, gre_combined, comment
        ) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11, ?12, ?13, ?14, ?15)",
        params![
            posting.gradcafe_id,
            posting.school,
            posting.program,
            posting.degree,
            posting.decision,
            posting.date_added,
            posting.date_added_iso,
            posting.season,
            posting.status,
            posting.gpa,
            posting.gre_quant,
            posting.gre_verbal,
            posting.gre_aw,
            posting.gre_combined,
            posting.comment,
        ],
    );

    match result {
        Ok(_) => Ok(true),
        Err(rusqlite::Error::SqliteFailure(err, _))
            if err.code == rusqlite::ffi::ErrorCode::ConstraintViolation =>
        {
            Ok(false)
        }
        Err(e) => Err(e.into()),
    }
}

/// Obtiene postings no publicados en Discord dentro de los últimos N días
pub fn get_unposted_postings(
    pool: &DbPool,
    days_back: i64,
) -> crate::error::Result<Vec<HashMap<String, serde_json::Value>>> {
    let conn = pool.get();
    let mut stmt = conn.prepare(
        "SELECT * FROM postings
         WHERE posted_to_discord = 0
         AND date_added_iso IS NOT NULL
         AND date_added_iso >= date('now', '-' || ? || ' days')
         ORDER BY id ASC",
    )?;

    let column_names: Vec<String> = stmt
        .column_names()
        .iter()
        .map(|s| s.to_string())
        .collect();

    let rows = stmt.query_map(params![days_back], |row| {
        let mut map = HashMap::new();
        for (i, col) in column_names.iter().enumerate() {
            let val: rusqlite::types::Value = row.get(i)?;
            let json_val = match val {
                rusqlite::types::Value::Null => serde_json::Value::Null,
                rusqlite::types::Value::Integer(n) => serde_json::json!(n),
                rusqlite::types::Value::Real(f) => serde_json::json!(f),
                rusqlite::types::Value::Text(s) => serde_json::json!(s),
                rusqlite::types::Value::Blob(b) => {
                    serde_json::json!(String::from_utf8_lossy(&b).to_string())
                }
            };
            map.insert(col.clone(), json_val);
        }
        Ok(map)
    })?;

    let mut result = Vec::new();
    for row in rows {
        result.push(row?);
    }
    Ok(result)
}

/// Marca un posting como publicado en Discord
pub fn mark_posting_as_posted(pool: &DbPool, posting_id: i64) -> crate::error::Result<()> {
    let conn = pool.get();
    conn.execute(
        "UPDATE postings SET posted_to_discord = 1 WHERE id = ?",
        params![posting_id],
    )?;
    Ok(())
}

/// Refresca las tablas de agregación phd y masters
pub fn refresh_aggregation_tables(pool: &DbPool) -> crate::error::Result<()> {
    let conn = pool.get();

    conn.execute_batch("DROP TABLE IF EXISTS phd")?;
    conn.execute_batch(
        "CREATE TABLE phd AS
         SELECT
             school,
             program,
             date_added_iso as decision_date,
             gpa,
             gre_quant as gre,
             gre_combined,
             CASE
                 WHEN decision LIKE '%Accepted%' THEN 'Accepted'
                 WHEN decision LIKE '%Rejected%' THEN 'Rejected'
                 WHEN decision LIKE '%Interview%' THEN 'Interview'
                 WHEN decision LIKE '%Wait%list%' THEN 'Wait listed'
                 ELSE 'Other'
             END as result
         FROM postings
         WHERE degree = 'PhD'
         AND date_added_iso IS NOT NULL
         AND CAST(strftime('%Y', date_added_iso) AS INTEGER) >= 2018",
    )?;

    conn.execute_batch("DROP TABLE IF EXISTS masters")?;
    conn.execute_batch(
        "CREATE TABLE masters AS
         SELECT
             school,
             program,
             date_added_iso as decision_date,
             gpa,
             gre_quant as gre,
             gre_combined,
             CASE
                 WHEN decision LIKE '%Accepted%' THEN 'Accepted'
                 WHEN decision LIKE '%Rejected%' THEN 'Rejected'
                 WHEN decision LIKE '%Interview%' THEN 'Interview'
                 WHEN decision LIKE '%Wait%list%' THEN 'Wait listed'
                 ELSE 'Other'
             END as result
         FROM postings
         WHERE degree = 'Masters'
         AND date_added_iso IS NOT NULL
         AND CAST(strftime('%Y', date_added_iso) AS INTEGER) >= 2018",
    )?;

    Ok(())
}

/// Formatea un posting para enviar a Discord
pub fn format_posting_for_discord(posting: &HashMap<String, serde_json::Value>) -> String {
    let get_str = |key: &str| -> Option<String> {
        posting.get(key).and_then(|v| match v {
            serde_json::Value::String(s) if !s.is_empty() => Some(s.clone()),
            _ => None,
        })
    };

    let get_num = |key: &str| -> Option<f64> {
        posting.get(key).and_then(|v| match v {
            serde_json::Value::Number(n) => n.as_f64(),
            _ => None,
        })
    };

    let mut lines = Vec::new();

    /* Nombre de la escuela en negrita */
    let school = get_str("school").unwrap_or_default();
    lines.push(format!("**{}**", school));

    /* Programa y grado */
    let program = get_str("program").unwrap_or_default();
    if let Some(degree) = get_str("degree") {
        lines.push(format!("{} ({})", program, degree));
    } else {
        lines.push(program);
    }

    /* Decisión en cursiva */
    let decision = get_str("decision").unwrap_or_default();
    lines.push(format!("_{}_", decision));

    /* Detalles separados por pipe */
    let mut details = Vec::new();
    if let Some(season) = get_str("season") {
        details.push(season);
    }
    if let Some(status) = get_str("status") {
        details.push(status);
    }
    if let Some(gpa) = get_num("gpa") {
        details.push(format!("GPA: {}", gpa));
    }

    let mut gre_parts = Vec::new();
    if let Some(gre_quant) = get_num("gre_quant") {
        gre_parts.push(format!("Q:{}", gre_quant));
    }
    if let Some(gre_verbal) = get_num("gre_verbal") {
        gre_parts.push(format!("V:{}", gre_verbal));
    }
    if let Some(gre_aw) = get_num("gre_aw") {
        gre_parts.push(format!("AW:{}", gre_aw));
    }
    if let Some(gre_combined) = get_num("gre_combined") {
        gre_parts.push(format!("Total:{}", gre_combined));
    }
    if !gre_parts.is_empty() {
        details.push(format!("GRE: {}", gre_parts.join(" ")));
    }

    if !details.is_empty() {
        lines.push(details.join(" | "));
    }

    /* Comentario entre comillas */
    if let Some(comment) = get_str("comment") {
        lines.push(format!("\"{}\"", comment));
    }

    /* Fecha de adición */
    let date_added = get_str("date_added").unwrap_or_default();
    lines.push(format!("Added: {}", date_added));

    lines.join("\n")
}
