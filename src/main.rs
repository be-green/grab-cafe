/*
 * Punto de entrada del bot de GradCafe.
 * Carga configuración, inicializa la base de datos, y arranca el bot de Discord.
 */

mod config;
mod error;
mod db;
mod scraper;
mod llm;
mod bot;

use std::sync::Arc;
use tracing::{info, error};

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    /* Cargar variables de entorno desde .env si existe */
    dotenvy::dotenv().ok();

    /* Configurar tracing/logging */
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| tracing_subscriber::EnvFilter::new("info")),
        )
        .init();

    /* Cargar configuración desde variables de entorno */
    let config = config::Config::from_env().map_err(|e| {
        error!("Error de configuración: {}", e);
        e
    })?;

    info!("Configuración cargada correctamente");

    /* Inicializar la base de datos */
    let pool = Arc::new(db::DbPool::new(&config.db_path)?);
    db::repository::init_database(&pool)?;
    info!("Base de datos inicializada: {}", config.db_path);

    /* Refrescar tablas de agregación al inicio */
    db::repository::refresh_aggregation_tables(&pool)?;
    info!("Tablas de agregación actualizadas");

    /* Arrancar el bot de Discord */
    info!("Iniciando bot de Discord...");
    bot::run_bot(config, pool).await?;

    Ok(())
}
