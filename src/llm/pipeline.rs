/*
 * Pipeline principal del LLM.
 * Orquesta el flujo completo: planificación de Beatriz, generación de SQL
 * por Gary, ejecución de la consulta, y resumen de resultados.
 */

use crate::db::models::QueryResult;
use crate::error::Result;
use crate::llm::beatriz::{self, RecentMessage};
use crate::llm::gary;
use crate::llm::tools;
use crate::llm::LlmState;
use tracing::{info, warn};

/*
 * Método principal de consulta que orquesta todo el pipeline del LLM.
 *
 * Flujo:
 * 1. Beatriz analiza la pregunta y decide si necesita datos del archivo
 * 2. Si responde directamente, retorna la respuesta sin consulta SQL
 * 3. Si necesita datos, Gary genera una consulta SQL
 * 4. Se extrae y valida el SQL de la respuesta de Gary
 * 5. Se ejecuta la consulta contra la base de datos
 * 6. Beatriz resume los resultados en prosa natural
 *
 * Almacena la última consulta SQL y pregunta en el estado del LLM
 * para que puedan ser recuperadas posteriormente (por ejemplo,
 * para mostrar la consulta al usuario bajo demanda).
 *
 * Retorna una tupla con la respuesta final y opcionalmente
 * el QueryResult con los datos crudos.
 */
pub async fn query(
    llm: &LlmState,
    user_question: &str,
    recent_messages: &[RecentMessage],
) -> Result<(String, Option<QueryResult>)> {
    info!("Pregunta: {}", user_question);

    /* Almacenar la pregunta */
    {
        let mut last_question = llm.last_user_question.lock().unwrap();
        *last_question = Some(user_question.to_string());
    }

    /* Paso 1: Beatriz lee la pregunta y decide qué necesita */
    let (needs_data, response_or_request) = beatriz::plan_response(
        &llm.client,
        &llm.summary_model,
        &llm.schema,
        user_question,
        recent_messages,
    )
    .await?;

    if !needs_data {
        /* Beatriz respondió directamente; no se necesita consulta SQL */
        {
            let mut last_sql = llm.last_sql_query.lock().unwrap();
            *last_sql = None;
        }
        return Ok((response_or_request, None));
    }

    /* Paso 2: Beatriz necesita datos; enviar su solicitud a Gary */
    let data_request = response_or_request;

    let recent_context = beatriz::format_recent_context(recent_messages);

    let sql_response = gary::generate_sql(
        &llm.client,
        &llm.sql_model,
        &llm.schema,
        &data_request,
        user_question,
        &recent_context,
    )
    .await?;

    info!("SQL generado: {}", sql_response);

    let sql_query = match gary::extract_sql(&sql_response) {
        Some(sql) if sql_response.trim().to_lowercase() != "none" => sql,
        _ => {
            warn!("No se pudo extraer SQL válido de la respuesta de Gary");
            let mut last_sql = llm.last_sql_query.lock().unwrap();
            *last_sql = None;
            return Ok((
                "I couldn't generate a valid SQL query for that request. Could you rephrase your question?".to_string(),
                None,
            ));
        }
    };

    /* Almacenar la consulta SQL */
    {
        let mut last_sql = llm.last_sql_query.lock().unwrap();
        *last_sql = Some(sql_query.clone());
    }

    /* Paso 3: Ejecutar la consulta de Gary */
    info!("Ejecutando: {}", sql_query);
    let result = tools::execute_sql_query(&llm.pool, &sql_query);

    /* Paso 4: Beatriz interpreta los resultados y formula la respuesta final */
    let final_response = beatriz::summarize_results(
        &llm.client,
        &llm.summary_model,
        user_question,
        &data_request,
        &sql_query,
        &result,
        recent_messages,
    )
    .await?;

    Ok((final_response, Some(result)))
}
