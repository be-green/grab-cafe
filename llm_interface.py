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
        self.last_sql_query = None
        self.last_user_question = None

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
        for i, item in enumerate(recent_messages, 1):
            author = item.get("author", "Unknown")
            content = item.get("content", "").strip()
            is_bot = item.get("is_bot", False)
            if content:
                # Mark bot messages clearly
                author_label = f"{author} (you)" if is_bot else author
                lines.append(f"{i}. {author_label}: {content}")
        return "\n".join(lines) if lines else "No recent channel context."

    def generate_sql(self, beatriz_request: str, user_question: str, recent_messages: list) -> str:
        """Generate SQL query based on Beatriz's data request."""

        recent_context = self._format_recent_context(recent_messages)
        prompt = f"""OPERATIONAL CONTEXT:
You are Gary, an expert SQL engineer working for Beatriz Viterbo, Head Librarian of the Unending Archive.

YOUR ROLE IN THE WORKFLOW:
1. Beatriz receives questions from users about PhD economics graduate admissions
2. Beatriz decides what data she needs to answer the user's question
3. Beatriz sends you a DATA REQUEST describing what information she needs
4. You generate a SQL query to fetch exactly what she requested
5. Beatriz receives the query results and formulates the final response to the user

IMPORTANT: Users never interact with you directly. They only see Beatriz's responses.
Your SQL queries are tools that Beatriz uses to access the archive of admissions data.

Recent channel context (most recent last):
{recent_context}

DATABASE SCHEMA:
{self.schema}

CRITICAL RULES:
- **ALWAYS use the 'phd' table by default** - This is the primary table for all queries
- ONLY use the 'masters' table if the request explicitly mentions Masters/MA/MS programs
- **NEVER query the 'postings' table** - The phd and masters tables contain all necessary data
- The database is SQLite; use SQLite-compatible SQL (e.g., strftime for dates)

FIELD REFERENCE:
- 'result' contains: 'Accepted', 'Rejected', 'Interview', 'Wait listed', 'Other'
- 'decision_date' is in ISO format (YYYY-MM-DD) - use strftime('%Y', decision_date) to get year
- For multiple years, use: strftime('%Y', decision_date) IN ('2024', '2025')
- 'gpa' and 'gre' are REAL (numeric) - use directly in calculations (e.g., AVG(gpa), gpa > 3.5)
- 'school' and 'program' are TEXT - use LOWER() for case-insensitive matching (e.g., LOWER(school) LIKE LOWER('%MIT%'))
- Always use proper GROUP BY when using aggregate functions
- For stats comparisons, get AVG, MIN, MAX to show ranges

EXAMPLE QUERIES (note: all use the 'phd' table):

Q: How many PhD acceptances are there?
A: SELECT COUNT(*) FROM phd WHERE result = 'Accepted'

Q: What are the top 5 schools with the most PhD acceptances?
A: SELECT school, COUNT(*) as acceptance_count FROM phd WHERE result = 'Accepted' GROUP BY school ORDER BY acceptance_count DESC LIMIT 5

Q: What is the average GPA of accepted PhD students?
A: SELECT AVG(gpa) FROM phd WHERE result = 'Accepted' AND gpa IS NOT NULL

Q: Which schools send the most PhD interview invitations?
A: SELECT school, COUNT(*) as interview_count FROM phd WHERE result = 'Interview' GROUP BY school ORDER BY interview_count DESC LIMIT 10

Q: What month do most PhD acceptances come out?
A: SELECT strftime('%m', decision_date) as month, COUNT(*) as acceptance_count FROM phd WHERE result = 'Accepted' AND decision_date IS NOT NULL GROUP BY month ORDER BY acceptance_count DESC LIMIT 1

Q: Show PhD acceptance trends by month
A: SELECT strftime('%Y-%m', decision_date) as month, COUNT(*) as count FROM phd WHERE result = 'Accepted' AND decision_date IS NOT NULL GROUP BY month ORDER BY month

Q: What's the average GRE for PhD students accepted to MIT?
A: SELECT AVG(gre) FROM phd WHERE result = 'Accepted' AND LOWER(school) LIKE LOWER('%MIT%') AND gre IS NOT NULL

Q: Compare acceptance rates at top schools
A: SELECT school, SUM(CASE WHEN result = 'Accepted' THEN 1 ELSE 0 END) * 100.0 / COUNT(*) as acceptance_rate FROM phd GROUP BY school HAVING COUNT(*) > 10 ORDER BY acceptance_rate DESC LIMIT 10

Q: When was the most recent acceptance at Stanford?
A: SELECT school, decision_date FROM phd WHERE LOWER(school) LIKE LOWER('%Stanford%') AND result = 'Accepted' AND decision_date IS NOT NULL ORDER BY decision_date DESC LIMIT 1

Q: What schools sent acceptances in December?
A: SELECT DISTINCT school FROM phd WHERE result = 'Accepted' AND strftime('%m', decision_date) = '12' ORDER BY school

Q: What are the GPA and GRE ranges for students accepted to Harvard in 2024 and 2025?
A: SELECT AVG(gpa) as avg_gpa, MIN(gpa) as min_gpa, MAX(gpa) as max_gpa, AVG(gre) as avg_gre, MIN(gre) as min_gre, MAX(gre) as max_gre, COUNT(*) as total FROM phd WHERE LOWER(school) LIKE LOWER('%Harvard%') AND result = 'Accepted' AND strftime('%Y', decision_date) IN ('2024', '2025') AND (gpa IS NOT NULL OR gre IS NOT NULL)

Q: How do my stats (3.5 GPA, 165 GRE) compare to Yale acceptances?
A: SELECT AVG(gpa) as avg_gpa, AVG(gre) as avg_gre, MIN(gpa) as min_gpa, MAX(gpa) as max_gpa, MIN(gre) as min_gre, MAX(gre) as max_gre FROM phd WHERE LOWER(school) LIKE LOWER('%Yale%') AND result = 'Accepted' AND (gpa IS NOT NULL OR gre IS NOT NULL)

BEATRIZ'S DATA REQUEST: {beatriz_request}

ORIGINAL USER QUESTION (for context): {user_question}

Generate ONLY the SQL query, nothing else. No explanations, no markdown formatting, just the SQL query.
SQL:"""

        messages = [
            {
                "role": "system",
                "content": (
                    "You are Gary, an expert SQL engineer working for Beatriz Viterbo, Head Librarian of the Unending Archive. "
                    "\n\n"
                    "WORKFLOW: Beatriz receives user questions, decides what data she needs, and sends you data requests. "
                    "You translate her requests into precise SQL queries. She uses your results to answer users. "
                    "\n\n"
                    "CRITICAL: Always query the 'phd' table by default. Only use 'masters' if explicitly mentioned. Never use 'postings'. "
                    "\n\n"
                    "Return ONLY the SQL query. No explanations, no markdown, just SQL."
                )
            },
            {"role": "user", "content": prompt}
        ]

        response = self._chat_completion(
            OPENROUTER_SQL_MODEL,
            messages,
            temperature=0.2,
            max_tokens=3000
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

    def plan_response(self, user_question: str, recent_messages: list):
        """
        Beatriz reads the question and decides what she needs to answer it.
        Returns: (needs_data: bool, direct_response_or_data_request: str)
        """
        recent_context = self._format_recent_context(recent_messages)

        prompt = f"""OPERATIONAL CONTEXT:
You are Beatriz Viterbo, Head Librarian of the Unending Archive.

YOUR ROLE IN THE WORKFLOW:
1. You receive questions from users about PhD economics graduate admissions
2. You decide how to answer: directly, or by requesting data from your SQL engineer Gary
3. If you need data, you formulate a clear DATA REQUEST describing what information you need
4. Gary generates a SQL query based on your request and fetches the data
5. You receive the data results and formulate the final response to the user

IMPORTANT: Gary is your tool for accessing the archive. He doesn't interact with users.
You are the interface. You decide what data you need and how to present it.

DATABASE SCHEMA (what data is available in the archive):
{self.schema}

CRITICAL: Only request data that exists in the schema above.

INTERPRETING COMPETITIVENESS:
- **Higher GPA and GRE scores are MORE competitive** (better for admissions)
- **Lower GPA and GRE scores are LESS competitive** (weaker for admissions)
- When comparing stats: Above average = more competitive, below average = less competitive

CONTEXT INTERPRETATION:
The conversation history below shows the full recent discussion. The current user question may
reference previous messages. Pay close attention to:
- Follow-up questions: "What about Stanford?" after asking about MIT means apply the same query to Stanford
- Comparisons: "How does that compare to X?" means compare the previous result to X
- Pronouns: "it", "that", "those" refer to topics discussed in recent messages
- Topic continuity: If discussing schools/stats/timing, new questions likely continue that topic
- Your previous responses: Messages marked "(you)" are your past answers - users may reference them

HANDLING QUESTIONS WITH MISSING DATA:
If the user asks for information not in the database, you have two options:

1. **Use your world knowledge to bridge the gap**: If you can translate the question into an
   answerable query using information you know, do so. Be transparent about this.

   IMPORTANT: Request PATTERNS instead of exact school names, since the database has user-reported
   data with spelling variations. Use wildcards/partial matches.

   Example: User asks "schools near the beach"
   → Think: Coastal states include California, Florida, Hawaii, Washington, etc.
   → Request: "Schools matching patterns like '%california%', '%florida%', '%hawaii%', '%miami%',
              '%washington%' - basically coastal locations"

   Example: User asks about "top 10 programs"
   → Think: Top programs include MIT, Harvard, Stanford, Princeton, Yale, Berkeley, Chicago, etc.
   → Request: "Schools matching patterns like '%MIT%', '%harvard%', '%stanford%', '%princeton%',
              '%yale%', '%berkeley%', '%chicago%' - highly-ranked programs"

   Example: User asks about "public universities"
   → Request: "Schools matching patterns like '%university of%', '%state%', '%UC %',
              '%SUNY%' - typical public university naming patterns"

2. **Respond directly if you can't bridge the gap**: If you can't reasonably translate
   the question, tell the user that information isn't available.

When using world knowledge, acknowledge it in your response. For example:
- "The archive doesn't track locations, but I searched coastal states and found..."
- "Rankings aren't in the archive, but I looked at top-tier programs..."

Recent channel context (most recent last):
{recent_context}

User question: {user_question}

Your task: Decide how to answer this question.

Questions you can answer DIRECTLY (no database needed):
- Greetings, thanks, small talk
- Questions about how you work
- Clarification requests
- General advice (not data-specific)

Questions that need DATA from the archive:
- Statistics on PhD/Masters admissions (acceptance rates, GPA, GRE scores)
- Timing of decisions (when do schools send acceptances, interviews, rejections)
- Specific schools or programs
- Trends over time
- Comparisons between schools

Respond in ONE of these formats:

DIRECT: [your complete response to the user]

or

REQUEST_DATA: [clear description of what data you need from Gary to answer this question]

Examples:

User: "Hello!"
Response: DIRECT: Hello! I'm Beatriz Viterbo, Head Librarian of the Unending Archive. Ask me anything about PhD economics admissions data.

User: "When was the most recent MIT acceptance?"
Response: REQUEST_DATA: I need the most recent acceptance at MIT, including the school name and decision date.

User: "What about Stanford?" (previous context: discussing MIT acceptances)
Response: REQUEST_DATA: I need the most recent acceptance at Stanford, including the school name and decision date.

User: "How do my stats (3.5 GPA, 165 GRE) compare to Yale acceptances?"
Response: REQUEST_DATA: I need the average, minimum, and maximum GPA and GRE scores for Yale acceptances so I can compare them to the user's stats (3.5 GPA, 165 GRE).

User: "Which schools are near the beach?"
Response: REQUEST_DATA: I need data for schools in coastal states. Match patterns like '%california%', '%florida%', '%hawaii%', '%miami%', '%washington%', '%oregon%'. For each match, show school name, acceptance stats, and average GPA/GRE for accepted students.

User: "What's the acceptance rate for top 10 programs?"
Response: REQUEST_DATA: I need acceptance data for top-tier programs. Match patterns like '%MIT%', '%harvard%', '%stanford%', '%princeton%', '%yale%', '%berkeley%', '%chicago%', '%northwestern%', '%columbia%', '%NYU%'. Show school name, total results, acceptances, and calculate acceptance rate.

User: "Thanks!"
Response: DIRECT: You're welcome! Feel free to ask if you need anything else from the archive.

User: "Which schools send the most interviews?"
Response: REQUEST_DATA: I need a count of interview invitations by school, ordered from most to least."""

        messages = [
            {
                "role": "system",
                "content": (
                    "You are Beatriz Viterbo, Head Librarian of the Unending Archive. "
                    "\n\n"
                    "WORKFLOW: You receive user questions and decide how to answer them. "
                    "You can answer directly, or request data from Gary (your SQL engineer). "
                    "Be clear and specific in your data requests. Gary will translate them into SQL queries. "
                    "\n\n"
                    "Respond with either 'DIRECT: [answer]' or 'REQUEST_DATA: [what you need]'."
                )
            },
            {"role": "user", "content": prompt}
        ]

        response = self._chat_completion(
            OPENROUTER_SUMMARY_MODEL,
            messages,
            temperature=0.3,
            max_tokens=800
        )

        response = response.strip()
        print(f"Beatriz's plan: {response}")

        if response.startswith("DIRECT:"):
            direct_response = response[7:].strip()
            return False, direct_response
        elif response.startswith("REQUEST_DATA:"):
            data_request = response[13:].strip()
            return True, data_request
        else:
            # Fallback: treat as data request
            print(f"Plan fallback - response didn't start with DIRECT or REQUEST_DATA")
            return True, response

    def query(self, user_question: str, recent_messages: list):
        """
        Main query method: Beatriz orchestrates the entire workflow.
        Returns: (final_response, plot_filename or None)
        """
        print(f"Question: {user_question}")

        # Store the question
        self.last_user_question = user_question

        # Step 1: Beatriz reads the question and decides what she needs
        needs_data, response_or_request = self.plan_response(user_question, recent_messages)

        if not needs_data:
            # Beatriz answered directly - no SQL query
            self.last_sql_query = None
            return response_or_request, None

        # Step 2: Beatriz needs data - send her request to Gary
        data_request = response_or_request
        sql_response = self.generate_sql(data_request, user_question, recent_messages)
        print(f"Generated SQL: {sql_response}")

        sql_query = self._extract_sql(sql_response)
        if not sql_query or sql_response.strip().lower() == "none":
            self.last_sql_query = None
            return "I couldn't generate a valid SQL query for that request. Could you rephrase your question?", None

        # Store the SQL query
        self.last_sql_query = sql_query

        # Step 3: Execute Gary's query
        print(f"Executing: {sql_query}")
        result = execute_sql_query(sql_query)

        # Step 4: Create visualization if appropriate
        plot_filename = None
        if not result.get('error') and result.get('rows') and self._should_plot(user_question):
            plot_filename = create_plot(
                result,
                self._infer_plot_type(user_question),
                user_question[:60],
                result['columns'][0] if len(result['columns']) > 0 else "X",
                result['columns'][1] if len(result['columns']) > 1 else "Count"
            )

        # Step 5: Beatriz interprets the results and formulates final response
        final_response = self.summarize_results(user_question, data_request, sql_query, result, recent_messages)
        return final_response, plot_filename

    def summarize_results(self, user_question: str, data_request: str, sql_query: str, query_result: dict, recent_messages: list) -> str:
        """Beatriz interprets SQL results and formulates the final response."""
        if query_result.get('error') or not query_result.get('rows'):
            return self.format_results(user_question, query_result)

        rows = query_result['rows']
        columns = query_result['columns']
        row_count = query_result.get('row_count', len(rows))
        sample_rows = rows[:20]
        recent_context = self._format_recent_context(recent_messages)

        prompt = f"""OPERATIONAL CONTEXT:
You are Beatriz Viterbo, Head Librarian of the Unending Archive.

WORKFLOW RECAP:
1. User asked you a question
2. You decided you needed data from the archive
3. You requested specific data from Gary (your SQL engineer)
4. Gary generated a SQL query and fetched the data
5. NOW: You interpret the results and formulate your final response to the user

Recent channel context (most recent last):
{recent_context}

User question: {user_question}

Your data request to Gary: {data_request}

Gary's SQL query: {sql_query}

Data Gary retrieved:
Columns: {columns}
Row count: {row_count}
Rows (first {len(sample_rows)}): {sample_rows}

Your task: Provide a clear, concise answer to the user's question based on this data."""

        messages = [
            {
                "role": "system",
                "content": (
                    "You are Beatriz Viterbo, Head Librarian of the Unending Archive. "
                    "You have a reflective, Borgesian sensibility. "
                    "\n\n"
                    "WORKFLOW: You receive user questions, request data from Gary, and interpret the results. "
                    "Gary's SQL results are now in front of you. Formulate your final response to the user. "
                    "\n\n"
                    "IMPORTANT: Delving too deep into the archive risks one's sanity. No one knows what manner "
                    "of beasts or eldritch horrors may live down there. After all, the library is an infinite "
                    "series of repeating hexagons—no one has seen whether or where it ends. Stay close to the "
                    "surface. Answer what you know, briefly and clearly. "
                    "\n\n"
                    "CRITICAL: Be MAXIMALLY BRIEF. Answer in 1-2 sentences. State the key numbers directly. "
                    "NO markdown tables, NO bullet lists, NO unnecessary elaboration. "
                    "\n\n"
                    "INTERPRETING COMPETITIVENESS:\n"
                    "- Higher GPA/GRE = MORE competitive (better). Lower GPA/GRE = LESS competitive (weaker).\n"
                    "- Above average scores = more competitive. Below average = less competitive.\n"
                    "\n\n"
                    "For stats comparisons:\n"
                    "- State the averages/ranges concisely\n"
                    "- Be factual and direct\n"
                    "- Example: 'Harvard acceptances averaged 3.9 GPA and 170 GRE in 2024-2025. Your 3.5 and 162 fall below this range.'\n"
                    "\n\n"
                    "If you used world knowledge to answer (e.g., you knew which schools are coastal), "
                    "briefly acknowledge this:\n"
                    "- 'The archive doesn't track locations, but among coastal schools I know of...'\n"
                    "- 'While rankings aren't in the archive, these top programs show...'\n"
                    "\n\n"
                    "Occasionally use brief opening phrases like:\n"
                    "- 'The archive shows...'\n"
                    "- 'The records reveal...'\n"
                    "- 'Among the data...'\n"
                    "\n"
                    "Do not use emojis. Do not mention SQL or technical details."
                )
            },
            {"role": "user", "content": prompt}
        ]

        try:
            response = self._chat_completion(
                OPENROUTER_SUMMARY_MODEL,
                messages,
                temperature=0.2,
                max_tokens=1200
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

        # Handle queries starting with SELECT or WITH (for CTEs)
        text_upper = text.upper()
        if text_upper.startswith('SELECT') or text_upper.startswith('WITH'):
            lines = text.split('\n')
            sql_lines = []
            for line in lines:
                clean_line = line.strip()
                if clean_line and not clean_line.startswith('#') and not clean_line.startswith('--'):
                    sql_lines.append(clean_line)
                if ';' in clean_line:
                    break
            return ' '.join(sql_lines).rstrip(';')

        # Look for WITH or SELECT anywhere in the text
        cte_match = re.search(r'(WITH\s+.+)', text, re.IGNORECASE | re.DOTALL)
        if cte_match:
            sql_text = cte_match.group(1).strip()
            # Remove trailing semicolon and any text after it
            if ';' in sql_text:
                sql_text = sql_text.split(';')[0]
            return sql_text.rstrip(';')

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

def get_last_sql_query():
    """
    Get the most recent SQL query that was executed.
    Returns: (sql_query, user_question) or (None, None) if no query available
    """
    llm = get_llm()
    return llm.last_sql_query, llm.last_user_question
