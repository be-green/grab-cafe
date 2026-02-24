/*
 * Obtención de páginas HTML desde GradCafe.
 * Usa reqwest con un timeout de 30 segundos y TLS vía rustls.
 */

use crate::error::{GradCafeError, Result};
use std::time::Duration;
use tracing::debug;

/*
 * Descarga el contenido HTML de la URL proporcionada.
 * Retorna el cuerpo como String o un error envuelto en GradCafeError.
 */
pub async fn fetch_page(url: &str) -> Result<String> {
    debug!(url = url, "Descargando página de GradCafe");

    let client = reqwest::Client::builder()
        .timeout(Duration::from_secs(30))
        .build()
        .map_err(|e| GradCafeError::Scraping(format!("No se pudo construir el cliente HTTP: {}", e)))?;

    let response = client
        .get(url)
        .send()
        .await?;

    let status = response.status();
    if !status.is_success() {
        return Err(GradCafeError::Scraping(format!(
            "Respuesta HTTP no exitosa: {} para URL {}",
            status, url
        )));
    }

    let body = response.text().await?;

    debug!(
        url = url,
        bytes = body.len(),
        "Página descargada exitosamente"
    );

    Ok(body)
}
