/*
 * Módulo de scraping de GradCafe.
 * Coordina la descarga, parseo y almacenamiento de nuevos postings
 * de admisión de programas de economía y finanzas.
 */

pub mod fetcher;
pub mod parser;

use crate::db::DbPool;
use crate::error::Result;
use tracing::{info, warn};

/*
 * URLs de los programas monitoreados en GradCafe.
 * Cada URL corresponde a una búsqueda por campo académico.
 */
pub const GRADCAFE_PROGRAMS: &[&str] = &[
    "https://www.thegradcafe.com/survey/?institution=&program=economics",
    "https://www.thegradcafe.com/survey/?institution=&program=finance",
];

/*
 * Número de días hacia atrás para la verificación de duplicados recientes.
 * Un posting se considera duplicado si ya existe en la base de datos
 * dentro de este rango de tiempo.
 */
const DEFAULT_DAYS_BACK: i64 = 7;

/*
 * Descarga, parsea y almacena los postings nuevos de todas las URLs configuradas.
 * Para cada programa:
 *   1. Descarga la primera página de resultados.
 *   2. Parsea el HTML para extraer los postings.
 *   3. Verifica si cada posting ya existe en la base de datos (últimos N días).
 *   4. Inserta los postings nuevos.
 *
 * Las operaciones de base de datos se ejecutan con spawn_blocking porque rusqlite
 * es síncrono y no debe ejecutarse directamente en el runtime de tokio.
 *
 * Retorna el número total de postings nuevos insertados.
 */
pub async fn fetch_and_store_new_postings(pool: &DbPool) -> Result<i32> {
    let mut new_count: i32 = 0;

    for base_url in GRADCAFE_PROGRAMS {
        let html = match fetcher::fetch_page(base_url).await {
            Ok(html) => html,
            Err(e) => {
                warn!(
                    url = base_url,
                    error = %e,
                    "Error al descargar página de GradCafe, continuando con la siguiente URL"
                );
                continue;
            }
        };

        let postings = parser::parse_page(&html);
        info!(
            url = base_url,
            count = postings.len(),
            "Postings parseados de GradCafe"
        );

        for posting in postings {
            let gradcafe_id = posting.gradcafe_id.clone();

            /*
             * Verificar existencia reciente en la base de datos.
             * Se usa spawn_blocking para no bloquear el runtime async de tokio
             * con la operación síncrona de rusqlite.
             */
            let pool_ptr = pool as *const DbPool;
            let pool_addr = pool_ptr as usize;
            let gid = gradcafe_id.clone();

            let exists = tokio::task::spawn_blocking(move || {
                /*
                 * SEGURIDAD: El puntero es válido porque el pool vive más que esta tarea.
                 * La función fetch_and_store_new_postings toma &DbPool, y la tarea
                 * bloqueante termina antes de que esta función retorne.
                 */
                let pool_ref = unsafe { &*(pool_addr as *const DbPool) };
                crate::db::repository::posting_exists_recent(pool_ref, &gid, DEFAULT_DAYS_BACK)
            })
            .await
            .map_err(|e| {
                crate::error::GradCafeError::Scraping(format!(
                    "Error en tarea bloqueante (exists): {}",
                    e
                ))
            })??;

            if exists {
                continue;
            }

            /*
             * Insertar el posting nuevo en la base de datos.
             * Igual que arriba, se usa spawn_blocking para la operación síncrona.
             */
            let posting_clone = posting.clone();
            let pool_ptr = pool as *const DbPool;
            let pool_addr = pool_ptr as usize;

            let inserted = tokio::task::spawn_blocking(move || {
                let pool_ref = unsafe { &*(pool_addr as *const DbPool) };
                crate::db::repository::add_posting(pool_ref, &posting_clone)
            })
            .await
            .map_err(|e| {
                crate::error::GradCafeError::Scraping(format!(
                    "Error en tarea bloqueante (insert): {}",
                    e
                ))
            })??;

            if inserted {
                new_count += 1;
                info!(
                    school = posting.school,
                    program = posting.program,
                    decision = posting.decision,
                    "Nuevo posting almacenado"
                );
            }
        }
    }

    info!(new_count = new_count, "Scraping completado");
    Ok(new_count)
}
