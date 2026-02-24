/*
 * Manejador de eventos de mensajes e interacciones de Discord.
 * Procesa menciones al bot, ejecuta consultas LLM, y gestiona
 * la navegación de vistas paginadas mediante botones de componentes.
 */

use super::pagination::PaginatedView;
use super::BotData;
use crate::llm;
use crate::llm::beatriz::RecentMessage;

use serenity::all::{
    ComponentInteraction, CreateInteractionResponse, CreateInteractionResponseMessage,
    EditMessage, Message, MessageId,
};
use serenity::prelude::Context;
use std::collections::HashMap;
use std::sync::Arc;
use tokio::sync::Mutex;
use tracing::{error, info, warn};

/*
 * Palabras clave que el usuario puede usar para solicitar
 * la última consulta SQL ejecutada por el bot.
 */
const SQL_REQUEST_KEYWORDS: &[&str] = &[
    "show sql",
    "last query",
    "what was the query",
    "show query",
    "sql query",
    "show the sql",
];

/*
 * Límite máximo de caracteres para un mensaje de Discord.
 * Los mensajes que excedan este límite se truncan con "...".
 */
const DISCORD_MESSAGE_LIMIT: usize = 2000;

/*
 * Tipo compartido para almacenar las vistas paginadas activas.
 * Se indexa por el MessageId del mensaje de la tabla para poder
 * actualizar la vista correcta cuando se recibe una interacción.
 */
pub type ActivePaginatedViews = Arc<Mutex<HashMap<MessageId, PaginatedView>>>;

/*
 * Crea un nuevo mapa de vistas paginadas vacío envuelto en Arc<Mutex<>>.
 * Se usa al inicializar BotData para compartir entre el manejador
 * de mensajes y el manejador de interacciones.
 */
pub fn new_paginated_views() -> ActivePaginatedViews {
    Arc::new(Mutex::new(HashMap::new()))
}

/*
 * Trunca un texto al límite de Discord, agregando "..." al final
 * si excede el máximo. Preserva la integridad UTF-8 truncando
 * en el límite de caracteres menos 3 para el sufijo.
 */
fn truncate_discord_message(text: &str) -> String {
    if text.len() > DISCORD_MESSAGE_LIMIT {
        let mut truncated = text.chars().take(DISCORD_MESSAGE_LIMIT - 3).collect::<String>();
        truncated.push_str("...");
        truncated
    } else {
        text.to_string()
    }
}

/*
 * Manejador principal de mensajes entrantes de Discord.
 * Procesa únicamente mensajes que mencionan al bot (sin @everyone).
 *
 * Flujo de procesamiento:
 *   1. Filtra mensajes propios y ya procesados.
 *   2. Mantiene el conjunto de mensajes procesados con un máximo de 100 entradas.
 *   3. Extrae la pregunta del usuario eliminando la mención al bot.
 *   4. Despacha según el tipo de solicitud:
 *      - Pregunta vacía: responde con saludo informativo.
 *      - Solicitud de SQL: muestra la última consulta ejecutada.
 *      - Consulta normal: ejecuta el pipeline LLM completo.
 *   5. Para resultados con más de 4 filas, envía una vista paginada
 *      con botones de navegación.
 */
pub async fn handle_message(
    ctx: &Context,
    new_message: &Message,
    data: &BotData,
) -> Result<(), anyhow::Error> {
    /* Ignorar mensajes del propio bot */
    let current_user_id = ctx.cache.current_user().id;
    if new_message.author.id == current_user_id {
        return Ok(());
    }

    /* Verificar si el mensaje ya fue procesado para evitar duplicados */
    {
        let mut processed = data.processed_messages.lock().await;
        if processed.contains(&new_message.id) {
            return Ok(());
        }
        processed.insert(new_message.id);

        /*
         * Limitar el conjunto de mensajes procesados a 100 entradas.
         * Se eliminan los más antiguos cuando se excede el límite,
         * manteniendo solo las últimas 100 entradas.
         */
        if processed.len() > 100 {
            let ids: Vec<MessageId> = processed.iter().copied().collect();
            let keep_from = ids.len().saturating_sub(100);
            *processed = ids[keep_from..].iter().copied().collect();
        }
    }

    /*
     * Solo procesar mensajes que mencionan al bot directamente.
     * Ignorar menciones @everyone que no son dirigidas al bot.
     */
    let mentions_bot = new_message.mentions.iter().any(|u| u.id == current_user_id);
    if !mentions_bot || new_message.mention_everyone {
        return Ok(());
    }

    /* Verificar que el LLM esté habilitado y cargado */
    if !data.config.enable_llm || data.llm.is_none() {
        new_message
            .channel_id
            .say(&ctx.http, "LLM queries are currently disabled.")
            .await?;
        return Ok(());
    }

    /*
     * Extraer la pregunta del usuario eliminando la mención al bot.
     * Se remueven tanto el formato <@ID> como <@!ID> (con nickname).
     */
    let bot_mention = format!("<@{}>", current_user_id);
    let bot_mention_nick = format!("<@!{}>", current_user_id);
    let user_question = new_message
        .content
        .replace(&bot_mention, "")
        .replace(&bot_mention_nick, "")
        .trim()
        .to_string();

    /* Responder con saludo si la pregunta está vacía */
    if user_question.is_empty() {
        new_message
            .channel_id
            .say(
                &ctx.http,
                "Hi! Ask me anything about economics and finance graduate admissions data.",
            )
            .await?;
        return Ok(());
    }

    /*
     * Verificar si el usuario solicita ver la última consulta SQL.
     * Busca coincidencia con cualquiera de las palabras clave definidas.
     */
    let question_lower = user_question.to_lowercase();
    if SQL_REQUEST_KEYWORDS
        .iter()
        .any(|kw| question_lower.contains(kw))
    {
        let llm_state = data.llm.as_ref().unwrap();
        let (sql_query, original_question) = llm::get_last_sql_query(llm_state);

        if let Some(sql) = sql_query {
            let orig = original_question.unwrap_or_default();
            let response = format!(
                "Last query for: \"{}\"\n\n```sql\n{}\n```",
                orig, sql
            );
            new_message
                .channel_id
                .say(&ctx.http, truncate_discord_message(&response))
                .await?;
        } else {
            new_message
                .channel_id
                .say(&ctx.http, "No SQL query has been run yet.")
                .await?;
        }
        return Ok(());
    }

    /*
     * Ejecutar el pipeline completo de LLM:
     *   1. Recuperar mensajes recientes del canal para contexto.
     *   2. Enviar la pregunta al LLM para generar SQL y obtener resultados.
     *   3. Si hay más de 4 filas, generar descripción resumida y vista paginada.
     *   4. Si hay 4 o menos filas (o error), enviar solo el texto de respuesta.
     */
    let result: Result<(), anyhow::Error> = async {
        /*
         * Obtener los últimos 6 mensajes del canal como contexto conversacional.
         * Se invierten para tener orden cronológico (más antiguo primero).
         */
        let messages = new_message
            .channel_id
            .messages(&ctx.http, serenity::all::GetMessages::new().before(new_message.id).limit(6))
            .await
            .unwrap_or_default();

        let mut recent_messages: Vec<RecentMessage> = messages
            .iter()
            .filter_map(|msg| {
                let content = msg.content.trim().to_string();
                if content.is_empty() {
                    return None;
                }
                Some(RecentMessage {
                    author: msg.author.name.clone(),
                    content,
                    is_bot: msg.author.id == current_user_id,
                })
            })
            .collect();

        /* Invertir para orden cronológico: del más antiguo al más reciente */
        recent_messages.reverse();

        let llm_state = data.llm.as_ref().unwrap();

        let (response_text, query_result) =
            llm::query_llm(llm_state, &user_question, &recent_messages).await?;

        /*
         * Determinar el modo de respuesta según los resultados:
         * - Si hay resultados válidos con más de 4 filas: vista paginada.
         * - En cualquier otro caso: solo texto.
         */
        if let Some(ref qr) = query_result {
            if !qr.has_error() && qr.has_rows() && qr.rows.len() > 4 {
                /* Generar descripción resumida para conjuntos grandes de datos */
                let description =
                    llm::beatriz::describe_query_results(
                        &llm_state.client,
                        &llm_state.summary_model,
                        &user_question,
                        qr,
                    ).await?;

                let description = truncate_discord_message(&description);
                new_message
                    .channel_id
                    .say(&ctx.http, &description)
                    .await?;

                /*
                 * Crear la vista paginada y enviar la tabla con botones.
                 * Se registra la vista en el mapa compartido para poder
                 * actualizarla cuando el usuario presione los botones.
                 */
                let view = PaginatedView::new(qr.clone(), 5);
                let table_content = view.format_table_page();
                let embed = view.get_embed();
                let action_row = view.create_action_row();

                let table_msg = new_message
                    .channel_id
                    .say(&ctx.http, &table_content)
                    .await?;

                let embed_msg = new_message
                    .channel_id
                    .send_message(
                        &ctx.http,
                        serenity::all::CreateMessage::new()
                            .embed(embed)
                            .components(vec![action_row]),
                    )
                    .await?;

                /*
                 * Almacenar la vista paginada indexada por el ID del mensaje
                 * del embed (que contiene los botones) para manejar interacciones.
                 * También se guarda el ID del mensaje de la tabla para poder editarlo.
                 */
                let mut views = data.paginated_views.lock().await;
                let paginated = PaginatedView::new(qr.clone(), 5);
                views.insert(embed_msg.id, paginated);

                /*
                 * También almacenar el ID del mensaje de la tabla
                 * en una estructura auxiliar para poder editarlo
                 * desde el manejador de interacciones.
                 */
                data.table_message_ids
                    .lock()
                    .await
                    .insert(embed_msg.id, table_msg.id);

                info!(
                    row_count = qr.rows.len(),
                    "Vista paginada enviada para consulta"
                );

                return Ok(());
            }
        }

        /* Respuesta simple de texto para resultados pequeños o sin datos */
        let response_text = truncate_discord_message(&response_text);
        new_message
            .channel_id
            .say(&ctx.http, &response_text)
            .await?;

        Ok(())
    }
    .await;

    /* Capturar y reportar errores al usuario sin propagar la excepción */
    if let Err(e) = result {
        let error_msg = format!("Sorry, I encountered an error: {}", &format!("{}", e)[..std::cmp::min(format!("{}", e).len(), 200)]);
        error!(error = %e, "Error procesando consulta LLM");
        new_message
            .channel_id
            .say(&ctx.http, &error_msg)
            .await
            .ok();
    }

    Ok(())
}

/*
 * Manejador de interacciones con componentes (botones de paginación).
 * Busca la vista paginada asociada al mensaje que generó la interacción,
 * actualiza la página según el botón presionado, y edita tanto el mensaje
 * de la tabla como el embed con los botones actualizados.
 *
 * Los custom_id de los botones son:
 *   - "prev_page": retroceder a la página anterior.
 *   - "next_page": avanzar a la siguiente página.
 */
pub async fn handle_interaction(
    ctx: &Context,
    interaction: &ComponentInteraction,
    data: &BotData,
) -> Result<(), anyhow::Error> {
    let custom_id = &interaction.data.custom_id;
    let message_id = interaction.message.id;

    /*
     * Verificar que la interacción corresponde a un botón de paginación
     * registrado en el mapa de vistas activas.
     */
    let has_view = {
        let views = data.paginated_views.lock().await;
        views.contains_key(&message_id)
    };

    if !has_view {
        /* La interacción no corresponde a una vista paginada activa */
        return Ok(());
    }

    /*
     * Actualizar la página según el botón presionado
     * y generar el nuevo contenido de la tabla y el embed.
     */
    let (table_content, embed, action_row, table_msg_id) = {
        let mut views = data.paginated_views.lock().await;
        let view = match views.get_mut(&message_id) {
            Some(v) => v,
            None => return Ok(()),
        };

        match custom_id.as_str() {
            "prev_page" => view.prev_page(),
            "next_page" => view.next_page(),
            _ => {
                warn!(custom_id = custom_id.as_str(), "ID de botón desconocido");
                return Ok(());
            }
        }

        let table_content = view.format_table_page();
        let embed = view.get_embed();
        let action_row = view.create_action_row();

        let table_msg_id = data.table_message_ids.lock().await.get(&message_id).copied();

        (table_content, embed, action_row, table_msg_id)
    };

    /*
     * Editar el mensaje de la tabla con el contenido de la nueva página.
     * Este mensaje es independiente del embed con los botones.
     */
    if let Some(table_id) = table_msg_id {
        interaction
            .channel_id
            .edit_message(
                &ctx.http,
                table_id,
                EditMessage::new().content(&table_content),
            )
            .await
            .ok();
    }

    /*
     * Responder a la interacción actualizando el embed y los botones.
     * Se usa UpdateMessage para editar el mensaje existente en lugar
     * de enviar uno nuevo, evitando la acumulación de mensajes.
     */
    interaction
        .create_response(
            &ctx.http,
            CreateInteractionResponse::UpdateMessage(
                CreateInteractionResponseMessage::new()
                    .embed(embed)
                    .components(vec![action_row]),
            ),
        )
        .await?;

    Ok(())
}
