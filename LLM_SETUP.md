# GradCafe Bot with LLM Query System

## Overview

The bot now has an interactive LLM-powered query system that can answer questions about the graduate admissions database using Qwen2.5-0.5B-Instruct.

## Features

- **Natural Language Queries**: Ask questions in plain English
- **Read-Only SQL Access**: LLM can query the database safely
- **Automatic Visualizations**: Creates charts when appropriate
- **30,545 Admissions Results**: Complete economics grad school dataset

## Setup

### 1. Install Dependencies

```bash
source venv/bin/activate
pip install -r requirements.txt
```

Note: First run will download the Qwen model (~600MB). This happens automatically.

### 2. Environment Variables

Add to your `.env` file:

```bash
# Required for basic bot
DISCORD_TOKEN=your_token_here
DISCORD_CHANNEL_ID=your_channel_id

# Optional - LLM features
ENABLE_LLM=true  # Set to 'false' to disable LLM queries
```

### 3. Run the Enhanced Bot

```bash
python bot_with_llm.py
```

## Usage

### Automatic Posting (unchanged)
The bot continues to monitor GradCafe and post new results automatically.

### Interactive Queries
Tag the bot with a question:

```
@GradCafeBot What month do most acceptances come out?
@GradCafeBot Which schools send the most interviews?
@GradCafeBot What's the average GPA of accepted students at Stanford?
@GradCafeBot Show me acceptance trends over time
```

## Example Questions

**Timing & Trends:**
- "What month do most acceptances come out?"
- "When do schools typically send interview invitations?"
- "Show me decision trends over the year"

**School Comparisons:**
- "Which schools have the highest acceptance rates?"
- "Compare MIT vs Harvard acceptance rates"
- "Which schools send the most interviews?"

**Applicant Statistics:**
- "What's the average GPA of accepted students?"
- "What GRE scores do successful applicants have?"
- "International vs American acceptance rates"

**Specific Schools:**
- "How many people got into Stanford?"
- "What are Yale's interview statistics?"
- "Show me all Berkeley Economics decisions"

## How It Works

1. **User mentions bot** with a question
2. **LLM analyzes** the question and determines what data is needed
3. **Executes SQL query** (read-only) on the database
4. **Generates response** in natural language
5. **Creates visualization** if appropriate
6. **Posts to Discord** with text + optional chart

## Safety Features

- ✓ **Read-only SQL**: Can only SELECT, no modifications
- ✓ **Query filtering**: Blocks INSERT/UPDATE/DELETE/DROP
- ✓ **Timeout protection**: Queries limited in execution time
- ✓ **Error handling**: Graceful failures with user-friendly messages

## Performance

- **CPU**: Works fine on CPU-only servers
- **GPU**: Faster inference if CUDA available
- **Memory**: ~1.5GB RAM for model
- **Response time**: 2-10 seconds per query

## Files

- `bot_with_llm.py` - Enhanced Discord bot
- `llm_interface.py` - Qwen model integration
- `llm_tools.py` - Database query and plotting tools
- `test_llm.py` - Test suite for LLM features

## Troubleshooting

**Model won't download:**
```bash
# Manually download
python -c "from transformers import AutoModelForCausalLM; AutoModelForCausalLM.from_pretrained('Qwen/Qwen2.5-0.5B-Instruct')"
```

**Out of memory:**
- Use smaller model or reduce batch size
- Ensure bot has sufficient RAM (~2GB recommended)

**Slow responses:**
- Normal on CPU (5-10s)
- Consider GPU for faster inference

**LLM not responding:**
- Check `ENABLE_LLM=true` in environment
- Verify model downloaded successfully
- Check bot logs for errors

## Fallback Mode

If you want to run without LLM features:
```bash
export ENABLE_LLM=false
python bot_with_llm.py
```

Or use the original bot:
```bash
python bot.py  # No LLM features
```
