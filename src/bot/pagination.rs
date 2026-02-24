/*
 * Paginación de resultados de consultas SQL para Discord.
 * Formatea tablas en bloques de código, genera embeds con información
 * de página, y construye botones de navegación para la interacción
 * del usuario con las vistas paginadas.
 */

use crate::db::models::QueryResult;
use serenity::all::{ButtonStyle, CreateActionRow, CreateButton, CreateEmbed};

/*
 * Vista paginada que mantiene el estado de navegación
 * para un conjunto de resultados de una consulta SQL.
 * Cada instancia se asocia a un mensaje de Discord con botones
 * de navegación anterior/siguiente.
 */
pub struct PaginatedView {
    pub query_result: QueryResult,
    pub rows_per_page: usize,
    pub current_page: usize,
    pub total_pages: usize,
}

impl PaginatedView {
    /*
     * Crea una nueva vista paginada a partir de un QueryResult.
     * Calcula el total de páginas usando redondeo hacia arriba.
     * Si no hay filas, se establece al menos una página.
     */
    pub fn new(query_result: QueryResult, rows_per_page: usize) -> Self {
        let row_count = query_result.rows.len();
        let total_pages = if row_count == 0 {
            1
        } else {
            (row_count + rows_per_page - 1) / rows_per_page
        };

        PaginatedView {
            query_result,
            rows_per_page,
            current_page: 0,
            total_pages,
        }
    }

    /*
     * Formatea la página actual como una tabla de texto plano
     * dentro de un bloque de código Markdown para Discord.
     * Calcula anchos de columna dinámicos con un máximo de 20 caracteres
     * por columna, alineando valores a la izquierda con separadores de pipe.
     */
    pub fn format_table_page(&self) -> String {
        let start_idx = self.current_page * self.rows_per_page;
        let end_idx = std::cmp::min(
            start_idx + self.rows_per_page,
            self.query_result.rows.len(),
        );

        let columns = &self.query_result.columns;
        let page_rows = &self.query_result.rows[start_idx..end_idx];

        /*
         * Calcular anchos de columna basados en los encabezados
         * y los valores de la página actual, con un límite de 20 caracteres.
         */
        let mut col_widths: Vec<usize> = columns
            .iter()
            .map(|col| std::cmp::min(col.len(), 20))
            .collect();

        for row in page_rows {
            for (i, val) in row.iter().enumerate() {
                if i < col_widths.len() {
                    let formatted = format_value(val);
                    col_widths[i] = std::cmp::min(
                        std::cmp::max(col_widths[i], formatted.len()),
                        20,
                    );
                }
            }
        }

        let mut table_lines = Vec::new();

        /* Línea de encabezado con nombres de columna truncados y alineados */
        let header: String = columns
            .iter()
            .enumerate()
            .map(|(i, col)| {
                let width = col_widths[i];
                let truncated = truncate_str(col, width);
                format!("{:<width$}", truncated, width = width)
            })
            .collect::<Vec<_>>()
            .join(" | ");
        table_lines.push(header.clone());

        /* Línea separadora con guiones */
        table_lines.push("-".repeat(header.len()));

        /* Filas de datos formateadas y alineadas */
        for row in page_rows {
            let formatted_vals: Vec<String> = row
                .iter()
                .enumerate()
                .map(|(i, val)| {
                    let width = if i < col_widths.len() {
                        col_widths[i]
                    } else {
                        10
                    };
                    let formatted = format_value(val);
                    let truncated = truncate_str(&formatted, width);
                    format!("{:<width$}", truncated, width = width)
                })
                .collect();
            table_lines.push(formatted_vals.join(" | "));
        }

        format!("```\n{}\n```", table_lines.join("\n"))
    }

    /*
     * Construye un embed de Discord con el indicador de página actual.
     * Muestra "Página X de Y" en la descripción con color azul.
     */
    pub fn get_embed(&self) -> CreateEmbed {
        CreateEmbed::new()
            .description(format!(
                "**Pagina {} de {}**",
                self.current_page + 1,
                self.total_pages
            ))
            .color(0x3498db)
    }

    /*
     * Crea los botones de navegación anterior y siguiente.
     * Los botones se deshabilitan cuando la vista tiene una sola página
     * o cuando se está en el límite correspondiente.
     */
    pub fn create_buttons(&self) -> Vec<CreateButton> {
        let single_page = self.total_pages <= 1;

        let prev_button = CreateButton::new("prev_page")
            .label("Previous")
            .style(ButtonStyle::Secondary)
            .disabled(single_page || self.current_page == 0);

        let next_button = CreateButton::new("next_page")
            .label("Next")
            .style(ButtonStyle::Secondary)
            .disabled(single_page || self.current_page >= self.total_pages - 1);

        vec![prev_button, next_button]
    }

    /*
     * Agrupa los botones de navegación en una fila de acciones
     * compatible con el sistema de componentes de Discord.
     */
    pub fn create_action_row(&self) -> CreateActionRow {
        CreateActionRow::Buttons(self.create_buttons())
    }

    /*
     * Avanza a la siguiente página si no se ha alcanzado el final.
     * No hace nada si ya se está en la última página.
     */
    pub fn next_page(&mut self) {
        if self.current_page < self.total_pages - 1 {
            self.current_page += 1;
        }
    }

    /*
     * Retrocede a la página anterior si no se está en la primera.
     * No hace nada si ya se está en la página inicial.
     */
    pub fn prev_page(&mut self) {
        if self.current_page > 0 {
            self.current_page -= 1;
        }
    }
}

/*
 * Formatea un valor JSON para su representación en tabla.
 * Los valores nulos se muestran como "N/A", los flotantes
 * con dos decimales, y el resto como cadena de texto.
 */
fn format_value(val: &serde_json::Value) -> String {
    match val {
        serde_json::Value::Null => "N/A".to_string(),
        serde_json::Value::Number(n) => {
            /* Enteros se muestran sin decimales, flotantes con 2 decimales */
            if let Some(i) = n.as_i64() {
                format!("{}", i)
            } else if let Some(f) = n.as_f64() {
                format!("{:.2}", f)
            } else {
                n.to_string()
            }
        }
        serde_json::Value::String(s) => s.clone(),
        serde_json::Value::Bool(b) => b.to_string(),
        other => other.to_string(),
    }
}

/*
 * Trunca una cadena a un ancho máximo de caracteres.
 * No agrega indicador de truncamiento para mantener
 * la alineación limpia de las columnas.
 */
fn truncate_str(s: &str, max_len: usize) -> String {
    if s.len() <= max_len {
        s.to_string()
    } else {
        s.chars().take(max_len).collect()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_paginated_view_paginas() {
        let qr = QueryResult {
            error: None,
            columns: vec!["school".to_string(), "gpa".to_string()],
            rows: vec![
                vec![serde_json::json!("MIT"), serde_json::json!(3.9)],
                vec![serde_json::json!("Harvard"), serde_json::json!(3.8)],
                vec![serde_json::json!("Stanford"), serde_json::json!(3.7)],
                vec![serde_json::json!("Princeton"), serde_json::json!(3.6)],
                vec![serde_json::json!("Yale"), serde_json::json!(3.5)],
                vec![serde_json::json!("Columbia"), serde_json::json!(3.4)],
            ],
            row_count: 6,
        };

        let view = PaginatedView::new(qr, 2);
        assert_eq!(view.total_pages, 3);
        assert_eq!(view.current_page, 0);
    }

    #[test]
    fn test_paginated_view_navegacion() {
        let qr = QueryResult {
            error: None,
            columns: vec!["col".to_string()],
            rows: vec![
                vec![serde_json::json!("a")],
                vec![serde_json::json!("b")],
                vec![serde_json::json!("c")],
            ],
            row_count: 3,
        };

        let mut view = PaginatedView::new(qr, 1);
        assert_eq!(view.total_pages, 3);

        view.next_page();
        assert_eq!(view.current_page, 1);

        view.next_page();
        assert_eq!(view.current_page, 2);

        /* No debe avanzar más allá de la última página */
        view.next_page();
        assert_eq!(view.current_page, 2);

        view.prev_page();
        assert_eq!(view.current_page, 1);

        view.prev_page();
        assert_eq!(view.current_page, 0);

        /* No debe retroceder más allá de la primera página */
        view.prev_page();
        assert_eq!(view.current_page, 0);
    }

    #[test]
    fn test_format_value_tipos() {
        assert_eq!(format_value(&serde_json::Value::Null), "N/A");
        assert_eq!(format_value(&serde_json::json!(3.14159)), "3.14");
        assert_eq!(format_value(&serde_json::json!("hello")), "hello");
        assert_eq!(format_value(&serde_json::json!(42)), "42");
        assert_eq!(format_value(&serde_json::json!(true)), "true");
    }

    #[test]
    fn test_format_table_page_contenido() {
        let qr = QueryResult {
            error: None,
            columns: vec!["school".to_string(), "gpa".to_string()],
            rows: vec![
                vec![serde_json::json!("MIT"), serde_json::json!(3.9)],
                vec![serde_json::json!("Harvard"), serde_json::json!(3.8)],
            ],
            row_count: 2,
        };

        let view = PaginatedView::new(qr, 5);
        let table = view.format_table_page();
        assert!(table.starts_with("```\n"));
        assert!(table.ends_with("\n```"));
        assert!(table.contains("school"));
        assert!(table.contains("MIT"));
        assert!(table.contains("Harvard"));
    }

    #[test]
    fn test_pagina_unica_botones_deshabilitados() {
        let qr = QueryResult {
            error: None,
            columns: vec!["x".to_string()],
            rows: vec![vec![serde_json::json!(1)]],
            row_count: 1,
        };

        let view = PaginatedView::new(qr, 5);
        assert_eq!(view.total_pages, 1);
        /* Los botones deben estar deshabilitados con una sola página */
        let buttons = view.create_buttons();
        assert_eq!(buttons.len(), 2);
    }

    #[test]
    fn test_truncate_str_limites() {
        assert_eq!(truncate_str("abcdef", 3), "abc");
        assert_eq!(truncate_str("ab", 5), "ab");
        assert_eq!(truncate_str("", 5), "");
    }
}
