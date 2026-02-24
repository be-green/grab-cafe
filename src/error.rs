/*
 * Errores de dominio para GradCafe Bot.
 * Cada variante envuelve un tipo de error específico del sistema.
 */

use thiserror::Error;

#[derive(Error, Debug)]
pub enum GradCafeError {
    #[error("Error de base de datos: {0}")]
    Database(#[from] rusqlite::Error),

    #[error("Error de scraping: {0}")]
    Scraping(String),

    #[error("Error HTTP: {0}")]
    Http(#[from] reqwest::Error),

    #[error("Error de LLM: {0}")]
    Llm(String),

    #[error("Error de configuración: {0}")]
    Config(String),

    #[error("Consulta SQL insegura: {0}")]
    SqlSafety(String),

    #[error("Error de Discord: {0}")]
    Discord(#[from] serenity::Error),
}

pub type Result<T> = std::result::Result<T, GradCafeError>;
