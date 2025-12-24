import sqlite3
import json
import matplotlib.pyplot as plt
import seaborn as sns
import pandas as pd
from datetime import datetime
import io
import os

DB_PATH = os.getenv('DB_PATH', 'gradcafe_messages.db')

def execute_sql_query(query: str) -> dict:
    """
    Execute a read-only SQL query on the GradCafe database.
    Returns results as a dictionary with columns and rows.

    Safety: Only SELECT queries are allowed.
    """
    query = query.strip()

    if not query.upper().startswith('SELECT'):
        return {
            "error": "Only SELECT queries are allowed for safety reasons.",
            "columns": [],
            "rows": []
        }

    forbidden_keywords = ['INSERT', 'UPDATE', 'DELETE', 'DROP', 'CREATE', 'ALTER', 'TRUNCATE']
    query_upper = query.upper()
    for keyword in forbidden_keywords:
        if keyword in query_upper:
            return {
                "error": f"Query contains forbidden keyword: {keyword}",
                "columns": [],
                "rows": []
            }

    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute(query)
        rows = cursor.fetchall()

        if rows:
            columns = list(rows[0].keys())
            data = [list(row) for row in rows]
        else:
            columns = []
            data = []

        conn.close()

        return {
            "error": None,
            "columns": columns,
            "rows": data,
            "row_count": len(data)
        }
    except Exception as e:
        return {
            "error": str(e),
            "columns": [],
            "rows": []
        }

def get_database_schema() -> str:
    """
    Returns the database schema information to help the LLM understand what data is available.
    """
    schema = """
GradCafe Economics Database Schema:

Table: postings
Columns:
  - id: INTEGER (primary key)
  - gradcafe_id: TEXT (unique identifier from GradCafe)
  - school: TEXT (university name)
  - program: TEXT (program name, e.g., "Economics")
  - degree: TEXT (PhD, Masters, etc.)
  - decision: TEXT (e.g., "Accepted on 15 Dec", "Rejected on 20 Nov")
  - date_added: TEXT (raw GradCafe date text, e.g., "December 15, 2025")
  - date_added_iso: TEXT (normalized ISO date "YYYY-MM-DD" when available)
  - season: TEXT (e.g., "Fall 2026", "Spring 2025")
  - status: TEXT (International, American, Other)
  - gpa: REAL (e.g., 3.85)
  - gre_quant: REAL (quantitative GRE score)
  - gre_verbal: REAL (verbal GRE score)
  - gre_aw: REAL (analytical writing GRE score)
  - comment: TEXT (user comments)
  - scraped_at: TIMESTAMP (when we scraped it)
  - posted_to_discord: BOOLEAN (0 or 1)
  - result: TEXT (extracted result: Accepted, Rejected, Interview, Waitlist)
  - decision_date: TEXT (extracted decision date)

Total postings: ~30,545 individual admissions results

Table: phd (RECOMMENDED for PhD-specific queries)
Simplified aggregation table for PhD programs (2018+)
Columns:
  - school: TEXT (university name)
  - program: TEXT (program name)
  - gpa: REAL (GPA score)
  - gre: REAL (GRE quantitative score)
  - result: TEXT (Accepted, Rejected, Interview, Waitlist)

Total PhD postings: ~8,241

Table: masters (RECOMMENDED for Masters-specific queries)
Simplified aggregation table for Masters programs (2018+)
Columns:
  - school: TEXT (university name)
  - program: TEXT (program name)
  - gpa: REAL (GPA score)
  - gre: REAL (GRE quantitative score)
  - result: TEXT (Accepted, Rejected, Interview, Waitlist)

Total Masters postings: ~1,155

IMPORTANT: Use the 'phd' or 'masters' tables for simpler queries when you only need
school, program, scores, and result. These tables are filtered for 2018+ and by degree type.
Use the 'postings' table when you need additional fields like dates, status, season, or comments.

Common queries:
- Count acceptances by school (use phd/masters tables)
- Average GPA/GRE by decision type (use phd/masters tables)
- Acceptance rates over time (use postings table for date_added_iso)
- International vs American acceptance rates (use postings table for status)
- When do schools typically send decisions (use postings table for decision_date or date_added_iso)
"""
    return schema

def create_plot(query_result: dict, plot_type: str, title: str, x_label: str = None, y_label: str = None) -> str:
    """
    Create a matplotlib plot from query results and save to file.
    Returns the filename of the saved plot.

    plot_type: 'bar', 'line', 'scatter', 'pie', 'histogram'
    """
    if query_result.get('error'):
        return None

    if not query_result['rows']:
        return None

    df = pd.DataFrame(query_result['rows'], columns=query_result['columns'])

    plt.figure(figsize=(10, 6))
    sns.set_style("whitegrid")

    try:
        if plot_type == 'bar':
            if len(df.columns) >= 2:
                plt.bar(df.iloc[:, 0], df.iloc[:, 1])
        elif plot_type == 'line':
            if len(df.columns) >= 2:
                plt.plot(df.iloc[:, 0], df.iloc[:, 1], marker='o')
        elif plot_type == 'pie':
            if len(df.columns) >= 2:
                plt.pie(df.iloc[:, 1], labels=df.iloc[:, 0], autopct='%1.1f%%')
        elif plot_type == 'histogram':
            plt.hist(df.iloc[:, 0], bins=20)
        elif plot_type == 'scatter':
            if len(df.columns) >= 2:
                plt.scatter(df.iloc[:, 0], df.iloc[:, 1])

        plt.title(title)
        if x_label:
            plt.xlabel(x_label)
        if y_label:
            plt.ylabel(y_label)

        plt.xticks(rotation=45, ha='right')
        plt.tight_layout()

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f'plot_{timestamp}.png'
        plt.savefig(filename, dpi=150, bbox_inches='tight')
        plt.close()

        return filename
    except Exception as e:
        plt.close()
        return None

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "execute_sql_query",
            "description": "Execute a read-only SELECT query on the GradCafe economics admissions database. Use this to answer questions about admissions data, acceptance rates, GPA/GRE statistics, timing of decisions, etc.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "A SQL SELECT query to run on the postings table. Must be read-only (SELECT only)."
                    }
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "create_plot",
            "description": "Create a visualization from query results. Use after executing a SQL query to visualize the data.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query_result": {
                        "type": "object",
                        "description": "The result object from execute_sql_query"
                    },
                    "plot_type": {
                        "type": "string",
                        "enum": ["bar", "line", "scatter", "pie", "histogram"],
                        "description": "Type of plot to create"
                    },
                    "title": {
                        "type": "string",
                        "description": "Title for the plot"
                    },
                    "x_label": {
                        "type": "string",
                        "description": "Label for x-axis (optional)"
                    },
                    "y_label": {
                        "type": "string",
                        "description": "Label for y-axis (optional)"
                    }
                },
                "required": ["query_result", "plot_type", "title"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_database_schema",
            "description": "Get information about the database schema and available columns. Use this first to understand what data is available before writing queries.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    }
]
