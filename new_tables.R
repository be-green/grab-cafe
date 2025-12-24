library(RSQLite)
library(odbc)
library(magrittr)
library(data.table)

tmp = odbc::dbConnect(RSQLite::SQLite(), "../grab-cafe/gradcafe_messages.db")

postings = dbGetQuery(tmp, "select * from postings") %>% 
  as.data.table

postings[, decision_date := as.Date(paste0(decision_date, year(date_added_iso)),
                                    format = "%d %b %Y")]
postings[, admission_year := year(decision_date)]
postings[]

phd = postings[year(date_added_iso) > 2018 & degree == "PhD", .(school, program, gpa, gre = gre_quant, result)]
masters = postings[year(date_added_iso) > 2018 & degree == "Masters", .(school, program, gpa, gre = gre_quant, result)]

dbWriteTable(tmp, name = "phd", phd)
dbWriteTable(tmp, name = "masters", masters)




