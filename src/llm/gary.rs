/*
 * Módulo de Gary, el ingeniero SQL del Archivo Interminable.
 * Genera consultas SQL a partir de las solicitudes de datos de Beatriz
 * y extrae SQL válido de las respuestas del modelo LLM.
 */

use crate::error::Result;
use crate::llm::client::{ChatMessage, OpenRouterClient};
use regex::Regex;
use tracing::{debug, info};

/*
 * Plantillas de prompts cargadas en tiempo de compilación.
 * Se insertan como cadenas estáticas desde los archivos de texto.
 */
const GARY_SYSTEM_PROMPT: &str = include_str!("prompts/gary_system.txt");
const GARY_USER_TEMPLATE: &str = include_str!("prompts/gary_user.txt");

/*
 * Genera una consulta SQL basada en la solicitud de datos de Beatriz.
 * Construye el prompt con el esquema, contexto reciente, solicitud de
 * Beatriz y la pregunta original del usuario. Envía al modelo y
 * devuelve la respuesta sin espacios en blanco adicionales.
 */
pub async fn generate_sql(
    client: &OpenRouterClient,
    model: &str,
    schema: &str,
    beatriz_request: &str,
    user_question: &str,
    recent_context: &str,
) -> Result<String> {
    let user_prompt = GARY_USER_TEMPLATE
        .replace("{recent_context}", recent_context)
        .replace("{schema}", schema)
        .replace("{beatriz_request}", beatriz_request)
        .replace("{user_question}", user_question);

    let messages = vec![
        ChatMessage {
            role: "system".into(),
            content: GARY_SYSTEM_PROMPT.into(),
        },
        ChatMessage {
            role: "user".into(),
            content: user_prompt,
        },
    ];

    info!("Enviando solicitud de generación SQL a Gary");

    let response = client
        .chat_completion(model, messages, 0.2, 3000, None)
        .await?;

    let sql = response.trim().to_string();
    debug!("Gary generó SQL: {}", sql);

    Ok(sql)
}

/*
 * Extrae una consulta SQL válida del texto de respuesta del modelo.
 * Maneja cuatro casos en orden de prioridad:
 *   1. Bloques de código SQL con delimitadores ```sql ... ```
 *   2. Texto que comienza directamente con SELECT o WITH
 *   3. WITH (CTE) encontrado en cualquier parte del texto
 *   4. SELECT encontrado en cualquier parte del texto
 * En todos los casos, elimina el punto y coma final si existe.
 * Retorna None si no se puede encontrar SQL válido.
 */
pub fn extract_sql(text: &str) -> Option<String> {
    let text = text.trim();

    /* Caso 1: bloque de código SQL con delimitadores markdown */
    if text.to_lowercase().contains("```sql") {
        let parts: Vec<&str> = text.split("```").collect();
        for part in &parts {
            let trimmed = part.trim();
            if trimmed.to_lowercase().starts_with("sql") {
                let sql_content = trimmed[3..].trim();
                return Some(sql_content.trim_end_matches(';').to_string());
            }
        }
    }

    /* Caso 2: el texto comienza directamente con SELECT o WITH */
    let text_upper = text.to_uppercase();
    if text_upper.starts_with("SELECT") || text_upper.starts_with("WITH") {
        let mut sql_lines = Vec::new();
        for line in text.lines() {
            let clean_line = line.trim();
            if clean_line.is_empty() {
                continue;
            }
            if clean_line.starts_with('#') || clean_line.starts_with("--") {
                continue;
            }
            sql_lines.push(clean_line);
            if clean_line.contains(';') {
                break;
            }
        }
        let joined = sql_lines.join(" ");
        return Some(joined.trim_end_matches(';').to_string());
    }

    /* Caso 3: buscar WITH (CTE) en cualquier parte del texto */
    let cte_re = Regex::new(r"(?is)(WITH\s+.+)").unwrap();
    if let Some(caps) = cte_re.captures(text) {
        let sql_text = caps.get(1).unwrap().as_str().trim();
        let result = if let Some(idx) = sql_text.find(';') {
            &sql_text[..idx]
        } else {
            sql_text
        };
        return Some(result.trim_end_matches(';').to_string());
    }

    /* Caso 4: buscar SELECT en cualquier parte del texto */
    let select_re = Regex::new(r"(?is)(SELECT\s+.+?)(?:;|\n\n|$)").unwrap();
    if let Some(caps) = select_re.captures(text) {
        let sql_text = caps.get(1).unwrap().as_str().trim();
        return Some(sql_text.trim_end_matches(';').to_string());
    }

    None
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_extrae_sql_de_bloque_codigo() {
        /* Verifica extracción desde bloque markdown con ```sql */
        let text = "Here is the query:\n```sql\nSELECT * FROM phd\n```\nDone.";
        let result = extract_sql(text);
        assert_eq!(result, Some("SELECT * FROM phd".to_string()));
    }

    #[test]
    fn test_extrae_sql_directo() {
        /* Verifica extracción cuando el texto comienza con SELECT */
        let text = "SELECT COUNT(*) FROM phd WHERE result = 'Accepted';";
        let result = extract_sql(text);
        assert_eq!(
            result,
            Some("SELECT COUNT(*) FROM phd WHERE result = 'Accepted'".to_string())
        );
    }

    #[test]
    fn test_extrae_cte() {
        /* Verifica extracción de CTE con WITH */
        let text = "Sure, here:\nWITH cte AS (SELECT * FROM phd) SELECT * FROM cte;";
        let result = extract_sql(text);
        assert!(result.is_some());
        assert!(result.unwrap().starts_with("WITH cte AS"));
    }

    #[test]
    fn test_extrae_select_embebido() {
        /* Verifica extracción de SELECT embebido en texto libre */
        let text = "The query would be: SELECT school FROM phd WHERE result = 'Accepted'";
        let result = extract_sql(text);
        assert!(result.is_some());
        assert!(result.unwrap().contains("SELECT school FROM phd"));
    }

    #[test]
    fn test_retorna_none_sin_sql() {
        /* Verifica que retorna None cuando no hay SQL */
        let text = "I don't know how to answer that.";
        let result = extract_sql(text);
        assert!(result.is_none());
    }

    #[test]
    fn test_elimina_punto_y_coma() {
        /* Verifica que se elimina el punto y coma final */
        let text = "SELECT 1;";
        let result = extract_sql(text);
        assert_eq!(result, Some("SELECT 1".to_string()));
    }

    #[test]
    fn test_ignora_comentarios_sql() {
        /* Verifica que se ignoran líneas de comentarios */
        let text = "SELECT school\n-- this is a comment\nFROM phd";
        let result = extract_sql(text);
        assert!(result.is_some());
        let sql = result.unwrap();
        assert!(sql.contains("SELECT school"));
        assert!(sql.contains("FROM phd"));
        assert!(!sql.contains("-- this is a comment"));
    }
}
