/*
 * Tarea en segundo plano para el scraping periódico de GradCafe.
 * Ejecuta un bucle infinito que descarga, parsea y publica nuevos
 * postings de admisiones a programas de economía y finanzas
 * en el canal de Discord configurado.
 */

use crate::config::Config;
use crate::db::DbPool;
use crate::db::repository;
use crate::scraper;

use serenity::all::ChannelId;
use std::sync::Arc;
use std::time::Duration;
use tracing::{error, info, warn};

/*
 * Bucle principal de scraping que se ejecuta indefinidamente.
 * En cada iteración del intervalo configurado:
 *
 *   1. Descarga y almacena nuevos postings de GradCafe mediante
 *      spawn_blocking (porque rusqlite es síncrono).
 *   2. Si hay nuevos postings, refresca las tablas de agregación
 *      (phd y masters) para mantener los datos del LLM actualizados.
 *   3. Consulta los postings pendientes de publicación en Discord.
 *   4. Publica cada posting pendiente en el canal configurado y lo
 *      marca como publicado en la base de datos.
 *
 * Los errores se registran con tracing pero no detienen el bucle,
 * permitiendo que el bot siga funcionando ante fallos transitorios.
 */
pub async fn scraping_loop(
    pool: Arc<DbPool>,
    config: Config,
    http: Arc<serenity::http::Http>,
) {
    let interval_secs = config.check_interval_seconds;
    let channel_id = ChannelId::new(config.discord_channel_id);
    let lookback_days = config.post_lookback_days;

    info!(
        interval_seconds = interval_secs,
        channel_id = config.discord_channel_id,
        "Iniciando bucle de scraping de GradCafe"
    );

    let mut interval = tokio::time::interval(Duration::from_secs(interval_secs));

    loop {
        /* Esperar al siguiente tick del intervalo antes de ejecutar */
        interval.tick().await;

        info!("Ejecutando ciclo de scraping de GradCafe");

        /*
         * Paso 1: Descargar y almacenar nuevos postings.
         * Se clona el Arc del pool para moverlo al spawn_blocking.
         * La función fetch_and_store_new_postings es async internamente
         * pero necesita acceso al pool que no es Send, así que se ejecuta
         * en el runtime de tokio directamente.
         */
        let pool_clone = Arc::clone(&pool);
        let new_count = match scraper::fetch_and_store_new_postings(&pool_clone).await {
            Ok(count) => {
                if count > 0 {
                    info!(new_count = count, "Nuevos postings almacenados");
                }
                count
            }
            Err(e) => {
                error!(error = %e, "Error durante el scraping de GradCafe");
                0
            }
        };

        /*
         * Paso 2: Refrescar tablas de agregación si se encontraron datos nuevos.
         * Las tablas phd y masters se reconstruyen completamente para reflejar
         * los nuevos postings insertados.
         */
        if new_count > 0 {
            let pool_for_refresh = Arc::clone(&pool);
            let refresh_result = tokio::task::spawn_blocking(move || {
                repository::refresh_aggregation_tables(&pool_for_refresh)
            })
            .await;

            match refresh_result {
                Ok(Ok(())) => {
                    info!("Tablas de agregación actualizadas correctamente");
                }
                Ok(Err(e)) => {
                    error!(error = %e, "Error al refrescar tablas de agregación");
                }
                Err(e) => {
                    error!(error = %e, "Error en tarea bloqueante de agregación");
                }
            }
        }

        /*
         * Paso 3: Obtener postings pendientes de publicación en Discord.
         * Solo se consideran postings dentro del rango de días configurado
         * (post_lookback_days) para evitar publicar entradas muy antiguas.
         */
        let pool_for_unposted = Arc::clone(&pool);
        let unposted_result = tokio::task::spawn_blocking(move || {
            repository::get_unposted_postings(&pool_for_unposted, lookback_days)
        })
        .await;

        let unposted = match unposted_result {
            Ok(Ok(postings)) => postings,
            Ok(Err(e)) => {
                error!(error = %e, "Error al obtener postings no publicados");
                continue;
            }
            Err(e) => {
                error!(error = %e, "Error en tarea bloqueante de postings no publicados");
                continue;
            }
        };

        if unposted.is_empty() {
            continue;
        }

        info!(
            count = unposted.len(),
            "Postings pendientes de publicación en Discord"
        );

        /*
         * Paso 4: Publicar cada posting pendiente en el canal de Discord.
         * Después de cada publicación exitosa, se marca el posting como
         * publicado en la base de datos para evitar duplicados.
         */
        for posting in &unposted {
            let message = repository::format_posting_for_discord(posting);

            match channel_id.say(&http, &message).await {
                Ok(_) => {
                    /*
                     * Extraer el ID del posting para marcarlo como publicado.
                     * El campo 'id' puede ser un entero JSON; se intenta parsear.
                     */
                    let posting_id = posting
                        .get("id")
                        .and_then(|v| v.as_i64());

                    if let Some(id) = posting_id {
                        let pool_for_mark = Arc::clone(&pool);
                        let mark_result = tokio::task::spawn_blocking(move || {
                            repository::mark_posting_as_posted(&pool_for_mark, id)
                        })
                        .await;

                        match mark_result {
                            Ok(Ok(())) => {
                                info!(posting_id = id, "Posting marcado como publicado");
                            }
                            Ok(Err(e)) => {
                                warn!(
                                    posting_id = id,
                                    error = %e,
                                    "Error al marcar posting como publicado"
                                );
                            }
                            Err(e) => {
                                warn!(
                                    posting_id = id,
                                    error = %e,
                                    "Error en tarea bloqueante al marcar posting"
                                );
                            }
                        }
                    } else {
                        warn!("Posting sin campo 'id' válido, no se puede marcar como publicado");
                    }
                }
                Err(e) => {
                    error!(
                        error = %e,
                        "Error al publicar posting en canal de Discord"
                    );
                }
            }
        }
    }
}
