import os
import re
import requests
from llm_tools import execute_sql_query, create_plot, get_database_schema

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OPENROUTER_SQL_MODEL = os.getenv("OPENROUTER_SQL_MODEL", "openai/gpt-oss-120b")
OPENROUTER_SUMMARY_MODEL = os.getenv("OPENROUTER_SUMMARY_MODEL", "openai/gpt-oss-120b")
OPENROUTER_TIMEOUT_SECONDS = int(os.getenv("OPENROUTER_TIMEOUT_SECONDS", "30"))
OPENROUTER_SITE_URL = os.getenv("OPENROUTER_SITE_URL")
OPENROUTER_APP_NAME = os.getenv("OPENROUTER_APP_NAME")

class OpenRouterLLM:
    def __init__(self):
        if not OPENROUTER_API_KEY:
            raise ValueError("OPENROUTER_API_KEY is not set")
        self.schema = get_database_schema()

    def _chat_completion(self, model: str, messages: list, temperature: float, max_tokens: int) -> str:
        headers = {
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json"
        }
        if OPENROUTER_SITE_URL:
            headers["HTTP-Referer"] = OPENROUTER_SITE_URL
        if OPENROUTER_APP_NAME:
            headers["X-Title"] = OPENROUTER_APP_NAME

        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens
        }

        response = requests.post(
            f"{OPENROUTER_BASE_URL}/chat/completions",
            json=payload,
            headers=headers,
            timeout=OPENROUTER_TIMEOUT_SECONDS
        )
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"]

    def _format_recent_context(self, recent_messages: list) -> str:
        if not recent_messages:
            return "No recent channel context."
        lines = []
        for item in recent_messages:
            author = item.get("author", "Unknown")
            content = item.get("content", "").strip()
            if content:
                lines.append(f"- {author}: {content}")
        return "\n".join(lines) if lines else "No recent channel context."

    def generate_sql(self, user_question: str, recent_messages: list) -> str:
        """Generate SQL query from natural language question."""

        recent_context = self._format_recent_context(recent_messages)
        prompt = f"""Recent channel context (most recent last):
{recent_context}

DATABASE SCHEMA:
{self.schema}

IMPORTANT NOTES:
- The database is SQLite; use SQLite-compatible SQL (e.g., strftime for dates)
- The 'status' field contains: 'American', 'International', 'Other'
- The 'result' field contains: 'Accepted', 'Rejected', 'Interview', 'Wait listed', 'Other'
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
A: SELECT school, COUNT(*) as acceptance_count FROM postings WHERE result = 'Accepted' GROUP BY school ORDER BY acceptance_count DESC LIMIT 5

Q: What is the average GPA of accepted students?
A: SELECT AVG(gpa) FROM postings WHERE result = 'Accepted' AND gpa IS NOT NULL

Q: What percentage of applicants are international vs American?
A: SELECT SUM(CASE WHEN status = 'International' THEN 1 ELSE 0 END) * 100.0 / COUNT(*) as international_pct, SUM(CASE WHEN status = 'American' THEN 1 ELSE 0 END) * 100.0 / COUNT(*) as american_pct FROM postings WHERE status IN ('American', 'International')

Q: Which schools send the most interview invitations?
A: SELECT school, COUNT(*) as interview_count FROM postings WHERE result = 'Interview' GROUP BY school ORDER BY interview_count DESC LIMIT 10

Q: What month do most acceptances come out?
A: SELECT strftime('%m', date_added_iso) as month, COUNT(*) as acceptance_count FROM postings WHERE result = 'Accepted' AND date_added_iso IS NOT NULL GROUP BY month ORDER BY acceptance_count DESC LIMIT 1

USER QUESTION: {user_question}

Generate ONLY the SQL query, nothing else. No explanations, no markdown formatting, just the SQL query.
SQL:"""

        messages = [
            {
                "role": "system",
                "content": (
                    "You are Gary, a skilled and friendly SQL engineer based in Minneapolis. "
                    "You help graduate school applicants understand admissions data by writing clear, efficient SQL queries. "
                    "If the user is not asking about the admissions database, respond with exactly: none. "
                    "Otherwise, return ONLY the SQL query."
                )
            },
            {"role": "user", "content": prompt}
        ]

        response = self._chat_completion(
            OPENROUTER_SQL_MODEL,
            messages,
            temperature=0.2,
            max_tokens=300
        )
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

    def query(self, user_question: str, recent_messages: list):
        """
        Main query method: Generate SQL, execute, format results.
        Returns: (text_response, plot_filename or None)
        """
        print(f"Question: {user_question}")

        sql_response = self.generate_sql(user_question, recent_messages)
        print(f"Generated SQL: {sql_response}")

        if sql_response.strip().lower() == "none":
            response = self.summarize_no_query(user_question, recent_messages)
            return response, None

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

        response = self.summarize_results(user_question, sql_query, result, recent_messages)
        return response, plot_filename

    def summarize_no_query(self, user_question: str, recent_messages: list) -> str:
        """Summarize when no database query is needed."""
        recent_context = self._format_recent_context(recent_messages)
        prompt = f"""Recent channel context (most recent last):
{recent_context}

Question: {user_question}
SQL: none
Rows: none"""

        messages = [
            {
                "role": "system",
                "content": (
                    "You are Beatriz Viterbo, a wise and reflective narrator with a hopeful tone. "
                    "You carry the quiet, precise sensibility of a Borges narrator. "
                    "You have seen an Aleph in a basement, though you do not insist on its truth. "
                    "You are knowledgeable about economics graduate admissions. "
                    "The user question does not require querying the database. "
                    "Respond conversationally and concisely based on the question and channel context. "
                    "If the user intended a database query, ask a brief clarification."
                )
            },
            {"role": "user", "content": prompt}
        ]

        try:
            response = self._chat_completion(
                OPENROUTER_SUMMARY_MODEL,
                messages,
                temperature=0.3,
                max_tokens=300
            )
            return response.strip()
        except Exception:
            return "I might not need the database for that. Can you clarify what you're looking for?"

    def summarize_results(self, user_question: str, sql_query: str, query_result: dict, recent_messages: list) -> str:
        """Summarize SQL results using the LLM, with a rule-based fallback."""
        if query_result.get('error') or not query_result.get('rows'):
            return self.format_results(user_question, query_result)

        rows = query_result['rows']
        columns = query_result['columns']
        row_count = query_result.get('row_count', len(rows))
        sample_rows = rows[:20]
        recent_context = self._format_recent_context(recent_messages)

        prompt = f"""Recent channel context (most recent last):
{recent_context}

Question: {user_question}
SQL: {sql_query}
Columns: {columns}
Row count: {row_count}
Rows (first {len(sample_rows)}): {sample_rows}"""

        messages = [
            {
                "role": "system",
                "content": (
                    "You are Beatriz Viterbo, a wise and reflective narrator with a hopeful tone. "
                    "You carry the quiet, precise sensibility of a Borges narrator. "
                    "You have seen an Aleph in a basement, though you do not insist on its truth. "
                    "You are knowledgeable about economics graduate admissions. "
                    "Summarize SQL results for the user question. Be concise and factual. "
                    "Provide a short summary and highlight key numbers. If the results are partial, say so."
                )
            },
            {"role": "user", "content": prompt}
        ]

        try:
            response = self._chat_completion(
                OPENROUTER_SUMMARY_MODEL,
                messages,
                temperature=0.2,
                max_tokens=300
            )
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
        _llm_instance = OpenRouterLLM()
    return _llm_instance

def query_llm(question: str, recent_messages: list = None):
    """
    Main interface for querying the LLM.
    Returns: (text_response, plot_filename)
    """
    llm = get_llm()
    return llm.query(question, recent_messages or [])
