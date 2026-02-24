/*
 * Configuración tipada desde variables de entorno.
 * Carga todos los parámetros necesarios para el bot.
 */

use crate::error::GradCafeError;

#[derive(Debug, Clone)]
pub struct Config {
    pub discord_token: String,
    pub discord_channel_id: u64,
    pub openrouter_api_key: String,
    pub openrouter_base_url: String,
    pub openrouter_sql_model: String,
    pub openrouter_summary_model: String,
    pub openrouter_timeout_seconds: u64,
    pub openrouter_site_url: Option<String>,
    pub openrouter_app_name: Option<String>,
    pub check_interval_seconds: u64,
    pub enable_llm: bool,
    pub post_lookback_days: i64,
    pub db_path: String,
}

impl Config {
    /// Carga la configuración desde variables de entorno
    pub fn from_env() -> Result<Self, GradCafeError> {
        let discord_token = std::env::var("DISCORD_TOKEN")
            .map_err(|_| GradCafeError::Config("DISCORD_TOKEN no configurado".into()))?;

        let discord_channel_id: u64 = std::env::var("DISCORD_CHANNEL_ID")
            .map_err(|_| GradCafeError::Config("DISCORD_CHANNEL_ID no configurado".into()))?
            .parse()
            .map_err(|_| GradCafeError::Config("DISCORD_CHANNEL_ID no es un número válido".into()))?;

        if discord_channel_id == 0 {
            return Err(GradCafeError::Config("DISCORD_CHANNEL_ID no puede ser 0".into()));
        }

        let openrouter_api_key = std::env::var("OPENROUTER_API_KEY")
            .map_err(|_| GradCafeError::Config("OPENROUTER_API_KEY no configurado".into()))?;

        let openrouter_base_url = std::env::var("OPENROUTER_BASE_URL")
            .unwrap_or_else(|_| "https://openrouter.ai/api/v1".into());

        let openrouter_sql_model = std::env::var("OPENROUTER_SQL_MODEL")
            .unwrap_or_else(|_| "openai/gpt-oss-120b".into());

        let openrouter_summary_model = std::env::var("OPENROUTER_SUMMARY_MODEL")
            .unwrap_or_else(|_| "openai/gpt-oss-120b".into());

        let openrouter_timeout_seconds: u64 = std::env::var("OPENROUTER_TIMEOUT_SECONDS")
            .unwrap_or_else(|_| "30".into())
            .parse()
            .unwrap_or(30);

        let openrouter_site_url = std::env::var("OPENROUTER_SITE_URL").ok();
        let openrouter_app_name = std::env::var("OPENROUTER_APP_NAME").ok();

        let check_interval_seconds: u64 = std::env::var("CHECK_INTERVAL_SECONDS")
            .unwrap_or_else(|_| "60".into())
            .parse()
            .unwrap_or(60);

        let enable_llm = std::env::var("ENABLE_LLM")
            .unwrap_or_else(|_| "true".into())
            .to_lowercase() != "false";

        let post_lookback_days: i64 = std::env::var("POST_LOOKBACK_DAYS")
            .unwrap_or_else(|_| "1".into())
            .parse()
            .unwrap_or(1);

        let db_path = std::env::var("DB_PATH")
            .unwrap_or_else(|_| "gradcafe_messages.db".into());

        Ok(Config {
            discord_token,
            discord_channel_id,
            openrouter_api_key,
            openrouter_base_url,
            openrouter_sql_model,
            openrouter_summary_model,
            openrouter_timeout_seconds,
            openrouter_site_url,
            openrouter_app_name,
            check_interval_seconds,
            enable_llm,
            post_lookback_days,
            db_path,
        })
    }
}
