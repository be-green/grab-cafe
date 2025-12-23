# GradCafe Bot - Architecture Documentation

**Last Updated:** December 23, 2025
**Model:** Qwen3-1.7B
**Database:** 30,545+ economics graduate admissions postings

---

## Table of Contents
1. [Project Overview](#project-overview)
2. [System Architecture](#system-architecture)
3. [Data Flow](#data-flow)
4. [Component Details](#component-details)
5. [Database Schema](#database-schema)
6. [LLM Integration](#llm-integration)
7. [Key Design Decisions](#key-design-decisions)
8. [Deployment](#deployment)
9. [Common Operations](#common-operations)
10. [Troubleshooting](#troubleshooting)

---

## Project Overview

### Purpose
A Discord bot that:
1. Monitors TheGradCafe.com for new economics graduate admissions results
2. Posts new results to a Discord channel automatically every 60 seconds
3. Answers natural language queries about admissions data using a local LLM (Gary)

### History
- **Original:** R script + Python + CSV storage + cron jobs
- **Refactored:** Native Python + SQLite + Discord bot + embedded LLM
- **Migration:** Converted from CSV to SQLite, scraped full GradCafe history (30,545 postings)
- **LLM Added:** Integrated Qwen3-1.7B for natural language SQL generation

---

## System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     Discord Bot (bot_with_llm.py)            │
│  ┌──────────────────────┐    ┌──────────────────────────┐   │
│  │  Background Task     │    │   Message Handler        │   │
│  │  (every 60s)         │    │   (@mention triggers)    │   │
│  │                      │    │                          │   │
│  │  1. Scrape GradCafe  │    │  1. Parse user question  │   │
│  │  2. Store new posts  │    │  2. Call LLM (Gary)      │   │
│  │  3. Post to Discord  │    │  3. Return answer + plot │   │
│  └──────────────────────┘    └──────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
                    ↓                           ↓
┌──────────────────────────────┐   ┌──────────────────────────┐
│   Scraper (scraper.py)       │   │   LLM Interface          │
│                              │   │   (llm_interface.py)     │
│  - Beautiful Soup scraping   │   │                          │
│  - Pagination support        │   │  ┌────────────────────┐  │
│  - Extract gradcafe_id       │   │  │ Qwen3-1.7B Model   │  │
│  - Parse posting fields      │   │  │ (SimpleLLM class)  │  │
│                              │   │  └────────────────────┘  │
└──────────────────────────────┘   │                          │
                ↓                  │  1. Generate SQL         │
┌──────────────────────────────┐   │  2. Execute query        │
│   Database (database.py)     │   │  3. Format results       │
│                              │←──│  4. Create plot          │
│  - SQLite connection         │   └──────────────────────────┘
│  - CRUD operations           │                ↓
│  - Deduplication             │   ┌──────────────────────────┐
│  - Discord formatting        │   │   LLM Tools              │
│                              │   │   (llm_tools.py)         │
│  gradcafe_messages.db        │   │                          │
│  (30,545 postings)           │   │  - execute_sql_query()   │
└──────────────────────────────┘   │  - create_plot()         │
                                   │  - get_database_schema() │
                                   └──────────────────────────┘
```

---

## Data Flow

### Flow 1: Automatic Posting (Background Task)
```
1. Bot starts → check_gradcafe_task() runs every 60 seconds
2. fetch_and_store_new_postings() → scrapes GradCafe page 1
3. For each result:
   - Extract gradcafe_id from URL (/result/987590)
   - Check posting_exists(gradcafe_id)
   - If new: add_posting() to database
4. get_unposted_postings() → fetch new posts not yet on Discord
5. For each unposted:
   - format_posting_for_discord()
   - Send to Discord channel
   - mark_posting_as_posted()
```

### Flow 2: LLM Query (@mention)
```
1. User mentions bot: "@GradCafeBot What month do acceptances come out?"
2. on_message() triggered
3. Strip mention from message → "What month do acceptances come out?"
4. query_llm(user_question):
   a. Load Qwen3-1.7B model (singleton pattern)
   b. generate_sql(user_question):
      - Create prompt with schema + few-shot examples
      - Model generates SQL query
   c. _extract_sql() → parse SQL from response
   d. execute_sql_query(sql) → run against database
   e. format_results() → natural language response
   f. _should_plot() → check if visualization needed
   g. create_plot() if applicable
5. Send response text to Discord
6. Send plot file if generated
7. Delete plot file
```

---

## Component Details

### 1. bot_with_llm.py (Main Application)
**Purpose:** Discord bot with background tasks and LLM integration

**Key Classes:**
- `GradCafeBotWithLLM(discord.Client)`
  - Inherits from discord.Client
  - Uses discord.py 2.0+ (requires `message_content` intent)
  - Singleton LLM instance for efficiency

**Important Methods:**
- `on_ready()`: Initialize, load LLM in background
- `on_message()`: Handle @mentions, call query_llm()
- `check_gradcafe_task()`: Background loop (@tasks.loop decorator)
- `before_check_task()`: Wait for bot ready before starting loop

**Environment Variables:**
- `DISCORD_TOKEN`: Bot authentication (required)
- `DISCORD_CHANNEL_ID`: Channel ID for posting (required)
- `CHECK_INTERVAL_SECONDS`: Scraping interval (default: 60)
- `ENABLE_LLM`: Enable/disable LLM queries (default: true)

**Critical Detail:** Line 46 chains both mention formats:
```python
user_question = message.content.replace(f'<@{self.user.id}>', '').replace(f'<@!{self.user.id}>', '').strip()
```
This handles both regular and nickname mentions.

---

### 2. database.py (Data Layer)
**Purpose:** SQLite database operations and business logic

**Key Functions:**
- `init_database()`: Create table if not exists
- `posting_exists(gradcafe_id)`: Check for duplicates
- `add_posting(posting)`: Insert new posting
- `get_unposted_postings()`: Fetch posts not yet on Discord
- `mark_posting_as_posted(posting_id)`: Update posted flag
- `format_posting_for_discord(posting)`: Create Discord message

**Database File:** `gradcafe_messages.db`

**Schema:**
```sql
CREATE TABLE postings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    gradcafe_id TEXT NOT NULL UNIQUE,      -- Key deduplication field
    school TEXT NOT NULL,
    program TEXT NOT NULL,
    degree TEXT,
    decision TEXT NOT NULL,                 -- Format: "Accepted on 15 Dec"
    date_added TEXT NOT NULL,
    season TEXT,                            -- "F24", "S25", etc.
    status TEXT,                            -- "American", "International", "Other"
    gpa REAL,                               -- Converted to numeric
    gre_quant REAL,                         -- Converted to numeric
    gre_verbal REAL,                        -- Converted to numeric
    gre_aw REAL,                            -- Converted to numeric
    comment TEXT,
    scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    posted_to_discord BOOLEAN DEFAULT 0
)
```

**Critical Design Decision:**
- **gradcafe_id is the unique key**, not (school, program, decision, date)
- This allows multiple students from same school/program/date to be tracked
- gradcafe_id extracted from result URL: `/result/987590` → `987590`

---

### 3. scraper.py (Web Scraping)
**Purpose:** Scrape TheGradCafe.com for admissions results

**Key Functions:**
- `scrape_gradcafe_page(page=1)`: Scrape single page
- `fetch_and_store_new_postings()`: Scrape page 1 and store
- `scrape_all_history(start_page, end_page)`: Bulk historical scraping

**Scraping Strategy:**
- URL: `https://www.thegradcafe.com/survey/index.php?q=economics&t=a&pp=250&p={page}`
- Uses Beautiful Soup to parse HTML tables
- Extracts gradcafe_id from result link href
- Respects rate limits (0.1s delay between pages)

**Field Extraction:**
```python
gradcafe_id = extract from <a href="/result/987590">
school = cells[0].text.strip()
program = cells[1].text.strip()
decision = cells[2].text.strip()  # "Accepted on 15 Dec"
date_added = cells[4].text.strip()
```

**Note:** GRE Verbal and AW are rarely populated on GradCafe

---

### 4. llm_interface.py (LLM Logic)
**Purpose:** Natural language to SQL using Qwen3-1.7B

**Key Class:** `SimpleLLM`

**Initialization:**
```python
MODEL_NAME = "Qwen/Qwen3-1.7B"
- Loads model with AutoModelForCausalLM
- Uses FP16 on GPU, FP32 on CPU
- Singleton pattern via get_llm()
```

**Core Method:** `generate_sql(user_question)`

**Prompt Structure:**
1. Role definition: "You are Gary, a skilled SQL engineer from Minneapolis"
2. Database schema with detailed notes
3. Important reminders (LIKE for decision field, numeric types)
4. **6 few-shot examples** (critical for performance)
5. User question
6. Instruction: "Generate ONLY the SQL query"

**Few-Shot Examples Cover:**
- COUNT queries
- GROUP BY with ORDER BY
- AVG with NULL filtering
- Percentage calculations
- Date functions (strftime)

**SQL Extraction:** `_extract_sql()`
- Handles markdown code blocks (```sql)
- Handles plain SQL
- Regex fallback for SELECT statements

**Result Formatting:** `format_results()`
- Single value: "The answer is X"
- Count: "There are X results"
- Average: "The average is X.XX"
- List: Numbered bullet points
- Large results: Show first 10, indicate total

**Visualization Logic:**
- `_should_plot()`: Check for keywords (chart, graph, plot, top, compare)
- `_infer_plot_type()`: trend→line, distribution→histogram, default→bar

---

### 5. llm_tools.py (LLM Utilities)
**Purpose:** Database query execution and plotting

**Function:** `execute_sql_query(query)`
- **Safety:** Only allows SELECT queries
- **Validation:** Blocks INSERT, UPDATE, DELETE, DROP, CREATE, ALTER
- **Timeout:** 30 seconds max
- **Returns:** `{columns: [...], rows: [[...]], error: None}`

**Function:** `create_plot(result, plot_type, title, xlabel, ylabel)`
- Uses matplotlib + seaborn
- Supports: bar, line, histogram
- Saves to timestamped PNG file
- Returns filename for Discord upload

**Function:** `get_database_schema()`
- Returns formatted schema documentation
- Used in LLM prompt construction

---

### 6. scrape_history.py (Historical Scraping)
**Purpose:** One-time bulk scrape of entire GradCafe history

**Usage:**
```bash
python scrape_history.py
```

**Stats from last run:**
- 1,529 pages scraped
- 30,545 unique postings
- ~18 minutes total
- 0 duplicates (all unique gradcafe_ids)

**Note:** This is a utility script, not part of the bot runtime

---

## Database Schema

### Field Details

**gradcafe_id** (TEXT, UNIQUE)
- Extracted from result URL
- Example: `987590` from `/result/987590`
- **Primary deduplication key**
- Cannot be NULL

**decision** (TEXT)
- Format: `"[Action] on [Date]"`
- Examples: `"Accepted on 15 Dec"`, `"Rejected on 20 Nov"`
- **Important:** Always use `LIKE 'Accepted%'` in queries, not `= 'Accepted'`
- Values: Accepted, Rejected, Interview, Wait listed, Other

**status** (TEXT)
- Values: `"American"`, `"International"`, `"Other"`
- **Case-sensitive**
- About 75% International, 25% American

**season** (TEXT)
- Format: `"F24"` (Fall 2024), `"S25"` (Spring 2025)
- F = Fall, S = Spring

**Numeric Fields** (REAL)
- gpa: 0.0-5.0 (some international scales go to 5.0)
- gre_quant: 130-170
- gre_verbal: 130-170 (rarely populated)
- gre_aw: 0.0-6.0 (rarely populated)

**Migration Note:**
- Originally TEXT, converted to REAL via `migrate_to_numeric.py`
- Invalid values (empty, 'n/a', out of range) → NULL
- 7,491 GPA values, 7,695 GRE Quant values migrated successfully

---

## LLM Integration

### Model: Qwen3-1.7B
- **Size:** 1.7B parameters (~3.4GB)
- **Type:** Instruction-tuned (no "-Instruct" suffix in name)
- **Features:** Thinking/non-thinking mode support
- **Released:** May 2025 (latest small Qwen model)

### Performance Characteristics
- **RAM:** ~5GB for model + overhead
- **CPU Inference:** 5-10 seconds per query (2 vCPUs)
- **GPU Inference:** <1 second (if available)
- **First run:** Downloads model (~3.4GB)

### Prompt Engineering Strategy

**Why Few-Shot Examples Matter:**
- Small models (1.7B) need concrete examples
- Shows correct SQL syntax patterns
- Demonstrates LIKE usage for decision field
- Prevents schema hallucination (no fake table names)

**Critical Prompt Elements:**
1. **Role/Persona:** "Gary from Minneapolis" (humanizes, improves tone)
2. **Schema Notes:** Explain decision format, status values
3. **LIKE Reminder:** Emphasize `decision LIKE 'Accepted%'` not `= 'Accepted'`
4. **Examples:** 6 diverse queries covering common patterns
5. **Output Format:** "Generate ONLY the SQL query" (prevents explanations)

**Common Failure Modes (and how we prevent them):**
1. Schema hallucination → Provide exact schema, remind "only postings table"
2. Aggregate syntax errors → Show GROUP BY examples
3. Wrong field values → Document actual values in notes
4. Verbose output → Explicitly request "ONLY the SQL query"

### Gary's Personality
- Name: Gary
- Location: Minneapolis
- Role: Skilled and friendly SQL engineer
- Helps: Graduate school applicants understand admissions data

*Note: The personality doesn't affect SQL generation but makes responses friendlier*

---

## Key Design Decisions

### 1. Why SQLite instead of PostgreSQL/MySQL?
- **Simplicity:** Single file, no server process
- **Portability:** Easy to backup/transfer
- **Performance:** Fast enough for 30K rows with proper indexing
- **Cost:** No database hosting fees

### 2. Why gradcafe_id as unique key?
**Problem:** Original approach used (school, program, decision, date) as uniqueness check
- This deduplicated from 30,545 → 15,858 postings
- Lost valuable individual submission data

**Solution:** Use GradCafe's unique result ID
- Every submission has unique `/result/XXXXX` URL
- Preserves all 30,545 individual submissions
- No false deduplication

### 3. Why Qwen3-1.7B instead of larger model?
**Considered:**
- GPT-3.5 API: Fast but ongoing costs ($$$)
- Qwen2.5-1.5B: Older, less capable
- Qwen3-4B: Better but 2x larger (8GB), slower
- Llama 3 8B: Too large for CPU inference

**Chosen:** Qwen3-1.7B
- Best balance of size/performance
- Latest small model (May 2025)
- Works on 8GB RAM server
- Acceptable 5-10s response time
- No API costs

### 4. Why numeric conversion for GPA/GRE?
**Benefits:**
- Faster queries (no CAST needed)
- Cleaner SQL in LLM prompts
- Better index performance
- Native comparison operators (>, <, AVG)

**Trade-off:**
- Needed migration script
- Invalid data → NULL (acceptable)

### 5. Why background task instead of webhooks?
**Polling (chosen):**
- GradCafe has no webhook API
- Simple to implement
- Predictable server load
- 60s delay acceptable

**Webhooks (not possible):**
- Would require GradCafe integration
- Not available for scraping scenarios

### 6. Why Discord bot instead of web app?
- User base already on Discord
- Real-time notifications
- No frontend development needed
- Built-in authentication (Discord handles it)
- Easy @mention interface for queries

---

## Deployment

### Server Requirements
**Minimum:**
- 8GB RAM
- 2 vCPUs
- 10GB disk space
- Python 3.8+
- Ubuntu 20.04+ or similar

**Recommended Providers:**
- DigitalOcean: $48/month droplet (8GB RAM, 2 vCPUs)
- Google Cloud: e2-standard-2 instance
- AWS: t3.large instance

### Setup Steps

1. **Install dependencies:**
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

2. **Set environment variables:**
```bash
export DISCORD_TOKEN="your_discord_bot_token"
export DISCORD_CHANNEL_ID="your_channel_id"
export CHECK_INTERVAL_SECONDS=60
export ENABLE_LLM=true
```

Or use `.env` file (copy from `.env.example`)

3. **Initialize database:**
```bash
python -c "from database import init_database; init_database()"
```

4. **Run bot:**
```bash
python bot_with_llm.py
```

5. **Production (with systemd):**
```ini
[Unit]
Description=GradCafe Discord Bot
After=network.target

[Service]
Type=simple
User=botuser
WorkingDirectory=/path/to/grab-cafe
Environment="DISCORD_TOKEN=your_token"
Environment="DISCORD_CHANNEL_ID=your_id"
ExecStart=/path/to/venv/bin/python bot_with_llm.py
Restart=always

[Install]
WantedBy=multi-user.target
```

---

## Common Operations

### Check Bot Status
```bash
# Check if process running
ps aux | grep bot_with_llm.py

# Check logs (if using systemd)
journalctl -u gradcafe-bot -f
```

### Query Database Directly
```bash
sqlite3 gradcafe_messages.db "SELECT COUNT(*) FROM postings;"
sqlite3 gradcafe_messages.db "SELECT * FROM postings WHERE school LIKE '%Stanford%' LIMIT 5;"
```

### Re-scrape History
```bash
python scrape_history.py
# Takes ~18 minutes for full scrape
```

### Test LLM Queries
```bash
python test_qwen_queries.py
```

### Run Diagnostics
```bash
python diagnostics.py
```

### Backup Database
```bash
cp gradcafe_messages.db gradcafe_messages_backup_$(date +%Y%m%d).db
```

---

## Troubleshooting

### "Model not found" error
**Cause:** First run needs to download model
**Solution:** Wait for download (~3.4GB), ensure internet connection

### "Out of memory" error
**Cause:** Server has <6GB RAM
**Solution:**
- Upgrade server to 8GB
- Use smaller model (Qwen3-0.6B)
- Disable LLM with `ENABLE_LLM=false`

### Bot not posting to Discord
**Check:**
1. Is `DISCORD_CHANNEL_ID` correct?
2. Does bot have permissions in that channel?
3. Are there new postings? Check: `get_unposted_postings()`
4. Check bot logs for errors

### LLM generating incorrect SQL
**Common issues:**
1. Using `= 'Accepted'` instead of `LIKE 'Accepted%'`
   - **Fix:** Update few-shot examples in prompt
2. Hallucinating table names
   - **Fix:** Add explicit "only postings table" reminder
3. Missing GROUP BY
   - **Fix:** Add more GROUP BY examples

### Scraper not finding new postings
**Check:**
1. Is GradCafe website structure changed? (view page source)
2. Are you rate-limited? (increase delay in scraper.py)
3. Check scraper logs for parsing errors

### Database locked error
**Cause:** Multiple processes accessing database
**Solution:** Ensure only one bot instance running

---

## Testing

### Test Files

**test_qwen_queries.py**
- Tests LLM SQL generation on 4 sample questions
- Validates query execution
- Checks response formatting
- Run before deploying changes to prompts

**test_llm.py**
- Tests SQL safety (blocks dangerous queries)
- Tests basic query execution
- Tests schema retrieval

**diagnostics.py**
- Comprehensive database checks
- Verifies no duplicate gradcafe_ids
- Checks field populations
- Validates data integrity

### Manual Testing Checklist

**Before Deployment:**
- [ ] Run `python test_qwen_queries.py`
- [ ] Run `python diagnostics.py`
- [ ] Test @mention in Discord test server
- [ ] Verify background task posts new results
- [ ] Check logs for errors

---

## Future Improvements

**Potential Enhancements:**
1. **Caching:** Cache common SQL queries for faster responses
2. **Queue System:** Handle multiple simultaneous LLM queries
3. **Smaller Model:** Try Qwen3-0.6B for faster responses
4. **GPU Support:** Add CUDA support for 10x faster inference
5. **Web Dashboard:** Add simple web UI for browsing data
6. **More Programs:** Expand beyond economics to other fields
7. **Sentiment Analysis:** Analyze comment sentiment
8. **Prediction Model:** Predict admission chances based on stats

---

## File Summary

**Production Code:**
- `bot_with_llm.py` - Main Discord bot application
- `database.py` - Database operations and business logic
- `llm_interface.py` - LLM integration (Qwen3-1.7B)
- `llm_tools.py` - SQL execution, plotting utilities
- `scraper.py` - GradCafe web scraping
- `scrape_history.py` - Historical bulk scraping utility

**Testing:**
- `test_qwen_queries.py` - LLM query tests
- `test_llm.py` - Basic LLM functionality tests
- `diagnostics.py` - Database integrity checks

**Documentation:**
- `README.md` - Basic project overview
- `LLM_SETUP.md` - LLM setup instructions
- `ARCHITECTURE.md` - This file (comprehensive architecture)

**Configuration:**
- `requirements.txt` - Python dependencies
- `.env.example` - Environment variable template
- `.gitignore` - Git ignore rules

**Data:**
- `gradcafe_messages.db` - SQLite database (30,545 postings)

---

## Dependencies Explained

**Core:**
- `discord.py>=2.0.0` - Discord bot framework (requires message_content intent)
- `requests>=2.28.0` - HTTP requests for web scraping
- `beautifulsoup4>=4.11.0` - HTML parsing for scraper

**Data:**
- `pandas>=1.5.0` - Data manipulation (used in plotting)

**LLM:**
- `torch>=2.0.0` - PyTorch for model inference
- `transformers>=4.35.0` - Hugging Face model loading
- `accelerate>=0.24.0` - Optimized model loading

**Visualization:**
- `matplotlib>=3.5.0` - Plotting library
- `seaborn>=0.12.0` - Statistical visualization (prettier plots)

---

## Glossary

**GradCafe:** TheGradCafe.com - community site for sharing graduate admissions results

**gradcafe_id:** Unique identifier for each posting on GradCafe (extracted from URL)

**Gary:** Persona name for the LLM assistant

**Qwen3-1.7B:** Latest small instruction-tuned language model from Alibaba Cloud

**Few-shot prompting:** Providing examples in the prompt to guide model behavior

**Singleton pattern:** Design pattern ensuring only one LLM instance loads (saves memory)

**Background task:** Discord.py task that runs on a schedule (every 60s)

**Intents:** Discord API permissions required for bot functionality

---

## Contact & Maintenance

**When to Update This Doc:**
- Model version changes
- Database schema modifications
- New features added
- Architectural changes
- Performance optimizations discovered

**Version History:**
- v1.0 (Dec 2025): Initial architecture with Qwen3-1.7B, SQLite, full refactor from R/CSV

---

*End of Architecture Documentation*
