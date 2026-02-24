/*
 * Herramientas SQL para el módulo LLM.
 * Validación de seguridad de consultas y ejecución de solo lectura contra SQLite.
 * También proporciona el esquema de la base de datos como texto estático.
 */

use crate::db::DbPool;
use crate::db::models::QueryResult;
use tracing::{debug, error};

/*
 * Palabras clave SQL prohibidas que no deben aparecer en ninguna consulta.
 * Se verifican en mayúsculas contra la versión en mayúsculas de la consulta.
 */
const FORBIDDEN_KEYWORDS: &[&str] = &[
    "INSERT", "UPDATE", "DELETE", "DROP", "CREATE", "ALTER", "TRUNCATE",
];

/*
 * Esquema de la base de datos embebido como cadena estática.
 * Se usa para inyectar en los prompts del LLM para que conozca
 * la estructura de las tablas disponibles.
 */
const DATABASE_SCHEMA: &str = r#"
GradCafe Economics Database Schema:

Table: phd (the DEFAULT)
Simplified aggregation table for PhD programs (2018+)
Columns:
  - school: TEXT (university name)
  - program: TEXT (program name)
  - decision_date: DATE (ISO format YYYY-MM-DD, when the decision was made)
  - gpa: REAL (GPA score)
  - gre: REAL (GRE quantitative score)
  - result: TEXT (Accepted, Rejected, Interview, Waitlist)

Total PhD postings: ~8,241

Table: masters (RECOMMENDED for Masters-specific queries)
Simplified aggregation table for Masters programs (2018+)
Columns:
  - school: TEXT (university name)
  - program: TEXT (program name)
  - decision_date: DATE (ISO format YYYY-MM-DD, when the decision was made)
  - gpa: REAL (GPA score)
  - gre: REAL (GRE quantitative score)
  - result: TEXT (Accepted, Rejected, Interview, Waitlist)

Total Masters postings: ~1,155


Table: postings
Columns:
  - id: INTEGER (primary key)
  - gradcafe_id: TEXT (unique identifier from GradCafe)
  - school: TEXT (university name)
  - program: TEXT (program name, e.g., "Economics")
  - degree: TEXT (PhD, Masters, etc.)
  - decision: TEXT (e.g., "Accepted on 15 Dec", "Rejected on 20 Nov")
  - date_added: TEXT (raw GradCafe date text, e.g., "December 15, 2025")
  - date_added_iso: TEXT (normalized ISO date "YYYY-MM-DD" when available)
  - season: TEXT (e.g., "Fall 2026", "Spring 2025")
  - status: TEXT (International, American, Other)
  - gpa: REAL (e.g., 3.85)
  - gre_quant: REAL (quantitative GRE score)
  - gre_verbal: REAL (verbal GRE score)
  - gre_aw: REAL (analytical writing GRE score)
  - comment: TEXT (user comments)
  - scraped_at: TIMESTAMP (when we scraped it)
  - posted_to_discord: BOOLEAN (0 or 1)
  - result: TEXT (extracted result: Accepted, Rejected, Interview, Waitlist)
  - decision_date: TEXT (extracted decision date)

Total postings: ~30,545 individual admissions results

IMPORTANT: Use the 'phd' or 'masters' tables for simpler queries when you only need
school, program, scores, and result. These tables are filtered for 2018+ and by degree type.
Use the 'postings' table when you need additional fields like dates, status, season, or comments.

Common queries:
- Count acceptances by school (use phd/masters tables)
- Average GPA/GRE by decision type (use phd/masters tables)
- Acceptance rates over time (use postings table for date_added_iso)
- International vs American acceptance rates (use postings table for status)
- When do schools typically send decisions (use postings table for decision_date or date_added_iso)
"#;

/*
 * Devuelve el esquema de la base de datos como referencia estática.
 * Se usa en los prompts del LLM para que el modelo conozca
 * las tablas, columnas y tipos disponibles.
 */
pub fn get_database_schema() -> &'static str {
    DATABASE_SCHEMA
}

/*
 * Ejecuta una consulta SQL de solo lectura contra la base de datos.
 * Primero valida que la consulta comience con SELECT y no contenga
 * palabras clave prohibidas (INSERT, UPDATE, DELETE, etc.).
 * Devuelve un QueryResult con columnas, filas y conteo de resultados,
 * o un QueryResult con error si la validación o ejecución falla.
 */
pub fn execute_sql_query(pool: &DbPool, query: &str) -> QueryResult {
    let query = query.trim();

    /* Verificar que la consulta comience con SELECT */
    if !query.to_uppercase().starts_with("SELECT") {
        return QueryResult::error(
            "Only SELECT queries are allowed for safety reasons.".into(),
        );
    }

    /* Verificar palabras clave prohibidas */
    let query_upper = query.to_uppercase();
    for keyword in FORBIDDEN_KEYWORDS {
        if query_upper.contains(keyword) {
            return QueryResult::error(format!(
                "Query contains forbidden keyword: {}",
                keyword
            ));
        }
    }

    /* Ejecutar la consulta contra la base de datos */
    let conn = pool.get();

    let mut stmt = match conn.prepare(query) {
        Ok(s) => s,
        Err(e) => {
            error!("Error al preparar consulta SQL: {}", e);
            return QueryResult::error(e.to_string());
        }
    };

    let column_names: Vec<String> = stmt
        .column_names()
        .iter()
        .map(|s| s.to_string())
        .collect();

    let rows_result = stmt.query_map([], |row| {
        let mut values = Vec::new();
        for i in 0..column_names.len() {
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
            values.push(json_val);
        }
        Ok(values)
    });

    match rows_result {
        Ok(rows) => {
            let mut data: Vec<Vec<serde_json::Value>> = Vec::new();
            for row in rows {
                match row {
                    Ok(values) => data.push(values),
                    Err(e) => {
                        error!("Error al leer fila: {}", e);
                        return QueryResult::error(e.to_string());
                    }
                }
            }

            let row_count = data.len();
            debug!("Consulta ejecutada exitosamente: {} filas", row_count);

            QueryResult {
                error: None,
                columns: if data.is_empty() {
                    vec![]
                } else {
                    column_names
                },
                rows: data,
                row_count,
            }
        }
        Err(e) => {
            error!("Error al ejecutar consulta SQL: {}", e);
            QueryResult::error(e.to_string())
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_rechaza_consulta_insert() {
        /* Verifica que INSERT sea rechazado */
        let pool = DbPool::new(":memory:").unwrap();
        let result = execute_sql_query(&pool, "INSERT INTO phd VALUES ('test')");
        assert!(result.has_error());
        assert!(result.error.unwrap().contains("Only SELECT"));
    }

    #[test]
    fn test_rechaza_consulta_drop() {
        /* Verifica que DROP dentro de un SELECT sea rechazado */
        let pool = DbPool::new(":memory:").unwrap();
        let result = execute_sql_query(&pool, "SELECT * FROM phd; DROP TABLE phd");
        assert!(result.has_error());
        assert!(result.error.unwrap().contains("DROP"));
    }

    #[test]
    fn test_esquema_no_vacio() {
        /* Verifica que el esquema contiene las tablas esperadas */
        let schema = get_database_schema();
        assert!(schema.contains("phd"));
        assert!(schema.contains("masters"));
        assert!(schema.contains("postings"));
    }
}
