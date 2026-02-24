/*
 * Módulo de base de datos.
 * DbPool envuelve una conexión SQLite con Mutex para uso seguro entre hilos.
 */

pub mod models;
pub mod repository;

use rusqlite::Connection;
use std::sync::Mutex;

pub struct DbPool {
    conn: Mutex<Connection>,
}

impl DbPool {
    /// Crea un nuevo pool abriendo la conexión y activando WAL mode
    pub fn new(db_path: &str) -> crate::error::Result<Self> {
        let conn = Connection::open(db_path)?;
        conn.execute_batch("PRAGMA journal_mode=WAL;")?;
        Ok(DbPool {
            conn: Mutex::new(conn),
        })
    }

    /// Obtiene acceso a la conexión protegida por Mutex
    pub fn get(&self) -> std::sync::MutexGuard<'_, Connection> {
        self.conn.lock().expect("El mutex de la base de datos fue envenenado")
    }
}
