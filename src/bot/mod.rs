/*
 * Módulo principal del bot de Discord para GradCafe.
 * Define la estructura de datos compartida, configura el framework poise
 * con manejo de eventos, y arranca tanto el bot como la tarea de scraping
 * en segundo plano.
 */

pub mod handler;
pub mod pagination;
pub mod tasks;

use crate::config::Config;
use crate::db::DbPool;
use crate::llm::LlmState;

use handler::ActivePaginatedViews;
use std::collections::{HashMap, HashSet};
use std::sync::Arc;
use tokio::sync::Mutex;
use tracing::{error, info};

use serenity::all::MessageId;

/*
 * Datos compartidos del bot, accesibles desde todos los manejadores de eventos
 * y comandos de poise. Contiene el pool de base de datos, el estado del LLM,
 * la configuración, y las estructuras de control de paginación.
 *
 * Todos los campos mutables están protegidos por Mutex de tokio para
 * acceso seguro desde múltiples tareas asíncronas concurrentes.
 */
pub struct BotData {
    pub pool: Arc<DbPool>,
    pub llm: Option<Arc<LlmState>>,
    pub config: Config,
    pub processed_messages: Arc<Mutex<HashSet<MessageId>>>,
    pub paginated_views: ActivePaginatedViews,
    /*
     * Mapeo entre el MessageId del embed (con botones) y el MessageId
     * del mensaje de la tabla, necesario para editar la tabla cuando
     * el usuario navega entre páginas.
     */
    pub table_message_ids: Arc<Mutex<HashMap<MessageId, MessageId>>>,
}

/*
 * Alias de tipo para el contexto de poise parametrizado con BotData.
 * Facilita la escritura de firmas de comandos slash y de prefijo.
 */
pub type PoiseContext<'a> = poise::Context<'a, BotData, anyhow::Error>;

/*
 * Punto de entrada principal del bot de Discord.
 * Configura el framework poise con:
 *   - Manejo de eventos para mensajes (Message) e interacciones (ComponentInteraction).
 *   - Inicialización del estado compartido del bot (BotData).
 *   - Lanzamiento de la tarea de scraping en segundo plano al estar listo.
 *
 * El framework intercepta los eventos crudos de serenity y los despacha
 * al manejador correspondiente en handler.rs. La tarea de scraping se
 * ejecuta como una tarea tokio independiente que vive durante toda la
 * sesión del bot.
 */
pub async fn run_bot(config: Config, pool: Arc<DbPool>) -> anyhow::Result<()> {
    let token = config.discord_token.clone();

    /*
     * Inicializar el estado del LLM si está habilitado en la configuración.
     * Si falla la inicialización, se continúa sin LLM y se registra el error.
     */
    let llm_state = if config.enable_llm {
        match crate::llm::create_llm(&config, Arc::clone(&pool)) {
            Ok(state) => {
                info!("Estado del LLM inicializado correctamente");
                Some(Arc::new(state))
            }
            Err(e) => {
                error!(error = %e, "Error al inicializar el LLM, continuando sin él");
                None
            }
        }
    } else {
        info!("LLM deshabilitado por configuración");
        None
    };

    /*
     * Configurar los intents de Discord necesarios.
     * GUILD_MESSAGES y MESSAGE_CONTENT son requeridos para leer mensajes,
     * GUILDS para el manejo de canales e interacciones.
     */
    let intents = serenity::all::GatewayIntents::GUILD_MESSAGES
        | serenity::all::GatewayIntents::MESSAGE_CONTENT
        | serenity::all::GatewayIntents::GUILDS;

    /*
     * Clonar valores necesarios para el closure de setup que se ejecuta
     * una sola vez cuando el bot se conecta exitosamente a Discord.
     */
    let config_for_data = config.clone();
    let pool_for_data = Arc::clone(&pool);
    let llm_for_data = llm_state.clone();
    let config_for_task = config.clone();
    let pool_for_task = Arc::clone(&pool);

    /*
     * Construir el framework de poise con las opciones del bot.
     * No se registran comandos slash por ahora; toda la interacción
     * se maneja a través de menciones en mensajes regulares.
     */
    let framework = poise::Framework::builder()
        .options(poise::FrameworkOptions {
            /*
             * Manejador de eventos crudos de serenity.
             * Intercepta FullEvent::Message para procesar menciones al bot
             * y FullEvent::InteractionCreate para manejar botones de paginación.
             */
            event_handler: |ctx, event, _framework_ctx: poise::FrameworkContext<'_, BotData, anyhow::Error>, data| {
                Box::pin(async move {
                    match event {
                        /*
                         * Evento de mensaje nuevo: se despacha al manejador
                         * que verifica menciones y ejecuta consultas LLM.
                         */
                        poise::serenity_prelude::FullEvent::Message { new_message } => {
                            if let Err(e) =
                                handler::handle_message(ctx, new_message, data).await
                            {
                                error!(
                                    error = %e,
                                    "Error en el manejador de mensajes"
                                );
                            }
                        }
                        /*
                         * Evento de interacción: se filtra por ComponentInteraction
                         * (botones) y se despacha al manejador de paginación.
                         */
                        poise::serenity_prelude::FullEvent::InteractionCreate {
                            interaction,
                        } => {
                            if let Some(component) = interaction.as_message_component() {
                                if let Err(e) =
                                    handler::handle_interaction(ctx, component, data).await
                                {
                                    error!(
                                        error = %e,
                                        "Error en el manejador de interacciones"
                                    );
                                }
                            }
                        }
                        _ => {}
                    }
                    Ok(())
                })
            },
            ..Default::default()
        })
        .setup(move |ctx, ready, _framework| {
            Box::pin(async move {
                info!(
                    user = %ready.user.name,
                    "Bot conectado a Discord exitosamente"
                );

                /*
                 * Lanzar la tarea de scraping en segundo plano.
                 * Se ejecuta como una tarea tokio independiente que vive
                 * durante toda la sesión del bot, ejecutando el bucle
                 * de scraping con el intervalo configurado.
                 */
                let http = Arc::clone(&ctx.http);
                tokio::spawn(async move {
                    tasks::scraping_loop(pool_for_task, config_for_task, http).await;
                });

                info!("Tarea de scraping en segundo plano iniciada");

                /*
                 * Construir y retornar el estado compartido del bot.
                 * Este dato estará disponible en todos los manejadores
                 * de eventos y comandos a través del parámetro data.
                 */
                Ok(BotData {
                    pool: pool_for_data,
                    llm: llm_for_data,
                    config: config_for_data,
                    processed_messages: Arc::new(Mutex::new(HashSet::new())),
                    paginated_views: handler::new_paginated_views(),
                    table_message_ids: Arc::new(Mutex::new(HashMap::new())),
                })
            })
        })
        .build();

    /*
     * Construir el cliente de serenity con el token, los intents y el framework.
     * El método start() conecta al gateway de Discord y bloquea hasta que
     * el bot se desconecte o ocurra un error fatal.
     */
    let mut client = serenity::all::Client::builder(&token, intents)
        .framework(framework)
        .await
        .map_err(|e| anyhow::anyhow!("Error al construir el cliente de Discord: {}", e))?;

    info!("Iniciando cliente de Discord...");

    client
        .start()
        .await
        .map_err(|e| anyhow::anyhow!("Error al iniciar el cliente de Discord: {}", e))?;

    Ok(())
}
