/*
 * Módulo LLM principal.
 * Expone el estado compartido, funciones de consulta, y re-exporta
 * los tipos necesarios para que el resto de la aplicación interactúe
 * con el pipeline de Beatriz y Gary.
 */

pub mod beatriz;
pub mod client;
pub mod gary;
pub mod pipeline;
pub mod tools;

use crate::config::Config;
use crate::db::DbPool;
use crate::db::models::QueryResult;
use client::OpenRouterClient;
use std::sync::{Arc, Mutex};

pub use beatriz::RecentMessage;

/*
 * Estado compartido del sistema LLM.
 * Contiene el cliente HTTP, los modelos configurados, el esquema de la
 * base de datos, la última consulta SQL ejecutada, la última pregunta
 * del usuario, y una referencia al pool de conexiones de la base de datos.
 * Se comparte entre hilos de forma segura mediante Arc y Mutex.
 */
pub struct LlmState {
    pub client: OpenRouterClient,
    pub sql_model: String,
    pub summary_model: String,
    pub schema: String,
    pub last_sql_query: Mutex<Option<String>>,
    pub last_user_question: Mutex<Option<String>>,
    pub pool: Arc<DbPool>,
}

/*
 * Crea una nueva instancia del estado LLM a partir de la configuración
 * y un pool de conexiones compartido. Inicializa el cliente OpenRouter
 * con los parámetros de autenticación y timeout del config, y carga
 * el esquema de la base de datos.
 */
pub fn create_llm(config: &Config, pool: Arc<DbPool>) -> crate::error::Result<LlmState> {
    let client = OpenRouterClient::new(
        config.openrouter_api_key.clone(),
        config.openrouter_base_url.clone(),
        config.openrouter_timeout_seconds,
        config.openrouter_site_url.clone(),
        config.openrouter_app_name.clone(),
    )?;

    let schema = tools::get_database_schema().to_string();

    Ok(LlmState {
        client,
        sql_model: config.openrouter_sql_model.clone(),
        summary_model: config.openrouter_summary_model.clone(),
        schema,
        last_sql_query: Mutex::new(None),
        last_user_question: Mutex::new(None),
        pool,
    })
}

/*
 * Función principal para consultar el LLM.
 * Delega al pipeline que orquesta todo el flujo de Beatriz y Gary.
 * Retorna la respuesta en texto y opcionalmente los resultados de la consulta.
 */
pub async fn query_llm(
    llm: &LlmState,
    question: &str,
    recent_messages: &[RecentMessage],
) -> crate::error::Result<(String, Option<QueryResult>)> {
    pipeline::query(llm, question, recent_messages).await
}

/*
 * Obtiene la última consulta SQL ejecutada y la pregunta que la originó.
 * Se usa para que el usuario pueda inspeccionar la consulta SQL que
 * generó una respuesta particular. Retorna (None, None) si no hay
 * consulta disponible.
 */
pub fn get_last_sql_query(llm: &LlmState) -> (Option<String>, Option<String>) {
    let sql = llm.last_sql_query.lock().unwrap().clone();
    let question = llm.last_user_question.lock().unwrap().clone();
    (sql, question)
}
