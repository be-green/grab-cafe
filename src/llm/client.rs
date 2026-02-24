/*
 * Cliente HTTP para la API de OpenRouter.
 * Envía solicitudes de completación de chat y parsea las respuestas.
 */

use crate::error::{GradCafeError, Result};
use reqwest::Client;
use serde::{Deserialize, Serialize};
use std::time::Duration;
use tracing::{debug, warn};

/*
 * Estructura principal del cliente OpenRouter.
 * Almacena la configuración de autenticación, timeouts y metadatos HTTP.
 */
#[derive(Debug, Clone)]
pub struct OpenRouterClient {
    client: Client,
    api_key: String,
    base_url: String,
    site_url: Option<String>,
    app_name: Option<String>,
}

/*
 * Payload JSON enviado a la API de OpenRouter.
 * Sigue el formato estándar de chat completions compatible con OpenAI.
 */
#[derive(Debug, Serialize)]
struct ChatRequest {
    model: String,
    messages: Vec<ChatMessage>,
    temperature: f64,
    max_tokens: u32,
    #[serde(skip_serializing_if = "Option::is_none")]
    stop: Option<Vec<String>>,
}

/*
 * Mensaje individual en la conversación.
 * El rol puede ser "system", "user" o "assistant".
 */
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ChatMessage {
    pub role: String,
    pub content: String,
}

/*
 * Respuesta parseada de la API de OpenRouter.
 * Contiene las opciones generadas por el modelo.
 */
#[derive(Debug, Deserialize)]
struct ChatResponse {
    choices: Vec<ChatChoice>,
}

/*
 * Una opción individual en la respuesta del modelo.
 * Incluye el mensaje generado y la razón de terminación.
 */
#[derive(Debug, Deserialize)]
struct ChatChoice {
    message: ChatChoiceMessage,
    finish_reason: Option<String>,
}

/*
 * El contenido del mensaje dentro de una opción de respuesta.
 */
#[derive(Debug, Deserialize)]
struct ChatChoiceMessage {
    content: Option<String>,
}

impl OpenRouterClient {
    /*
     * Crea un nuevo cliente OpenRouter con la configuración proporcionada.
     * Construye el cliente HTTP con TLS rustls y el timeout especificado.
     */
    pub fn new(
        api_key: String,
        base_url: String,
        timeout_seconds: u64,
        site_url: Option<String>,
        app_name: Option<String>,
    ) -> Result<Self> {
        let client = Client::builder()
            .timeout(Duration::from_secs(timeout_seconds))
            .build()
            .map_err(GradCafeError::Http)?;

        Ok(OpenRouterClient {
            client,
            api_key,
            base_url,
            site_url,
            app_name,
        })
    }

    /*
     * Envía una solicitud de completación de chat a la API de OpenRouter.
     * Construye los headers de autenticación, envía el payload JSON,
     * y extrae el contenido de texto de la primera opción de respuesta.
     * Emite una advertencia si la respuesta fue truncada por el límite de tokens.
     */
    pub async fn chat_completion(
        &self,
        model: &str,
        messages: Vec<ChatMessage>,
        temperature: f64,
        max_tokens: u32,
        stop: Option<Vec<String>>,
    ) -> Result<String> {
        let url = format!("{}/chat/completions", self.base_url);

        let mut headers = reqwest::header::HeaderMap::new();
        headers.insert(
            reqwest::header::AUTHORIZATION,
            format!("Bearer {}", self.api_key)
                .parse()
                .map_err(|e| GradCafeError::Llm(format!("Encabezado de autorización inválido: {}", e)))?,
        );
        headers.insert(
            reqwest::header::CONTENT_TYPE,
            "application/json"
                .parse()
                .map_err(|e| GradCafeError::Llm(format!("Encabezado content-type inválido: {}", e)))?,
        );

        if let Some(ref site_url) = self.site_url {
            headers.insert(
                "HTTP-Referer",
                site_url
                    .parse()
                    .map_err(|e| GradCafeError::Llm(format!("Encabezado HTTP-Referer inválido: {}", e)))?,
            );
        }
        if let Some(ref app_name) = self.app_name {
            headers.insert(
                "X-Title",
                app_name
                    .parse()
                    .map_err(|e| GradCafeError::Llm(format!("Encabezado X-Title inválido: {}", e)))?,
            );
        }

        let request_body = ChatRequest {
            model: model.to_string(),
            messages,
            temperature,
            max_tokens,
            stop,
        };

        debug!(
            "Enviando solicitud a OpenRouter: modelo={}, temperatura={}, max_tokens={}",
            model, temperature, max_tokens
        );

        let response = self
            .client
            .post(&url)
            .headers(headers)
            .json(&request_body)
            .send()
            .await
            .map_err(GradCafeError::Http)?;

        let status = response.status();
        if !status.is_success() {
            let body = response.text().await.unwrap_or_default();
            return Err(GradCafeError::Llm(format!(
                "La API de OpenRouter devolvió estado {}: {}",
                status, body
            )));
        }

        let data: ChatResponse = response
            .json()
            .await
            .map_err(|e| GradCafeError::Llm(format!("Error al parsear respuesta JSON: {}", e)))?;

        let choice = data
            .choices
            .into_iter()
            .next()
            .ok_or_else(|| GradCafeError::Llm("No se recibieron opciones en la respuesta".into()))?;

        /* Verificar si la respuesta fue truncada */
        if choice.finish_reason.as_deref() == Some("length") {
            warn!(
                "ADVERTENCIA: Respuesta truncada por límite de tokens (max_tokens={})",
                max_tokens
            );
        }

        choice
            .message
            .content
            .ok_or_else(|| GradCafeError::Llm("El contenido del mensaje es nulo".into()))
    }
}
