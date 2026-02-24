/*
 * Módulo de Beatriz Viterbo, Bibliotecaria Jefe del Archivo Interminable.
 * Planifica respuestas, resume resultados de consultas SQL,
 * y formatea datos para los usuarios del bot de Discord.
 */

use crate::db::models::QueryResult;
use crate::error::Result;
use crate::llm::client::{ChatMessage, OpenRouterClient};
use serde::{Deserialize, Serialize};
use tracing::{debug, error, info};

/*
 * Plantillas de prompts cargadas en tiempo de compilación.
 * Se insertan como cadenas estáticas desde los archivos de texto.
 */
const BEATRIZ_PLAN_SYSTEM: &str = include_str!("prompts/beatriz_plan_system.txt");
const BEATRIZ_PLAN_USER: &str = include_str!("prompts/beatriz_plan_user.txt");
const BEATRIZ_SUMMARY_SYSTEM: &str = include_str!("prompts/beatriz_summary_system.txt");
const BEATRIZ_SUMMARY_USER: &str = include_str!("prompts/beatriz_summary_user.txt");
const BEATRIZ_DESCRIBE: &str = include_str!("prompts/beatriz_describe.txt");

/*
 * Mensaje reciente del canal de Discord.
 * Se usa para proporcionar contexto conversacional al LLM,
 * permitiendo que Beatriz interprete referencias a mensajes anteriores.
 */
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RecentMessage {
    pub author: String,
    pub content: String,
    pub is_bot: bool,
}

/*
 * Formatea los mensajes recientes del canal como contexto legible para el LLM.
 * Los mensajes del bot se marcan con "(you)" para que Beatriz reconozca
 * sus propias respuestas anteriores. Retorna un texto descriptivo
 * si no hay mensajes recientes disponibles.
 */
pub fn format_recent_context(recent_messages: &[RecentMessage]) -> String {
    if recent_messages.is_empty() {
        return "No recent channel context.".to_string();
    }

    let mut lines = Vec::new();
    for (i, item) in recent_messages.iter().enumerate() {
        let content = item.content.trim();
        if content.is_empty() {
            continue;
        }
        /* Etiquetar mensajes del bot como "(you)" */
        let author_label = if item.is_bot {
            format!("{} (you)", item.author)
        } else {
            item.author.clone()
        };
        lines.push(format!("{}. {}: {}", i + 1, author_label, content));
    }

    if lines.is_empty() {
        "No recent channel context.".to_string()
    } else {
        lines.join("\n")
    }
}

/*
 * Etapa de planificación de Beatriz.
 * Lee la pregunta del usuario y decide si puede responder directamente
 * o necesita solicitar datos del archivo a Gary.
 *
 * Retorna una tupla (necesita_datos, texto):
 *   - (false, respuesta_directa): Beatriz responde sin consultar la base de datos
 *   - (true, solicitud_de_datos): Beatriz describe qué datos necesita de Gary
 *
 * Si la respuesta del LLM no comienza con "DIRECT:" ni "REQUEST_DATA:",
 * se trata como solicitud de datos por defecto.
 */
pub async fn plan_response(
    client: &OpenRouterClient,
    model: &str,
    schema: &str,
    user_question: &str,
    recent_messages: &[RecentMessage],
) -> Result<(bool, String)> {
    let recent_context = format_recent_context(recent_messages);

    let user_prompt = BEATRIZ_PLAN_USER
        .replace("{schema}", schema)
        .replace("{recent_context}", &recent_context)
        .replace("{user_question}", user_question);

    let messages = vec![
        ChatMessage {
            role: "system".into(),
            content: BEATRIZ_PLAN_SYSTEM.into(),
        },
        ChatMessage {
            role: "user".into(),
            content: user_prompt,
        },
    ];

    info!("Beatriz planificando respuesta para: {}", user_question);

    let response = client
        .chat_completion(model, messages, 0.3, 800, None)
        .await?;

    let response = response.trim().to_string();
    debug!("Plan de Beatriz: {}", response);

    if let Some(direct) = response.strip_prefix("DIRECT:") {
        let direct_response = direct.trim().to_string();
        Ok((false, direct_response))
    } else if let Some(request) = response.strip_prefix("REQUEST_DATA:") {
        let data_request = request.trim().to_string();
        Ok((true, data_request))
    } else {
        /* Alternativa: tratar como solicitud de datos */
        debug!("Plan alternativo: la respuesta no comenzó con DIRECT o REQUEST_DATA");
        Ok((true, response))
    }
}

/*
 * Beatriz resume los resultados de una consulta SQL en prosa natural.
 * Recibe la pregunta original, la solicitud de datos, la consulta SQL
 * ejecutada, y los resultados. Construye un prompt con ejemplos de
 * formato correcto e incorrecto para guiar al modelo.
 * Si el LLM falla o devuelve vacío, cae al formato de respaldo.
 */
pub async fn summarize_results(
    client: &OpenRouterClient,
    model: &str,
    user_question: &str,
    data_request: &str,
    sql_query: &str,
    query_result: &QueryResult,
    recent_messages: &[RecentMessage],
) -> Result<String> {
    /* Si hay error o no hay filas, usar formato de respaldo */
    if query_result.has_error() || !query_result.has_rows() {
        return Ok(format_results(user_question, query_result));
    }

    let rows = &query_result.rows;
    let columns = &query_result.columns;
    let row_count = query_result.row_count;
    let sample_rows: Vec<&Vec<serde_json::Value>> = rows.iter().take(5).collect();
    let recent_context = format_recent_context(recent_messages);

    /* Construir información sobre las filas de muestra */
    let sample_info = if row_count > sample_rows.len() {
        format!(
            "Showing first {} rows (results truncated for brevity)",
            sample_rows.len()
        )
    } else {
        "All rows".to_string()
    };

    /* Serializar las filas de muestra para el prompt */
    let sample_rows_str = serde_json::to_string(&sample_rows).unwrap_or_else(|_| "[]".into());
    let columns_str = format!("{:?}", columns);

    let user_prompt = BEATRIZ_SUMMARY_USER
        .replace("{recent_context}", &recent_context)
        .replace("{user_question}", user_question)
        .replace("{data_request}", data_request)
        .replace("{sql_query}", sql_query)
        .replace("{columns}", &columns_str)
        .replace("{row_count}", &row_count.to_string())
        .replace("{sample_info}", &sample_info)
        .replace("{sample_rows}", &sample_rows_str);

    let messages = vec![
        ChatMessage {
            role: "system".into(),
            content: BEATRIZ_SUMMARY_SYSTEM.into(),
        },
        ChatMessage {
            role: "user".into(),
            content: user_prompt,
        },
    ];

    /* Registrar tamaño del prompt para depuración */
    let prompt_chars = messages.iter().map(|m| m.content.len()).sum::<usize>();
    debug!(
        "Tamaño del prompt de resumen: {} caracteres (~{} tokens)",
        prompt_chars,
        prompt_chars / 4
    );

    match client.chat_completion(model, messages, 0.2, 800, None).await {
        Ok(response) => {
            let final_response = response.trim().to_string();
            if final_response.is_empty() {
                Ok(format_results(user_question, query_result))
            } else {
                debug!(
                    "Respuesta completa de Beatriz ({} caracteres): {}",
                    final_response.len(),
                    final_response
                );
                Ok(final_response)
            }
        }
        Err(e) => {
            error!("Error en summarize_results: {}", e);
            Ok(format_results(user_question, query_result))
        }
    }
}

/*
 * Formato de respaldo para resultados de consulta SQL.
 * Se usa cuando el LLM no está disponible o falla.
 * Aplica heurísticas basadas en la forma de los datos:
 *   - Un solo valor escalar: formatea según la pregunta (promedio, conteo, porcentaje)
 *   - Dos columnas con pocas filas: lista compacta
 *   - Pocas filas de una columna: lista separada por comas
 *   - Muchas filas: mensaje genérico con conteo
 */
pub fn format_results(user_question: &str, query_result: &QueryResult) -> String {
    if let Some(ref err) = query_result.error {
        return format!("I encountered an error: {}", err);
    }

    if !query_result.has_rows() {
        return "I found no results for that query.".to_string();
    }

    let rows = &query_result.rows;
    let columns = &query_result.columns;
    let question_lower = user_question.to_lowercase();

    /* Caso: un solo valor escalar */
    if rows.len() == 1 && rows[0].len() == 1 {
        let value = &rows[0][0];
        if let Some(n) = value.as_f64() {
            if question_lower.contains("average") || question_lower.contains("mean") {
                return format!("The average is {:.2}", n);
            } else if question_lower.contains("count") || question_lower.contains("how many") {
                return format!("There are {} results", n as i64);
            } else if question_lower.contains("percentage") || question_lower.contains("percent")
            {
                return format!("{:.1}%", n);
            }
        }
        if let Some(n) = value.as_i64() {
            if question_lower.contains("average") || question_lower.contains("mean") {
                return format!("The average is {}", n);
            } else if question_lower.contains("count") || question_lower.contains("how many") {
                return format!("There are {} results", n);
            } else if question_lower.contains("percentage") || question_lower.contains("percent")
            {
                return format!("{}%", n);
            }
        }
        return format!("The answer is: {}", value_to_display(value));
    }

    /* Caso: dos columnas con pocas filas */
    if columns.len() == 2 && rows.len() <= 10 {
        let items: Vec<String> = rows
            .iter()
            .take(5)
            .map(|row| {
                format!(
                    "{} ({})",
                    value_to_display(&row[0]),
                    value_to_display(&row[1])
                )
            })
            .collect();

        if rows.len() <= 3 {
            return format!("The records show {}.", items.join(", "));
        } else {
            let top3: Vec<String> = items.into_iter().take(3).collect();
            return format!("Top results include {}, among others.", top3.join(", "));
        }
    }

    /* Caso: pocas filas */
    if rows.len() <= 5 {
        if rows[0].len() == 1 {
            let items: Vec<String> = rows.iter().map(|row| value_to_display(&row[0])).collect();
            return format!("I found: {}.", items.join(", "));
        } else {
            return format!("I found {} records matching your query.", rows.len());
        }
    }

    format!("I cataloged {} results for that query.", rows.len())
}

/*
 * Beatriz describe brevemente los resultados de una consulta y sus columnas.
 * Se usa cuando hay demasiadas filas para resumir todos los datos,
 * proporcionando al usuario una guía sobre cómo interpretar las columnas.
 */
pub async fn describe_query_results(
    client: &OpenRouterClient,
    model: &str,
    user_question: &str,
    query_result: &QueryResult,
) -> Result<String> {
    if query_result.has_error() || !query_result.has_rows() {
        return Ok(String::new());
    }

    let columns = &query_result.columns;
    let row_count = query_result.rows.len();

    let columns_joined = columns.join(", ");

    let prompt = BEATRIZ_DESCRIBE
        .replace("{user_question}", user_question)
        .replace("{row_count}", &row_count.to_string())
        .replace("{columns}", &columns_joined);

    let messages = vec![
        ChatMessage {
            role: "system".into(),
            content: "You are a librarian helping users understand query results. Be concise."
                .into(),
        },
        ChatMessage {
            role: "user".into(),
            content: prompt,
        },
    ];

    let response = client
        .chat_completion(model, messages, 0.3, 300, None)
        .await?;

    Ok(response.trim().to_string())
}

/*
 * Convierte un valor JSON a su representación de texto para mostrar al usuario.
 * Los números con decimales se formatean a dos posiciones.
 * Los nulos se muestran como "N/A".
 */
fn value_to_display(value: &serde_json::Value) -> String {
    match value {
        serde_json::Value::String(s) => s.clone(),
        serde_json::Value::Number(n) => {
            if let Some(f) = n.as_f64() {
                if f.fract() == 0.0 {
                    format!("{}", f as i64)
                } else {
                    format!("{:.2}", f)
                }
            } else {
                n.to_string()
            }
        }
        serde_json::Value::Null => "N/A".to_string(),
        serde_json::Value::Bool(b) => b.to_string(),
        other => other.to_string(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_formato_contexto_vacio() {
        /* Verifica que sin mensajes retorna el texto por defecto */
        let result = format_recent_context(&[]);
        assert_eq!(result, "No recent channel context.");
    }

    #[test]
    fn test_formato_contexto_con_mensajes() {
        /* Verifica formateo correcto con mensajes de usuario y bot */
        let messages = vec![
            RecentMessage {
                author: "Alice".into(),
                content: "Hello".into(),
                is_bot: false,
            },
            RecentMessage {
                author: "Bot".into(),
                content: "Hi there".into(),
                is_bot: true,
            },
        ];
        let result = format_recent_context(&messages);
        assert!(result.contains("1. Alice: Hello"));
        assert!(result.contains("2. Bot (you): Hi there"));
    }

    #[test]
    fn test_formato_ignora_mensajes_vacios() {
        /* Verifica que los mensajes con contenido vacío se ignoran */
        let messages = vec![
            RecentMessage {
                author: "Alice".into(),
                content: "".into(),
                is_bot: false,
            },
            RecentMessage {
                author: "Bob".into(),
                content: "  ".into(),
                is_bot: false,
            },
        ];
        let result = format_recent_context(&messages);
        assert_eq!(result, "No recent channel context.");
    }

    #[test]
    fn test_formato_resultado_error() {
        /* Verifica formato de error en resultados */
        let result = QueryResult::error("Database locked".into());
        let formatted = format_results("test", &result);
        assert!(formatted.contains("Database locked"));
    }

    #[test]
    fn test_formato_resultado_vacio() {
        /* Verifica formato cuando no hay filas */
        let result = QueryResult::empty();
        let formatted = format_results("test", &result);
        assert_eq!(formatted, "I found no results for that query.");
    }

    #[test]
    fn test_formato_valor_escalar_conteo() {
        /* Verifica formato de conteo escalar */
        let result = QueryResult {
            error: None,
            columns: vec!["count".into()],
            rows: vec![vec![serde_json::json!(42)]],
            row_count: 1,
        };
        let formatted = format_results("how many acceptances", &result);
        assert!(formatted.contains("42"));
    }

    #[test]
    fn test_formato_valor_escalar_promedio() {
        /* Verifica formato de promedio escalar */
        let result = QueryResult {
            error: None,
            columns: vec!["avg_gpa".into()],
            rows: vec![vec![serde_json::json!(3.85)]],
            row_count: 1,
        };
        let formatted = format_results("average gpa", &result);
        assert!(formatted.contains("3.85"));
    }

    #[test]
    fn test_value_to_display_numero_entero() {
        /* Verifica que números enteros no muestran decimales */
        assert_eq!(value_to_display(&serde_json::json!(42)), "42");
    }

    #[test]
    fn test_value_to_display_numero_decimal() {
        /* Verifica que números decimales se formatean a 2 posiciones */
        assert_eq!(value_to_display(&serde_json::json!(3.856)), "3.86");
    }

    #[test]
    fn test_value_to_display_nulo() {
        /* Verifica que nulos se muestran como N/A */
        assert_eq!(value_to_display(&serde_json::Value::Null), "N/A");
    }
}
