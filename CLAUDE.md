# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

GradCafe Discord Bot - monitors TheGradCafe.com for economics and finance graduate admissions results and provides an intelligent Discord bot interface. The bot:
- Scrapes GradCafe every 60 seconds for new postings
- Posts new results automatically to a Discord channel
- Answers natural language queries using a two-stage LLM pipeline (OpenRouter API)
- Maintains a SQLite database of 30,000+ historical economics admissions postings

## Commands

```bash
# Setup
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Run the bot
python bot_with_llm.py

# Run tests
python test_parser_fixes.py      # Parser validation
python test_workflow.py          # Interactive LLM workflow testing
python test_llm.py               # LLM safety and query tests
python diagnostics.py            # Database integrity checks

# Query database directly
sqlite3 gradcafe_messages.db "SELECT COUNT(*) FROM postings;"

# Historical scraping (one-time utility)
python scrape_history.py
```

## Architecture

### Core Files
- **bot_with_llm.py** - Main Discord bot with background scraping task and message handling
- **llm_interface.py** - Two-stage LLM: Gary (SQL generation) + Beatriz (result summarization)
- **llm_tools.py** - Query execution (read-only enforced), visualization, schema retrieval
- **scraper.py** - BeautifulSoup parsing of GradCafe, field extraction, validation
- **database.py** - SQLite CRUD, deduplication via gradcafe_id, Discord formatting

### Data Flow
1. **Background Task (every 60s):** Scrape GradCafe → store new postings → refresh aggregation tables → post to Discord
2. **LLM Query (@mention):** User question → Beatriz analyzes → Gary generates SQL → execute query → optional plot → Beatriz summarizes

### Database Schema
- **postings** - Main table (30,545 rows) with gradcafe_id as unique key
- **phd** - Aggregation table (8,241 rows) for LLM queries, filtered to PhD + year > 2018
- **masters** - Aggregation table (1,155 rows) for LLM queries, filtered to Masters + year > 2018

Key fields: school, program, degree, decision (format: "Accepted on 15 Dec"), date_added_iso, season (F24/S25), status (American/International), gpa, gre_quant, gre_combined

### LLM Design
- Uses OpenRouter API with configurable models (default: gpt-4o-mini)
- Two personas: Gary (SQL engineer) generates queries, Beatriz (Borges narrator) summarizes results
- Few-shot prompting guides model to use phd/masters tables, not postings
- SQL safety: only SELECT allowed, blocks INSERT/UPDATE/DELETE/DROP/CREATE/ALTER

## Environment Variables

Required:
- `DISCORD_TOKEN` - Bot authentication
- `DISCORD_CHANNEL_ID` - Channel for posting results
- `OPENROUTER_API_KEY` - API key for LLM

Optional:
- `OPENROUTER_SQL_MODEL` / `OPENROUTER_SUMMARY_MODEL` - Model selection (default: openai/gpt-4o-mini)
- `CHECK_INTERVAL_SECONDS` - Scraping interval (default: 60)
- `ENABLE_LLM` - Enable/disable LLM features (default: true)
- `POST_LOOKBACK_DAYS` - Days to check for unposted (default: 1)

## Key Patterns

- **Deduplication:** Uses gradcafe_id (from URL /result/XXXXX), not (school, program, date) tuple
- **Decision field:** Always use `LIKE 'Accepted%'` not `= 'Accepted'` (format is "Accepted on 15 Dec")
- **Singleton LLM:** Single instance loaded via `get_llm()` for efficiency
- **Context manager:** `get_db_connection()` ensures proper commit/rollback/close
- **Background task:** Uses `@tasks.loop(seconds=60)` decorator with before hook for bot ready
