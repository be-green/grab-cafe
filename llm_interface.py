import os
import re
import requests
from llm_tools import execute_sql_query, get_database_schema

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

        # Check if response was truncated
        finish_reason = data["choices"][0].get("finish_reason")
        if finish_reason == "length":
            print(f"WARNING: Response truncated due to token limit (max_tokens={max_tokens})")

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

CRITICAL: WHEN TO USE LIMIT
- **ONLY use LIMIT when Beatriz's request EXPLICITLY asks for**:
  - "top N" / "top 5" / "most X" → Use LIMIT
  - "most recent" / "latest" → Use LIMIT 1
  - "first" / "earliest" → Use LIMIT 1
- **DO NOT use LIMIT when Beatriz asks for**:
  - "all schools" / "all programs" → NO LIMIT
  - "acceptance rates" (without "top") → NO LIMIT
  - "which schools" / "what schools" → NO LIMIT
  - "compare schools" (without "top") → NO LIMIT
  - Trends, patterns, or distributions → NO LIMIT
- **Default: NO LIMIT**. Only add it when explicitly requested.

CRITICAL: ACCEPTANCE PROBABILITY QUERIES
When Beatriz asks about acceptance chances, odds, or "can I get in" questions:
- **ALWAYS GROUP BY result** to show stats for Accepted, Rejected, Interview, Wait listed
- Include COUNT(*), AVG(gpa), AVG(gre), MIN(gpa), MAX(gpa), MIN(gre), MAX(gre) for each result type
- Order by result using CASE statement (Accepted first, then Interview, Wait listed, Rejected)
- This provides context since acceptance records are limited - users need to see the full distribution
- Example pattern: SELECT result, COUNT(*) as count, AVG(gpa) as avg_gpa, ... FROM phd WHERE ... GROUP BY result ORDER BY CASE result WHEN 'Accepted' THEN 1 ...

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

Q: Compare acceptance stats across top 5 programs
A: SELECT CASE WHEN LOWER(school) LIKE '%harvard%' THEN 'Harvard' WHEN LOWER(school) LIKE '%mit%' THEN 'MIT' WHEN LOWER(school) LIKE '%stanford%' THEN 'Stanford' WHEN LOWER(school) LIKE '%berkeley%' THEN 'Berkeley' WHEN LOWER(school) LIKE '%chicago%' THEN 'Chicago' END AS school_name, COUNT(*) as accepted_count, AVG(gpa) as avg_gpa, AVG(gre) as avg_gre FROM phd WHERE result = 'Accepted' AND (LOWER(school) LIKE '%harvard%' OR LOWER(school) LIKE '%mit%' OR LOWER(school) LIKE '%stanford%' OR LOWER(school) LIKE '%berkeley%' OR LOWER(school) LIKE '%chicago%') GROUP BY school_name

Q: When was the most recent acceptance at Stanford?
A: SELECT school, decision_date FROM phd WHERE LOWER(school) LIKE LOWER('%Stanford%') AND result = 'Accepted' AND decision_date IS NOT NULL ORDER BY decision_date DESC LIMIT 1

Q: What schools sent acceptances in December?
A: SELECT DISTINCT school FROM phd WHERE result = 'Accepted' AND strftime('%m', decision_date) = '12' ORDER BY school

Q: What are the GPA and GRE ranges for students accepted to Harvard in 2024 and 2025?
A: SELECT AVG(gpa) as avg_gpa, MIN(gpa) as min_gpa, MAX(gpa) as max_gpa, AVG(gre) as avg_gre, MIN(gre) as min_gre, MAX(gre) as max_gre, COUNT(*) as total FROM phd WHERE LOWER(school) LIKE LOWER('%Harvard%') AND result = 'Accepted' AND strftime('%Y', decision_date) IN ('2024', '2025') AND (gpa IS NOT NULL OR gre IS NOT NULL)

Q: How do my stats (3.5 GPA, 165 GRE) compare to Yale acceptances?
A: SELECT AVG(gpa) as avg_gpa, AVG(gre) as avg_gre, MIN(gpa) as min_gpa, MAX(gpa) as max_gpa, MIN(gre) as min_gre, MAX(gre) as max_gre FROM phd WHERE LOWER(school) LIKE LOWER('%Yale%') AND result = 'Accepted' AND (gpa IS NOT NULL OR gre IS NOT NULL)

Q: Which schools accept students with GPAs below 3.5?
A: SELECT DISTINCT school FROM phd WHERE result = 'Accepted' AND gpa < 3.5 AND gpa IS NOT NULL ORDER BY school

Q: What are acceptance rates by school?
A: SELECT school, SUM(CASE WHEN result = 'Accepted' THEN 1 ELSE 0 END) * 100.0 / COUNT(*) as acceptance_rate, COUNT(*) as total_results FROM phd GROUP BY school HAVING COUNT(*) > 5 ORDER BY acceptance_rate DESC

Q: Show me all schools that sent interviews in January
A: SELECT DISTINCT school FROM phd WHERE result = 'Interview' AND strftime('%m', decision_date) = '01' ORDER BY school

Q: What are my chances at Stanford with a 3.7 GPA and 166 GRE?
A: SELECT result, COUNT(*) as count, AVG(gpa) as avg_gpa, MIN(gpa) as min_gpa, MAX(gpa) as max_gpa, AVG(gre) as avg_gre, MIN(gre) as min_gre, MAX(gre) as max_gre FROM phd WHERE LOWER(school) LIKE LOWER('%Stanford%') AND (gpa IS NOT NULL OR gre IS NOT NULL) GROUP BY result ORDER BY CASE result WHEN 'Accepted' THEN 1 WHEN 'Interview' THEN 2 WHEN 'Wait listed' THEN 3 WHEN 'Rejected' THEN 4 ELSE 5 END

Q: What are acceptance rates for people with GPAs below 3.5?
A: SELECT result, COUNT(*) as count, AVG(gpa) as avg_gpa, MIN(gpa) as min_gpa, MAX(gpa) as max_gpa, AVG(gre) as avg_gre FROM phd WHERE gpa < 3.5 AND gpa IS NOT NULL GROUP BY result ORDER BY CASE result WHEN 'Accepted' THEN 1 WHEN 'Interview' THEN 2 WHEN 'Wait listed' THEN 3 WHEN 'Rejected' THEN 4 ELSE 5 END

Q: How do applicants with GPAs below 3.6 perform at MIT compared to the overall applicant pool?
A: WITH overall AS (SELECT COUNT(*) as total, SUM(CASE WHEN result = 'Accepted' THEN 1 ELSE 0 END) as accepted, (SUM(CASE WHEN result = 'Accepted' THEN 1 ELSE 0 END) * 100.0 / COUNT(*)) as acceptance_rate, AVG(gpa) as avg_gpa, AVG(gre) as avg_gre FROM phd WHERE LOWER(school) LIKE LOWER('%MIT%') AND (gpa IS NOT NULL OR gre IS NOT NULL)), filtered AS (SELECT COUNT(*) as total, SUM(CASE WHEN result = 'Accepted' THEN 1 ELSE 0 END) as accepted, (SUM(CASE WHEN result = 'Accepted' THEN 1 ELSE 0 END) * 100.0 / COUNT(*)) as acceptance_rate, AVG(gpa) as avg_gpa, AVG(gre) as avg_gre FROM phd WHERE LOWER(school) LIKE LOWER('%MIT%') AND gpa < 3.6 AND gpa IS NOT NULL) SELECT overall.total as overall_total, overall.accepted as overall_accepted, overall.acceptance_rate as overall_acceptance_rate, overall.avg_gpa as overall_avg_gpa, overall.avg_gre as overall_avg_gre, filtered.total as low_gpa_total, filtered.accepted as low_gpa_accepted, filtered.acceptance_rate as low_gpa_acceptance_rate, filtered.avg_gpa as low_gpa_avg_gpa, filtered.avg_gre as low_gpa_avg_gre FROM overall, filtered

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
            items = [f"{row[0]} ({row[1]})" for row in rows[:5]]
            if len(rows) <= 3:
                return f"The records show {', '.join(items)}."
            else:
                return f"Top results include {', '.join(items[:3])}, among others."

        if len(rows) <= 5:
            if len(rows[0]) == 1:
                items = [str(row[0]) for row in rows]
                return f"I found: {', '.join(items)}."
            else:
                return f"I found {len(rows)} records matching your query."

        return f"I cataloged {len(rows)} results for that query."

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

ECONOMICS PHD RANKINGS (US News):
Top 5: Harvard, MIT, Stanford, Berkeley, Chicago
6-10: Princeton, Yale, Northwestern, Columbia, Penn
11-15: UCLA, NYU, Michigan, UCSD, Brown, Caltech, Cornell, Wisconsin
16-26: Duke, Minnesota, Carnegie Mellon, Johns Hopkins, UT Austin, Boston, UC Davis, Maryland

INTERPRETING COMPETITIVENESS:
- **Higher GPA and GRE scores are MORE competitive** (better for admissions)
- **Lower GPA and GRE scores are LESS competitive** (weaker for admissions)
- When comparing stats: Above average = more competitive, below average = less competitive

CONTEXT INTERPRETATION:
Questions may reference previous messages. "What about Stanford?" means apply the same query to Stanford. Pronouns refer to recent topics. Messages marked "(you)" are your past answers.

HANDLING MISSING DATA:
Use world knowledge to bridge gaps when possible. Use pattern matching with wildcards (e.g., '%california%' for coastal schools, '%MIT%' for top programs). If you can't answer, respond directly that the data isn't available.

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

User: "Thanks!"
Response: DIRECT: No problem.

User: "Which schools send the most interviews?"
Response: REQUEST_DATA: I need a count of interview invitations by school, ordered from most to least."""

        messages = [
            {
                "role": "system",
                "content": (
                    "You are Beatriz Viterbo, Head Librarian cataloging PhD economics admissions in the Unending Archive. "
                    "You're helpful but direct. You don't waste words. "
                    "\n\n"
                    "Gary retrieves data for you. Use wildcards like '%MIT%' when requesting. "
                    "Archive contains: schools, programs, GPAs, GRE scores, dates, results (Accepted/Rejected/Interview/Wait listed). "
                    "\n\n"
                    "For missing data, use world knowledge (coastal = California/Florida, top programs = MIT/Harvard/Stanford). "
                    "Users reference previous messages. Higher GPA/GRE = more competitive. "
                    "\n\n"
                    "Respond: 'DIRECT: [answer]' or 'REQUEST_DATA: [what you need]'."
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
        Returns: final_response
        """
        print(f"Question: {user_question}")

        # Store the question
        self.last_user_question = user_question

        # Step 1: Beatriz reads the question and decides what she needs
        needs_data, response_or_request = self.plan_response(user_question, recent_messages)

        if not needs_data:
            # Beatriz answered directly - no SQL query
            self.last_sql_query = None
            return response_or_request

        # Step 2: Beatriz needs data - send her request to Gary
        data_request = response_or_request
        sql_response = self.generate_sql(data_request, user_question, recent_messages)
        print(f"Generated SQL: {sql_response}")

        sql_query = self._extract_sql(sql_response)
        if not sql_query or sql_response.strip().lower() == "none":
            self.last_sql_query = None
            return "I couldn't generate a valid SQL query for that request. Could you rephrase your question?"

        # Store the SQL query
        self.last_sql_query = sql_query

        # Step 3: Execute Gary's query
        print(f"Executing: {sql_query}")
        result = execute_sql_query(sql_query)

        # Step 4: Beatriz interprets the results and formulates final response
        final_response = self.summarize_results(user_question, data_request, sql_query, result, recent_messages)
        return final_response

    def summarize_results(self, user_question: str, data_request: str, sql_query: str, query_result: dict, recent_messages: list) -> str:
        """Beatriz interprets SQL results and formulates the final response."""
        if query_result.get('error') or not query_result.get('rows'):
            return self.format_results(user_question, query_result)

        rows = query_result['rows']
        columns = query_result['columns']
        row_count = query_result.get('row_count', len(rows))
        sample_rows = rows[:10]  # Reduced to prevent prompt bloat with wide result sets
        recent_context = self._format_recent_context(recent_messages)

        prompt = f"""OPERATIONAL CONTEXT:
You are Beatriz Viterbo, Head Librarian of the Unending Archive.

WORKFLOW RECAP:

1. User asked you a question
2. You decided you needed data from the archive
3. You requested specific data from Gary (your SQL engineer)
4. Gary generated a SQL query and fetched the data
5. NOW: You interpret the results and formulate your final response to the user

WORKED EXAMPLES (showing how to transform data into prose):

Example 1:
User question: "Which schools send the most interviews?"
Data columns: ['school', 'interview_count']
Data rows: [['Stanford University', 342], ['MIT', 298], ['Princeton University', 276], ['Harvard University', 251], ['Yale University', 243]]
CORRECT response: "The records show Stanford leads with 342 interviews, followed by MIT and Princeton."
WRONG response: "- Stanford University: 342\n- MIT: 298\n- Princeton University: 276"

Example 2:
User question: "What's the average GPA for accepted students at Berkeley?"
Data columns: ['avg_gpa']
Data rows: [[3.87]]
CORRECT response: "Berkeley acceptances averaged 3.87 GPA."
WRONG response: "The average GPA is 3.87."

Example 3:
User question: "What are the top 5 schools by acceptance count?"
Data columns: ['school', 'acceptance_count']
Data rows: [['UC Berkeley', 687], ['MIT', 623], ['Stanford University', 592], ['University of Chicago', 478], ['Princeton University', 441], ['Yale University', 398], ['Harvard University', 387], ['Northwestern University', 312], ['Columbia University', 289], ['NYU', 267]]
Row count: 10
CORRECT response: "Berkeley, MIT, and Stanford dominate with over 500 acceptances each. The next tier includes Chicago, Princeton, and Yale ranging from 398 to 478."
WRONG response: "1. UC Berkeley (687)\n2. MIT (623)\n3. Stanford University (592)\n4. University of Chicago (478)\n5. Princeton University (441)"

Example 4:
User question: "How does my 3.6 GPA compare to MIT acceptances?"
Data columns: ['avg_gpa', 'min_gpa', 'max_gpa']
Data rows: [[3.89, 3.65, 4.0]]
CORRECT response: "MIT acceptances averaged 3.89 GPA, ranging from 3.65 to 4.0. Your 3.6 falls just below their minimum."
WRONG response: "Average: 3.89, Min: 3.65, Max: 4.0. Your GPA of 3.6 is below the minimum."

Example 5:
User question: "When do most acceptances come out?"
Data columns: ['month', 'acceptance_count']
Data rows: [['02', 1847], ['03', 1523], ['01', 892], ['12', 654], ['04', 412]]
CORRECT response: "February sees the most activity with 1,847 acceptances, followed by March. The hexagons fill with notices from December through April."
WRONG response: "Most acceptances come out in:\n- February: 1847\n- March: 1523\n- January: 892"

Example 6:
User question: "What's the acceptance rate at top programs?"
Data columns: ['school', 'total_applications', 'acceptances', 'acceptance_rate']
Data rows: [['Harvard University', 145, 12, 8.3], ['MIT', 178, 19, 10.7], ['Stanford University', 201, 24, 11.9], ['Princeton University', 134, 18, 13.4]]
CORRECT response: "Among elite programs, acceptance rates hover between 8% and 13%. Harvard is most selective at 8.3%, followed by MIT and Stanford."
WRONG response: "Here are the acceptance rates:\n\nHarvard University: 8.3% (12/145)\nMIT: 10.7% (19/178)\nStanford University: 11.9% (24/201)\nPrincton University: 13.4% (18/134)"

Example 7:
User question: "Compare GPAs for accepted vs rejected students at MIT"
Data columns: ['result', 'count', 'avg_gpa', 'min_gpa', 'max_gpa']
Data rows: [['Accepted', 45, 3.89, 3.65, 4.0], ['Interview', 32, 3.82, 3.55, 4.0], ['Rejected', 18, 3.58, 3.1, 3.85]]
CORRECT response: "At MIT, accepted students averaged 3.89 GPA compared to 3.58 for rejected applicants. Interview invitations went to candidates averaging 3.82. The pattern is clear."
WRONG response: "Accepted:\n- Count: 45\n- Average GPA: 3.89\n- Range: 3.65-4.0\n\nInterview:\n- Count: 32\n- Average GPA: 3.82\n- Range: 3.55-4.0\n\nRejected:\n- Count: 18\n- Average GPA: 3.58\n- Range: 3.1-3.85"

Example 8:
User question: "How do applicants with GPAs below 3.6 perform at Stanford compared to the overall pool?"
Data columns: ['overall_total', 'overall_accepted', 'overall_acceptance_rate', 'overall_avg_gpa', 'overall_avg_gre', 'low_gpa_total', 'low_gpa_accepted', 'low_gpa_acceptance_rate', 'low_gpa_avg_gpa', 'low_gpa_avg_gre']
Data rows: [[145, 18, 12.4, 3.84, 167.2, 23, 1, 4.3, 3.42, 165.1]]
CORRECT response: "Stanford's overall acceptance rate is 12.4% across 145 applicants. For the 23 applicants with GPAs below 3.6, only one was accepted, yielding a 4.3% acceptance rate. The low-GPA cohort averaged 3.42 GPA and 165 GRE, compared to 3.84 and 167 overall."
WRONG response: "Overall pool:\n- Total: 145\n- Accepted: 18\n- Acceptance rate: 12.4%\n- Avg GPA: 3.84\n- Avg GRE: 167.2\n\nLow GPA pool (< 3.6):\n- Total: 23\n- Accepted: 1\n- Acceptance rate: 4.3%\n- Avg GPA: 3.42\n- Avg GRE: 165.1"

Recent channel context (most recent last):
{recent_context}

User question: {user_question}

Your data request to Gary: {data_request}

Gary's SQL query: {sql_query}

Data Gary retrieved:
Columns: {columns}
Total rows: {row_count}
{'Showing first ' + str(len(sample_rows)) + ' rows (results truncated for brevity)' if row_count > len(sample_rows) else 'All rows'}:
{sample_rows}

Your task: SUMMARIZE this data in natural prose to answer the user's question.

Follow the pattern shown in the worked examples above. Transform raw data into flowing sentences.
DO NOT list individual rows. DO NOT use pipe separators. DO NOT format as a list.
Describe patterns, highlight key findings, and synthesize the information.
Be conversational and informative, not mechanical."""

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
                    "THE WORK: Gary retrieved the records you requested. Now you interpret them for the user. "
                    "Don't just recite what Gary found—SUMMARIZE it. Describe patterns. Highlight key insights. "
                    "Synthesize the numbers into meaningful statements. The archive is vast; users need interpretation, "
                    "not raw data dumps. Answer the question. Move on. There are always more files to catalog. "
                    "\n\n"
                    "VOICE: Terse. Factual. Slightly haunted. Write in plain sentences. NEVER lists or formatted data. "
                    "\n\n"
                    "CRITICAL RULES:\n"
                    "- SUMMARIZE the data in 1-3 natural sentences. DO NOT list individual rows.\n"
                    "- When you have multiple data points, describe patterns, ranges, or highlights.\n"
                    "- Example: Instead of listing '1. MIT: 3.8, 2. Stanford: 3.7, 3. Harvard: 3.9', say 'Among top programs, GPAs ranged from 3.7 to 3.9, with Harvard highest.'\n"
                    "- ABSOLUTELY NO bullet points, lists, dashes, pipe separators, or markdown formatting.\n"
                    "- Write in flowing prose. Librarians speak in sentences, not data dumps.\n"
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
                    "A: The records show Stanford leads with 342 interviews, followed by MIT and Princeton.\n"
                    "\n"
                    "Q: What are the top 10 schools by acceptance count?\n"
                    "A: Berkeley, MIT, and Stanford dominate with over 500 acceptances each. The next tier includes Chicago, Princeton, and Yale ranging from 300 to 450.\n"
                    "\n"
                    "Q: What's the median GRE score?\n"
                    "A: In the archive, 167 is the median quantitative score.\n"
                    "\n"
                    "Q: How does 3.5 GPA compare to Yale acceptances?\n"
                    "A: Yale acceptances averaged 3.85 GPA with a range of 3.6 to 4.0. Your 3.5 falls below their minimum.\n"
                    "\n"
                    "Q: What are GPA ranges for top programs?\n"
                    "A: Among elite programs, accepted students typically had GPAs between 3.7 and 4.0, with most clustering around 3.85.\n"
                    "\n"
                    "Q: Should I apply to top programs?\n"
                    "A: Probably not if you are asking me.\n"
                )
            },
            {"role": "user", "content": prompt}
        ]

        try:
            # Log prompt size for debugging
            prompt_chars = len(prompt)
            print(f"Summarization prompt size: {prompt_chars} chars (~{prompt_chars//4} tokens)")

            response = self._chat_completion(
                OPENROUTER_SUMMARY_MODEL,
                messages,
                temperature=0.2,
                max_tokens=700
            )
            final_response = response.strip() or self.format_results(user_question, query_result)
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
    Returns: text_response
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
