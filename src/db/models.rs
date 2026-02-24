/*
 * Modelos de datos para la base de datos.
 * Posting representa una entrada de GradCafe, QueryResult el resultado de una consulta SQL.
 */

use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Posting {
    pub id: Option<i64>,
    pub gradcafe_id: String,
    pub school: String,
    pub program: String,
    pub degree: Option<String>,
    pub decision: String,
    pub date_added: String,
    pub date_added_iso: Option<String>,
    pub season: Option<String>,
    pub status: Option<String>,
    pub gpa: Option<f64>,
    pub gre_quant: Option<f64>,
    pub gre_verbal: Option<f64>,
    pub gre_aw: Option<f64>,
    pub gre_combined: Option<f64>,
    pub comment: Option<String>,
    pub scraped_at: Option<String>,
    pub posted_to_discord: Option<bool>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct QueryResult {
    pub error: Option<String>,
    pub columns: Vec<String>,
    pub rows: Vec<Vec<serde_json::Value>>,
    pub row_count: usize,
}

impl QueryResult {
    pub fn error(msg: String) -> Self {
        QueryResult {
            error: Some(msg),
            columns: vec![],
            rows: vec![],
            row_count: 0,
        }
    }

    pub fn empty() -> Self {
        QueryResult {
            error: None,
            columns: vec![],
            rows: vec![],
            row_count: 0,
        }
    }

    pub fn has_error(&self) -> bool {
        self.error.is_some()
    }

    pub fn has_rows(&self) -> bool {
        !self.rows.is_empty()
    }
}
