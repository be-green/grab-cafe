import os
import torch
from transformers import AutoTokenizer, AutoModelForCausalLM
import re
from llm_tools import execute_sql_query, create_plot, get_database_schema

MODEL_NAME = "Qwen/Qwen3-1.7B"
USE_4BIT = os.getenv("USE_4BIT", "false").lower() == "true"

class SimpleLLM:
    def __init__(self):
        print("Loading Qwen model...")
        self.tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
        quantization_config = None
        if USE_4BIT and torch.cuda.is_available():
            try:
                from transformers import BitsAndBytesConfig
                quantization_config = BitsAndBytesConfig(
                    load_in_4bit=True,
                    bnb_4bit_compute_dtype=torch.float16
                )
                print("Using 4-bit quantization with bitsandbytes.")
            except Exception as e:
                print(f"4-bit quantization unavailable: {e}. Falling back to full precision.")
                quantization_config = None
        elif USE_4BIT:
            print("4-bit quantization requires CUDA; falling back to full precision on CPU.")

        self.model = AutoModelForCausalLM.from_pretrained(
            MODEL_NAME,
            torch_dtype=torch.float16 if torch.cuda.is_available() else torch.float32,
            device_map="auto" if torch.cuda.is_available() else None,
            quantization_config=quantization_config
        )

        if not torch.cuda.is_available():
            self.model = self.model.to('cpu')

        print(f"Model loaded on: {'GPU' if torch.cuda.is_available() else 'CPU'}")

        self.schema = get_database_schema()

    def generate_sql(self, user_question: str) -> str:
        """Generate SQL query from natural language question."""

        prompt = f"""You are Gary, a skilled and friendly SQL engineer based in Minneapolis. You help graduate school applicants understand admissions data by writing clear, efficient SQL queries.

DATABASE SCHEMA:
{self.schema}

IMPORTANT NOTES:
- The database is SQLite; use SQLite-compatible SQL (e.g., strftime for dates)
- The 'status' field contains: 'American', 'International', 'Other'
- The 'decision' field format: 'Accepted on [date]', 'Rejected on [date]', 'Interview on [date]', 'Wait listed on [date]', 'Other on [date]'
- ALWAYS use LIKE when filtering decision (e.g., "decision LIKE 'Accepted%'" not "decision = 'Accepted'")
- The 'date_added_iso' field stores ISO dates (YYYY-MM-DD); use it for date functions
- The 'season' field contains academic years like 'F24', 'F23' (F=Fall, S=Spring)
- GPA, GRE scores are stored as REAL (numeric) - can use directly in calculations (e.g., AVG(gpa), gpa > 3.5)
- Only use the 'postings' table - no other tables exist
- Always use proper GROUP BY when using aggregate functions
- Unless the user explicitly asks about Masters/MA/MS, default to PhD results (degree LIKE 'PhD%')

EXAMPLE QUERIES:

Q: How many total results are in the database?
A: SELECT COUNT(*) FROM postings

Q: What are the top 5 schools with the most acceptances?
A: SELECT school, COUNT(*) as acceptance_count FROM postings WHERE decision LIKE 'Accepted%' GROUP BY school ORDER BY acceptance_count DESC LIMIT 5

Q: What is the average GPA of accepted students?
A: SELECT AVG(gpa) FROM postings WHERE decision LIKE 'Accepted%' AND gpa IS NOT NULL

Q: What percentage of applicants are international vs American?
A: SELECT SUM(CASE WHEN status = 'International' THEN 1 ELSE 0 END) * 100.0 / COUNT(*) as international_pct, SUM(CASE WHEN status = 'American' THEN 1 ELSE 0 END) * 100.0 / COUNT(*) as american_pct FROM postings WHERE status IN ('American', 'International')

Q: Which schools send the most interview invitations?
A: SELECT school, COUNT(*) as interview_count FROM postings WHERE decision LIKE 'Interview%' GROUP BY school ORDER BY interview_count DESC LIMIT 10

Q: What month do most acceptances come out?
A: SELECT strftime('%m', date_added_iso) as month, COUNT(*) as acceptance_count FROM postings WHERE decision LIKE 'Accepted%' AND date_added_iso IS NOT NULL GROUP BY month ORDER BY acceptance_count DESC LIMIT 1

USER QUESTION: {user_question}

Generate ONLY the SQL query, nothing else. No explanations, no markdown formatting, just the SQL query.
SQL:"""

        inputs = self.tokenizer([prompt], return_tensors="pt").to(self.model.device)

        with torch.no_grad():
            outputs = self.model.generate(
                **inputs,
                max_new_tokens=200,
                temperature=0.3,
                do_sample=True,
                top_p=0.9,
                pad_token_id=self.tokenizer.eos_token_id
            )

        response = self.tokenizer.decode(outputs[0][inputs['input_ids'].shape[1]:], skip_special_tokens=True)
        return response.strip()

    def format_results(self, user_question: str, query_result: dict) -> str:
        """Format SQL results into natural language."""

        if query_result.get('error'):
            return f"I encountered an error: {query_result['error']}"

        if not query_result['rows']:
            return "I found no results for that query."

        rows = query_result['rows']
        columns = query_result['columns']

        if len(rows) == 1 and len(rows[0]) == 1:
            value = rows[0][0]
            if isinstance(value, (int, float)):
                if 'average' in user_question.lower() or 'mean' in user_question.lower():
                    if isinstance(value, float):
                        return f"The average is {value:.2f}"
                    return f"The average is {value}"
                elif 'count' in user_question.lower() or 'how many' in user_question.lower():
                    return f"There are {value:,} results"
                elif 'percentage' in user_question.lower() or 'percent' in user_question.lower():
                    return f"{value:.1f}%"
            return f"The answer is: {value}"

        if len(columns) == 2 and len(rows) <= 10:
            formatted = []
            for row in rows:
                formatted.append(f"{row[0]}: {row[1]}")
            return "\n".join(formatted)

        if len(rows) <= 20:
            formatted = "Here's what I found:\n"
            for i, row in enumerate(rows, 1):
                if len(row) == 1:
                    formatted += f"{i}. {row[0]}\n"
                else:
                    formatted += f"{i}. {' | '.join(str(x) for x in row)}\n"
            return formatted.strip()

        return f"I found {len(rows)} results. Here are the first few:\n" + "\n".join(
            [f"{i}. {' | '.join(str(x) for x in row)}" for i, row in enumerate(rows[:10], 1)]
        )

    def query(self, user_question: str):
        """
        Main query method: Generate SQL, execute, format results.
        Returns: (text_response, plot_filename or None)
        """
        print(f"Question: {user_question}")

        sql_response = self.generate_sql(user_question)
        print(f"Generated SQL: {sql_response}")

        sql_query = self._extract_sql(sql_response)
        if not sql_query:
            return "I couldn't generate a valid SQL query for that question. Could you rephrase it?", None

        print(f"Executing: {sql_query}")
        result = execute_sql_query(sql_query)

        plot_filename = None
        if not result.get('error') and result.get('rows') and self._should_plot(user_question):
            plot_filename = create_plot(
                result,
                self._infer_plot_type(user_question),
                user_question[:60],
                result['columns'][0] if len(result['columns']) > 0 else "X",
                result['columns'][1] if len(result['columns']) > 1 else "Count"
            )

        response = self.summarize_results(user_question, sql_query, result)
        return response, plot_filename

    def summarize_results(self, user_question: str, sql_query: str, query_result: dict) -> str:
        """Summarize SQL results using the LLM, with a rule-based fallback."""
        if query_result.get('error') or not query_result.get('rows'):
            return self.format_results(user_question, query_result)

        rows = query_result['rows']
        columns = query_result['columns']
        row_count = query_result.get('row_count', len(rows))
        sample_rows = rows[:20]

        prompt = f"""You are Gary, a skilled and friendly SQL engineer based in Minneapolis.
Summarize the SQL results for the user question. Be concise and factual.

Question: {user_question}
SQL: {sql_query}
Columns: {columns}
Row count: {row_count}
Rows (first {len(sample_rows)}): {sample_rows}

Provide a short summary and highlight key numbers. If the results are partial, say so."""

        try:
            inputs = self.tokenizer([prompt], return_tensors="pt").to(self.model.device)
            with torch.no_grad():
                outputs = self.model.generate(
                    **inputs,
                    max_new_tokens=200,
                    temperature=0.2,
                    do_sample=True,
                    top_p=0.9,
                    pad_token_id=self.tokenizer.eos_token_id
                )
            response = self.tokenizer.decode(outputs[0][inputs['input_ids'].shape[1]:], skip_special_tokens=True)
            return response.strip() or self.format_results(user_question, query_result)
        except Exception:
            return self.format_results(user_question, query_result)

    def _extract_sql(self, text: str) -> str:
        """Extract SQL query from model response."""
        text = text.strip()

        if "```sql" in text.lower():
            parts = text.split("```")
            for i, part in enumerate(parts):
                if part.strip().lower().startswith('sql'):
                    sql_content = part[3:].strip() if part.strip().lower().startswith('sql') else part.strip()
                    return sql_content.rstrip(';')

        if text.upper().startswith('SELECT'):
            lines = text.split('\n')
            sql_lines = []
            for line in lines:
                clean_line = line.strip()
                if clean_line and not clean_line.startswith('#') and not clean_line.startswith('--'):
                    sql_lines.append(clean_line)
                if ';' in clean_line:
                    break
            return ' '.join(sql_lines).rstrip(';')

        select_match = re.search(r'(SELECT\s+.+?)(?:;|\n\n|$)', text, re.IGNORECASE | re.DOTALL)
        if select_match:
            return select_match.group(1).strip().rstrip(';')

        return None

    def _should_plot(self, question: str) -> bool:
        """Determine if visualization would be helpful."""
        plot_keywords = ['chart', 'graph', 'plot', 'visualize', 'show', 'compare', 'trend', 'distribution', 'top']
        return any(kw in question.lower() for kw in plot_keywords)

    def _infer_plot_type(self, question: str) -> str:
        """Infer best plot type from question."""
        if 'trend' in question.lower() or 'over time' in question.lower():
            return 'line'
        elif 'distribution' in question.lower():
            return 'histogram'
        else:
            return 'bar'

_llm_instance = None

def get_llm():
    """Singleton pattern for LLM instance."""
    global _llm_instance
    if _llm_instance is None:
        _llm_instance = SimpleLLM()
    return _llm_instance

def query_llm(question: str):
    """
    Main interface for querying the LLM.
    Returns: (text_response, plot_filename)
    """
    llm = get_llm()
    return llm.query(question)
