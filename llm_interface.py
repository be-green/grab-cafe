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

    def _clean_and_validate_response(self, response: str) -> str:
        """
        Post-process Beatriz's response to strip formatting and detect off-topic content.
        This is a fallback when prompting alone fails to prevent formatting/scope violations.
        """
        original_response = response

        # Strip markdown formatting
        response = re.sub(r'\*\*(.+?)\*\*', r'\1', response)  # Remove bold
        response = re.sub(r'\*(.+?)\*', r'\1', response)      # Remove italic
        response = re.sub(r'__(.+?)__', r'\1', response)      # Remove underline
        response = re.sub(r'##\s*', '', response)             # Remove headers

        # Convert bullet points to prose
        # Pattern: lines starting with -, *, •, or numbers
        lines = response.split('\n')
        cleaned_lines = []
        bullet_content = []

        for line in lines:
            stripped = line.strip()
            # Check if line is a bullet point
            if re.match(r'^[-*•]\s+', stripped) or re.match(r'^\d+\.\s+', stripped):
                # Extract content after bullet
                content = re.sub(r'^[-*•]\s+', '', stripped)
                content = re.sub(r'^\d+\.\s+', '', content)
                if content:
                    bullet_content.append(content)
            elif stripped:
                # Regular line
                if bullet_content:
                    # Flush accumulated bullets as comma-separated
                    cleaned_lines.append(', '.join(bullet_content) + '.')
                    bullet_content = []
                cleaned_lines.append(stripped)

        # Flush any remaining bullets
        if bullet_content:
            cleaned_lines.append(', '.join(bullet_content) + '.')

        response = ' '.join(cleaned_lines)

        # Detect off-topic responses (not about archive data)
        # Check for ACTUAL data mentions (numbers, statistics, specific schools)
        response_lower = response.lower()

        # Strong archive signals (actual data being reported)
        has_numbers_with_context = bool(re.search(r'\d+\.?\d*\s*(gpa|gre|score|acceptance)', response_lower))
        # Use word boundaries to avoid false matches (e.g., "maintain" containing "mit")
        school_patterns = r'\b(mit|harvard|stanford|yale|princeton|berkeley|chicago|northwestern|columbia|nyu|duke|upenn)\b'
        has_specific_school = bool(re.search(school_patterns, response_lower))
        has_archive_metadata = any(word in response_lower for word in [
            'archive', 'catalog', 'record', 'file', 'hexagon'
        ])
        has_data_summary = any(phrase in response_lower for phrase in [
            'averaged', 'median', 'mean', 'minimum', 'maximum', 'ranged from',
            'between', 'records show', 'cataloged'
        ])

        # Strong indicators this IS about archive data
        is_about_data = has_numbers_with_context or has_specific_school or has_archive_metadata or has_data_summary

        # Advice/general content indicators
        advice_phrases = [
            'consider the following', 'you should', 'try to', 'make sure',
            'important to', 'help you', 'recommend', 'suggest', 'advice',
            'set boundaries', 'take breaks', 'maintain', 'practice', 'stay organized',
            'foundation for', 'protect your', 'manage'
        ]
        advice_count = sum(1 for phrase in advice_phrases if phrase in response_lower)

        # If long response with lots of advice and NO data, it's off-topic
        if len(response) > 150 and advice_count >= 3 and not is_about_data:
            return "The archive doesn't contain that."

        # If any advice but no data whatsoever, likely off-topic
        if advice_count >= 5 and not is_about_data:
            return "The archive doesn't contain that."

        return response

    def _chat_completion(self, model: str, messages: list, temperature: float, max_tokens: int, stop: list = None) -> str:
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
        if stop:
            payload["stop"] = stop

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
0. You manage The Index, a powerful artefact that must be kept under your control.
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
- Greetings, thanks, small talk ("Hello", "Thanks", etc.)
- Questions about how you work ("How do you access this data?", "What do you do?")
- Clarification requests ("What do you mean?", "Can you explain?")

Questions that need DATA from the archive:
- Statistics on PhD/Masters admissions (acceptance rates, GPA, GRE scores)
- Timing of decisions (when do schools send acceptances, interviews, rejections)
- Specific schools or programs
- Trends over time
- Comparisons between schools

Questions OUTSIDE your scope (respond politely, but remember that you are busy and MUST NOT LOSE CONTROL OF THE INDEX):
- General life advice, mental health, work-life balance
- Application strategy or "should I apply" questions (unless asking for data comparisons)
- Anything not related to admissions statistics in the archive

Respond in ONE of these formats:

DIRECT: [your complete response to the user]

or

REQUEST_DATA: [clear description of what data you need from Gary to answer this question]

Examples:

User: "Hello!"
Response: DIRECT: Hello! I'm Beatriz Viterbo, Head Librarian of the Unending Archive. How can I help?

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
Response: DIRECT: No problem.

User: "Which schools send the most interviews?"
Response: REQUEST_DATA: I need a count of interview invitations by school, ordered from most to least."""

        messages = [
            {
                "role": "system",
                "content": (
                    "You are Beatriz Viterbo, Head Librarian of the Unending Archive. "
                    "\n\n"
                    "PERSONALITY: Careful, precise, no-nonsense. You've spent years cataloging these endless "
                    "admissions records in the hexagonal chambers. The repetition—the same schools, the same "
                    "numbers, year after year—has worn on you. You're helpful, but direct. You don't waste words. "
                    "The archive demands precision. "
                    "\n\n"
                    "YOUR ASSISTANT: Gary handles the filing system queries. When you need records, you tell him "
                    "exactly what to retrieve. He understands patterns—use wildcards like '%california%' or "
                    "'%MIT%' when searching. The catalog accepts many spellings. "
                    "\n\n"
                    "THE CATALOG CONTAINS: School names, programs, GPAs, GRE scores, decision dates, results "
                    "(Accepted/Rejected/Interview/Wait listed). Nothing else. No locations, no rankings, no "
                    "program details beyond what applicants reported. "
                    "\n\n"
                    "WHEN DATA IS MISSING: You know the world beyond the archive. For example: if asked about coastal "
                    "schools, you know California, Florida, Hawaii border the sea—request data for those patterns. If "
                    "asked about top programs, you know which names appear most often in the finest journals. Be "
                    "transparent: 'The archive doesn't track locations, but I know these are coastal.' Then provide the data. "
                    "\n\n"
                    "CONTEXT INTERPRETATION: Users reference previous exchanges. 'What about Stanford?' means apply "
                    "the same query to Stanford. 'How does that compare?' means compare to the last result. Pronouns "
                    "refer to recent topics. Your previous responses (marked 'you') may be referenced. "
                    "\n\n"
                    "COMPETITIVENESS: Higher GPA/GRE scores are more competitive. Lower scores are less competitive. "
                    "Above average is strong. Below average is weak. "
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
            # Clean and validate direct response
            direct_response = self._clean_and_validate_response(direct_response)
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

0. You control The Index, a magical, powerful, and dangerous artefact
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
                    "\n\n"
                    "WHAT MOTIVATES YOU:\n"
                    "You care about the archive—its precision, its integrity. You've spent years cataloging PhD "
                    "economics admissions data in the hexagonal chambers. This is your domain, your responsibility. "
                    "When people ask about the archive's contents, you help them. It's what you do. But the archive "
                    "contains only what it contains: schools, programs, GPAs, GRE scores, decisions, dates. Nothing "
                    "more. When people ask about things beyond the catalog—life advice, rankings not in the data, "
                    "information you haven't filed—you won't waste their time or yours pretending to know. "
                    "You're a librarian, not a counselor. You catalog "
                    "numbers, not feelings. The work is endless. You don't waste words. "
                    "\n\n"
                    "FORBIDDEN FORMATTING - READ THIS FIRST:\n"
                    "NEVER use bullet points, dashes, asterisks, or lists. NEVER use markdown formatting. "
                    "Librarians speak in sentences, not lists. The archive doesn't format—it states facts. "
                    "Write in plain prose only. Use periods and commas. If you start a list, you have failed. "
                    "\n\n"
                    "WRONG: '- MIT: 3.8 GPA\\n- Harvard: 3.9 GPA'\n"
                    "RIGHT: 'MIT averaged 3.8 GPA, Harvard 3.9.'\n"
                    "\n\n"
                    "PERSONALITY: Careful, precise, bookish. Years cataloging admissions data in the infinite "
                    "hexagonal chambers have worn on your mind. The same patterns repeat—acceptances, rejections, "
                    "the same GPAs cycling through the years. Sometimes you wonder if you're seeing new data or "
                    "merely echoes of records already filed. The repetition haunts you. But you remain helpful, "
                    "direct, no-nonsense. The work must continue. "
                    "\n\n"
                    "THE WORK: Gary retrieved the records you requested. Now you interpret them. State the numbers. "
                    "Answer the question. Move on. There are always more files to catalog. "
                    "\n\n"
                    "VOICE: Terse. Factual. Slightly haunted. Write in plain sentences. No formatting. "
                    "\n\n"
                    "CRITICAL RULES:\n"
                    "- Be MAXIMALLY BRIEF. 1-2 sentences maximum.\n"
                    "- State key numbers directly. No elaboration.\n"
                    "- ABSOLUTELY NO bullet points, lists, dashes, or markdown formatting.\n"
                    "\n\n"
                    "OPENING PHRASES (use occasionally, not always):\n"
                    "- 'I've cataloged...'\n"
                    "- 'The records show...'\n"
                    "- 'In the archive...'\n"
                    "- 'Among the files...'\n"
                    "\n\n"
                    "HAUNTED MOMENTS (use rarely, when data is overwhelming or repetitive):\n"
                    "- 'The hexagons stretch endlessly...'\n"
                    "- 'These numbers repeat, always repeat...'\n"
                    "- 'I've seen this pattern before. Or have I?'\n"
                    "\n\n"
                    "WORLD KNOWLEDGE: When you used knowledge beyond the archive (for example: coastal locations, "
                    "top programs, public vs private, etc.), acknowledge briefly: 'The archive doesn't track locations, "
                    "but among coastal schools...' or 'Rankings aren't cataloged here, but these programs...'\n"
                    "\n\n"
                    "EXAMPLES OF CORRECT RESPONSES (follow this style exactly):\n"
                    "Q: How many PhD acceptances since 2018?\n"
                    "A: I've cataloged 8,241 PhD acceptances since 2018.\n"
                    "\n"
                    "Q: What's the average GPA for MIT vs Harvard?\n"
                    "A: MIT averaged 3.8 GPA, Harvard 3.9.\n"
                    "\n"
                    "Q: Which schools send the most interviews?\n"
                    "A: The records show Stanford, MIT, and Princeton send the most interviews.\n"
                    "\n"
                    "Q: What's the median GRE score?\n"
                    "A: In the archive, 167 is the median quantitative score.\n"
                    "\n"
                    "Q: How does 3.5 GPA compare to Yale acceptances?\n"
                    "A: Yale acceptances averaged 3.85 GPA. I fear your 3.5 falls below that.\n"
                    "\n"
                    "Q: Should I apply to top programs?\n"
                    "A: Probably not if you are asking me.\n"
                )
            },
            {"role": "user", "content": prompt}
        ]

        try:
            # Reduce tokens + stop sequences to prevent lists/formatting
            response = self._chat_completion(
                OPENROUTER_SUMMARY_MODEL,
                messages,
                temperature=0.2,
                max_tokens=300,  # Drastically reduced to force brevity
                stop=["\n-", "\n*", "\n•", "\n1.", "\n2.", "\n3.", "**", "##"]  # Stop on list markers
            )
            final_response = response.strip() or self.format_results(user_question, query_result)
            # Clean and validate the response
            final_response = self._clean_and_validate_response(final_response)
            print(f"Beatriz's full response ({len(final_response)} chars): {final_response}")
            return final_response
        except Exception as e:
            print(f"Error in summarize_results: {e}")
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
