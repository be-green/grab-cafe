/*
 * Parser del HTML de GradCafe.
 * Extrae postings de la tabla de resultados, procesando filas de datos,
 * filas de detalles (badges con GPA, GRE, temporada, estatus) y filas de comentarios.
 * Usa la máquina de estados multi-fila del scraper original en Python.
 */

use crate::db::models::Posting;
use chrono::NaiveDate;
use once_cell::sync::Lazy;
use regex::Regex;
use scraper::{Html, Selector};
use tracing::{debug, warn};

/*
 * Patrón para extraer el tipo de grado al final del campo program.
 * Coincide con PhD, Masters, MBA, MPhil, MRes, MSc, MFA, MS, MA, JD, etc.
 */
const DEGREE_PATTERN: &str =
    r"(PhD|Doctorate|Masters|Master|MBA|MPhil|MRes|MSc|MFA|MS|MA|JD|Other)$";

/*
 * Expresiones regulares compiladas una sola vez con Lazy.
 * Evita recompilar en cada llamada al parser.
 */
static RE_DEGREE: Lazy<Regex> = Lazy::new(|| Regex::new(DEGREE_PATTERN).unwrap());

static RE_RESULT_ID: Lazy<Regex> = Lazy::new(|| Regex::new(r"/result/(\d+)").unwrap());

static RE_SEASON: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"(Fall|Spring|Summer|Winter)\s+\d{4}").unwrap());

static RE_GPA: Lazy<Regex> = Lazy::new(|| Regex::new(r"GPA\s+([\d.]+)").unwrap());

static RE_GRE_LABELED: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"GRE\s+(V|AW|Q)\s+([\d.]+)").unwrap());

static RE_GRE_UNLABELED: Lazy<Regex> = Lazy::new(|| Regex::new(r"GRE\s+(\d+)").unwrap());

static RE_GRE_PAREN: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"([\d.]+)\s*\((Q|V|AW)\)").unwrap());

/*
 * Valida un valor de GPA.
 * Acepta valores entre 0.0 y 10.0 inclusive.
 * Retorna None si el string está vacío, no es numérico, o fuera de rango.
 */
fn validate_gpa(gpa_str: &str) -> Option<f64> {
    if gpa_str.is_empty() {
        return None;
    }
    let gpa: f64 = gpa_str.parse().ok()?;
    if (0.0..=10.0).contains(&gpa) {
        Some(gpa)
    } else {
        None
    }
}

/*
 * Valida un puntaje de sección del GRE.
 * Para secciones Q (quantitative) y V (verbal): rango 130-170.
 * Para sección AW (analytical writing): rango 0.0-6.0.
 */
fn validate_gre_section(score_str: &str, section: &str) -> Option<f64> {
    if score_str.is_empty() {
        return None;
    }
    let score: f64 = score_str.parse().ok()?;
    match section {
        "Q" | "V" if (130.0..=170.0).contains(&score) => Some(score),
        "AW" if (0.0..=6.0).contains(&score) => Some(score),
        _ => None,
    }
}

/*
 * Normaliza una fecha a formato ISO 8601 (YYYY-MM-DD).
 * Intenta múltiples formatos comunes de GradCafe:
 *   - "Jan 15, 2024" (abreviado)
 *   - "January 15, 2024" (completo)
 *   - "01/15/2024" (estadounidense)
 *   - "2024-01-15" (ISO)
 */
fn normalize_date(date_str: &str) -> Option<String> {
    let trimmed = date_str.trim();
    if trimmed.is_empty() {
        return None;
    }

    let formats = ["%b %d, %Y", "%B %d, %Y", "%m/%d/%Y", "%Y-%m-%d"];

    for fmt in &formats {
        if let Ok(parsed) = NaiveDate::parse_from_str(trimmed, fmt) {
            return Some(parsed.format("%Y-%m-%d").to_string());
        }
    }

    None
}

/*
 * Parsea el HTML completo de una página de resultados de GradCafe.
 * Implementa la máquina de estados multi-fila:
 *   1. Fila principal (5 celdas): school, program, date, decision, link
 *   2. Fila de detalles (opcional, clase tw-border-none): badges con season, status, GPA, GRE
 *   3. Fila de comentario (opcional, clase tw-border-none): párrafo con comentario del usuario
 *
 * Retorna un vector de Posting con todos los campos extraídos.
 */
pub fn parse_page(html: &str) -> Vec<Posting> {
    let document = Html::parse_document(html);

    let tr_selector = Selector::parse("tr").expect("Selector 'tr' inválido");
    let td_selector = Selector::parse("td").expect("Selector 'td' inválido");
    let a_selector = Selector::parse("a").expect("Selector 'a' inválido");
    let badge_selector =
        Selector::parse("div.tw-inline-flex").expect("Selector 'div.tw-inline-flex' inválido");
    let p_selector = Selector::parse("p").expect("Selector 'p' inválido");

    let rows: Vec<_> = document.select(&tr_selector).collect();

    if rows.is_empty() {
        warn!("No se encontraron filas en la tabla");
        return Vec::new();
    }

    let mut postings = Vec::new();
    let mut i = 1; // Saltar la fila de encabezado

    while i < rows.len() {
        let row = rows[i];
        let cells: Vec<_> = row.select(&td_selector).collect();

        /*
         * La fila principal de datos tiene exactamente 5 celdas:
         * school, program, date_added, decision, link (con gradcafe_id)
         */
        if cells.len() != 5 {
            i += 1;
            continue;
        }

        let school = cells[0].text().collect::<String>().trim().to_string();
        let program_raw = cells[1].text().collect::<String>().trim().to_string();
        let date_added = cells[2].text().collect::<String>().trim().to_string();
        let date_added_iso = normalize_date(&date_added);
        let decision = cells[3].text().collect::<String>().trim().to_string();

        /* Extraer el gradcafe_id del enlace en la quinta celda */
        let gradcafe_id = cells[4]
            .select(&a_selector)
            .next()
            .and_then(|a| a.value().attr("href"))
            .and_then(|href| RE_RESULT_ID.captures(href))
            .map(|caps| caps[1].to_string())
            .unwrap_or_default();

        /* Saltar filas sin escuela o sin ID válido */
        if school.is_empty() || gradcafe_id.is_empty() {
            i += 1;
            continue;
        }

        /*
         * Separar el programa del grado.
         * El grado aparece al final del texto del programa (ej. "Economics PhD").
         */
        let (program, degree) = if let Some(m) = RE_DEGREE.find(&program_raw) {
            let deg = m.as_str().to_string();
            let prog = program_raw[..m.start()].trim().to_string();
            let prog = if prog.is_empty() {
                program_raw.clone()
            } else {
                prog
            };
            (prog, Some(deg))
        } else {
            (program_raw.clone(), None)
        };

        /* Variables para los campos extraídos de la fila de detalles */
        let mut season: Option<String> = None;
        let mut status: Option<String> = None;
        let mut gpa: Option<f64> = None;
        let mut gre_quant: Option<f64> = None;
        let mut gre_verbal: Option<f64> = None;
        let mut gre_aw: Option<f64> = None;
        let mut gre_combined: Option<f64> = None;
        let mut comment: Option<String> = None;

        let mut details_row_consumed = false;

        /*
         * Verificar si la siguiente fila es una fila de detalles.
         * Las filas de detalles tienen la clase CSS "tw-border-none"
         * y contienen badges (div.tw-inline-flex) con información adicional.
         */
        if i + 1 < rows.len() {
            let details_row = rows[i + 1];
            let classes = details_row.value().attr("class").unwrap_or("");

            if classes.contains("tw-border-none") {
                details_row_consumed = true;

                for badge in details_row.select(&badge_selector) {
                    let badge_text = badge.text().collect::<String>().trim().to_string();

                    /* Intentar extraer la temporada (ej. "Fall 2024") */
                    if season.is_none() {
                        if let Some(caps) = RE_SEASON.captures(&badge_text) {
                            season = Some(caps[0].to_string());
                            continue;
                        }
                    }

                    /* Intentar extraer el estatus (International, American, Other) */
                    if status.is_none() {
                        if badge_text == "International"
                            || badge_text == "American"
                            || badge_text == "Other"
                        {
                            status = Some(badge_text);
                            continue;
                        }
                    }

                    /* Intentar extraer el GPA (ej. "GPA 3.85") */
                    if gpa.is_none() {
                        if let Some(caps) = RE_GPA.captures(&badge_text) {
                            gpa = validate_gpa(&caps[1]);
                            if gpa.is_some() {
                                continue;
                            }
                        }
                    }

                    /*
                     * Intentar extraer puntajes GRE con etiqueta (ej. "GRE Q 168", "GRE V 165", "GRE AW 5.0").
                     * Formato: "GRE <componente> <puntaje>"
                     */
                    if badge_text.starts_with("GRE") {
                        if let Some(caps) = RE_GRE_LABELED.captures(&badge_text) {
                            let component = &caps[1];
                            let score = &caps[2];
                            match component {
                                "Q" if gre_quant.is_none() => {
                                    gre_quant = validate_gre_section(score, "Q");
                                }
                                "V" if gre_verbal.is_none() => {
                                    gre_verbal = validate_gre_section(score, "V");
                                }
                                "AW" if gre_aw.is_none() => {
                                    gre_aw = validate_gre_section(score, "AW");
                                }
                                _ => {}
                            }
                            continue;
                        }

                        /*
                         * GRE sin etiqueta de componente (ej. "GRE 165" o "GRE 330").
                         * Si el puntaje está entre 130-170, se asume que es Quant.
                         * Si está entre 260-340, se asume que es el combinado.
                         */
                        if gre_quant.is_none() && gre_combined.is_none() {
                            if let Some(caps) = RE_GRE_UNLABELED.captures(&badge_text) {
                                if let Ok(score) = caps[1].parse::<i32>() {
                                    if (130..=170).contains(&score) {
                                        gre_quant = Some(score as f64);
                                    } else if (260..=340).contains(&score) {
                                        gre_combined = Some(score as f64);
                                    }
                                }
                                continue;
                            }
                        }
                    }

                    /*
                     * Formato alternativo con paréntesis: "165 (Q)", "160 (V)", "4.5 (AW)".
                     * Algunos postings usan este formato en vez del etiquetado.
                     */
                    if badge_text.contains("(Q)")
                        || badge_text.contains("(V)")
                        || badge_text.contains("(AW)")
                    {
                        if let Some(caps) = RE_GRE_PAREN.captures(&badge_text) {
                            let score = &caps[1];
                            let component = &caps[2];
                            match component {
                                "Q" if gre_quant.is_none() => {
                                    gre_quant = validate_gre_section(score, "Q");
                                }
                                "V" if gre_verbal.is_none() => {
                                    gre_verbal = validate_gre_section(score, "V");
                                }
                                "AW" if gre_aw.is_none() => {
                                    gre_aw = validate_gre_section(score, "AW");
                                }
                                _ => {}
                            }
                            continue;
                        }
                    }
                }
            }
        }

        /*
         * Calcular el puntaje combinado del GRE si tenemos Q y V pero no el combinado.
         * Solo se calcula si la suma está en el rango válido 260-340.
         */
        if gre_quant.is_some() && gre_verbal.is_some() && gre_combined.is_none() {
            let q = gre_quant.unwrap() as i32;
            let v = gre_verbal.unwrap() as i32;
            let combined = q + v;
            if (260..=340).contains(&combined) {
                gre_combined = Some(combined as f64);
            }
        }

        /*
         * Verificar si hay una fila de comentario después de la fila de detalles.
         * Solo se busca si la fila de detalles fue consumida.
         * La fila de comentario también tiene clase "tw-border-none" y contiene un <p>.
         */
        let mut comment_row_consumed = false;
        if details_row_consumed {
            if i + 2 < rows.len() {
                let comment_row = rows[i + 2];
                let classes = comment_row.value().attr("class").unwrap_or("");

                if classes.contains("tw-border-none") {
                    comment_row_consumed = true;
                    if let Some(p_elem) = comment_row.select(&p_selector).next() {
                        let text = p_elem.text().collect::<String>().trim().to_string();
                        if !text.is_empty() {
                            comment = Some(text);
                        }
                    }
                }
            }
        }

        let posting = Posting {
            id: None,
            gradcafe_id,
            school,
            program,
            degree,
            decision,
            date_added,
            date_added_iso,
            season,
            status,
            gpa,
            gre_quant,
            gre_verbal,
            gre_aw,
            gre_combined,
            comment,
            scraped_at: None,
            posted_to_discord: None,
        };

        postings.push(posting);

        /*
         * Avanzar el índice según cuántas filas fueron consumidas:
         * 1 (datos) + 0 o 1 (detalles) + 0 o 1 (comentario)
         */
        let mut rows_consumed = 1;
        if details_row_consumed {
            rows_consumed += 1;
        }
        if comment_row_consumed {
            rows_consumed += 1;
        }
        i += rows_consumed;
    }

    debug!(count = postings.len(), "Postings parseados de la página");

    postings
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_validate_gpa_valido() {
        assert_eq!(validate_gpa("3.85"), Some(3.85));
        assert_eq!(validate_gpa("0.0"), Some(0.0));
        assert_eq!(validate_gpa("10.0"), Some(10.0));
        assert_eq!(validate_gpa("4.0"), Some(4.0));
    }

    #[test]
    fn test_validate_gpa_invalido() {
        assert_eq!(validate_gpa(""), None);
        assert_eq!(validate_gpa("abc"), None);
        assert_eq!(validate_gpa("11.0"), None);
        assert_eq!(validate_gpa("-1.0"), None);
    }

    #[test]
    fn test_validate_gre_section_quant() {
        assert_eq!(validate_gre_section("165", "Q"), Some(165.0));
        assert_eq!(validate_gre_section("130", "Q"), Some(130.0));
        assert_eq!(validate_gre_section("170", "Q"), Some(170.0));
        assert_eq!(validate_gre_section("129", "Q"), None);
        assert_eq!(validate_gre_section("171", "Q"), None);
    }

    #[test]
    fn test_validate_gre_section_verbal() {
        assert_eq!(validate_gre_section("160", "V"), Some(160.0));
        assert_eq!(validate_gre_section("125", "V"), None);
    }

    #[test]
    fn test_validate_gre_section_aw() {
        assert_eq!(validate_gre_section("5.0", "AW"), Some(5.0));
        assert_eq!(validate_gre_section("0.0", "AW"), Some(0.0));
        assert_eq!(validate_gre_section("6.0", "AW"), Some(6.0));
        assert_eq!(validate_gre_section("6.5", "AW"), None);
        assert_eq!(validate_gre_section("-0.5", "AW"), None);
    }

    #[test]
    fn test_normalize_date_formatos() {
        assert_eq!(
            normalize_date("Jan 15, 2024"),
            Some("2024-01-15".to_string())
        );
        assert_eq!(
            normalize_date("January 15, 2024"),
            Some("2024-01-15".to_string())
        );
        assert_eq!(
            normalize_date("01/15/2024"),
            Some("2024-01-15".to_string())
        );
        assert_eq!(
            normalize_date("2024-01-15"),
            Some("2024-01-15".to_string())
        );
    }

    #[test]
    fn test_normalize_date_invalida() {
        assert_eq!(normalize_date(""), None);
        assert_eq!(normalize_date("   "), None);
        assert_eq!(normalize_date("no es una fecha"), None);
    }

    #[test]
    fn test_parse_page_html_vacio() {
        let postings = parse_page("<html><body></body></html>");
        assert!(postings.is_empty());
    }

    #[test]
    fn test_parse_page_tabla_basica() {
        let html = r#"
        <html><body>
        <table>
            <tr><th>School</th><th>Program</th><th>Date</th><th>Decision</th><th>Link</th></tr>
            <tr>
                <td>MIT</td>
                <td>Economics PhD</td>
                <td>Jan 15, 2024</td>
                <td>Accepted on 15 Jan</td>
                <td><a href="/result/12345">View</a></td>
            </tr>
        </table>
        </body></html>
        "#;

        let postings = parse_page(html);
        assert_eq!(postings.len(), 1);
        assert_eq!(postings[0].school, "MIT");
        assert_eq!(postings[0].program, "Economics");
        assert_eq!(postings[0].degree, Some("PhD".to_string()));
        assert_eq!(postings[0].gradcafe_id, "12345");
        assert_eq!(postings[0].decision, "Accepted on 15 Jan");
        assert_eq!(
            postings[0].date_added_iso,
            Some("2024-01-15".to_string())
        );
    }

    #[test]
    fn test_parse_page_con_detalles() {
        let html = r#"
        <html><body>
        <table>
            <tr><th>School</th><th>Program</th><th>Date</th><th>Decision</th><th>Link</th></tr>
            <tr>
                <td>Harvard</td>
                <td>Economics PhD</td>
                <td>Feb 01, 2024</td>
                <td>Rejected on 01 Feb</td>
                <td><a href="/result/67890">View</a></td>
            </tr>
            <tr class="tw-border-none">
                <td colspan="5">
                    <div class="tw-inline-flex">Fall 2024</div>
                    <div class="tw-inline-flex">International</div>
                    <div class="tw-inline-flex">GPA 3.90</div>
                    <div class="tw-inline-flex">GRE Q 168</div>
                    <div class="tw-inline-flex">GRE V 165</div>
                    <div class="tw-inline-flex">GRE AW 5.0</div>
                </td>
            </tr>
        </table>
        </body></html>
        "#;

        let postings = parse_page(html);
        assert_eq!(postings.len(), 1);
        assert_eq!(postings[0].season, Some("Fall 2024".to_string()));
        assert_eq!(postings[0].status, Some("International".to_string()));
        assert_eq!(postings[0].gpa, Some(3.90));
        assert_eq!(postings[0].gre_quant, Some(168.0));
        assert_eq!(postings[0].gre_verbal, Some(165.0));
        assert_eq!(postings[0].gre_aw, Some(5.0));
        assert_eq!(postings[0].gre_combined, Some(333.0));
    }

    #[test]
    fn test_parse_page_con_comentario() {
        let html = r#"
        <html><body>
        <table>
            <tr><th>School</th><th>Program</th><th>Date</th><th>Decision</th><th>Link</th></tr>
            <tr>
                <td>Stanford</td>
                <td>Finance Masters</td>
                <td>Mar 10, 2024</td>
                <td>Accepted on 10 Mar</td>
                <td><a href="/result/11111">View</a></td>
            </tr>
            <tr class="tw-border-none">
                <td colspan="5">
                    <div class="tw-inline-flex">Spring 2024</div>
                    <div class="tw-inline-flex">American</div>
                </td>
            </tr>
            <tr class="tw-border-none">
                <td colspan="5">
                    <p>Very excited about this acceptance!</p>
                </td>
            </tr>
        </table>
        </body></html>
        "#;

        let postings = parse_page(html);
        assert_eq!(postings.len(), 1);
        assert_eq!(postings[0].school, "Stanford");
        assert_eq!(postings[0].program, "Finance");
        assert_eq!(postings[0].degree, Some("Masters".to_string()));
        assert_eq!(postings[0].season, Some("Spring 2024".to_string()));
        assert_eq!(postings[0].status, Some("American".to_string()));
        assert_eq!(
            postings[0].comment,
            Some("Very excited about this acceptance!".to_string())
        );
    }

    #[test]
    fn test_gre_combinado_calculado() {
        let html = r#"
        <html><body>
        <table>
            <tr><th>School</th><th>Program</th><th>Date</th><th>Decision</th><th>Link</th></tr>
            <tr>
                <td>Columbia</td>
                <td>Economics PhD</td>
                <td>Jan 20, 2024</td>
                <td>Accepted on 20 Jan</td>
                <td><a href="/result/22222">View</a></td>
            </tr>
            <tr class="tw-border-none">
                <td colspan="5">
                    <div class="tw-inline-flex">GRE Q 168</div>
                    <div class="tw-inline-flex">GRE V 164</div>
                </td>
            </tr>
        </table>
        </body></html>
        "#;

        let postings = parse_page(html);
        assert_eq!(postings.len(), 1);
        assert_eq!(postings[0].gre_quant, Some(168.0));
        assert_eq!(postings[0].gre_verbal, Some(164.0));
        assert_eq!(postings[0].gre_combined, Some(332.0));
    }

    #[test]
    fn test_gre_formato_parentesis() {
        let html = r#"
        <html><body>
        <table>
            <tr><th>School</th><th>Program</th><th>Date</th><th>Decision</th><th>Link</th></tr>
            <tr>
                <td>Princeton</td>
                <td>Economics PhD</td>
                <td>Feb 05, 2024</td>
                <td>Accepted on 05 Feb</td>
                <td><a href="/result/33333">View</a></td>
            </tr>
            <tr class="tw-border-none">
                <td colspan="5">
                    <div class="tw-inline-flex">169 (Q)</div>
                    <div class="tw-inline-flex">166 (V)</div>
                    <div class="tw-inline-flex">5.5 (AW)</div>
                </td>
            </tr>
        </table>
        </body></html>
        "#;

        let postings = parse_page(html);
        assert_eq!(postings.len(), 1);
        assert_eq!(postings[0].gre_quant, Some(169.0));
        assert_eq!(postings[0].gre_verbal, Some(166.0));
        assert_eq!(postings[0].gre_aw, Some(5.5));
        assert_eq!(postings[0].gre_combined, Some(335.0));
    }

    #[test]
    fn test_gre_sin_etiqueta_combinado() {
        let html = r#"
        <html><body>
        <table>
            <tr><th>School</th><th>Program</th><th>Date</th><th>Decision</th><th>Link</th></tr>
            <tr>
                <td>Yale</td>
                <td>Economics PhD</td>
                <td>Jan 25, 2024</td>
                <td>Rejected on 25 Jan</td>
                <td><a href="/result/44444">View</a></td>
            </tr>
            <tr class="tw-border-none">
                <td colspan="5">
                    <div class="tw-inline-flex">GRE 330</div>
                </td>
            </tr>
        </table>
        </body></html>
        "#;

        let postings = parse_page(html);
        assert_eq!(postings.len(), 1);
        assert_eq!(postings[0].gre_quant, None);
        assert_eq!(postings[0].gre_combined, Some(330.0));
    }
}
