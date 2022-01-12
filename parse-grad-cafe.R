library(rvest)
library(magrittr)
library(data.table)
library(httr)
library(stringr)
library(reticulate)
reticulate::use_virtualenv("bot-env")

existing <- fread("messages.csv")

s <- rvest::read_html("https://www.thegradcafe.com/survey/?institution=&program=economics") %>% 
  html_element("#results-container") %>% 
  html_elements(".col")

l <- sapply(s, function(x) {
    link <- html_elements(x, "a") %>% html_attr("href")
    link <- paste0("https://www.thegradcafe.com", link)
    x <- html_text(x)
    x <- str_split(x, "\t\t\t", simplify = F)
    x  <- x[[1]]
    x <- subset(x, str_detect(x, "[A-Za-z0-9]+"))
    x <- str_replace_all(x, "[\t\n]+"," ")
    x <- str_trim(x)
    x <- str_replace_all(x, "Economics, ", "")
    x <- x[-length(x)]
    second <- str_extract(paste0(x, collapse = "; "), "Added on .*")
    first <- paste0(x, collapse = "; ")
    first <- str_replace_all(first, second, "") %>% 
      str_replace_all(";","") %>% 
      str_trim %>% 
      str_replace_all("  ", ": ")
    paste0(first,"\n",second, "\n",link) 
  })


l <- subset(l, !str_detect(l, "NA\nNA"))
  
l <- setdiff(l, existing$Messages)

if(length(l) > 0) {
  fwrite(data.table(Index = (max(existing$Index) + 1):(max(existing$Index) + length(l)), Messages = l), "messages.csv", append = T)
  fwrite(data.table(Index = 1:length(l), Messages = l), "new_messages.csv")
}
