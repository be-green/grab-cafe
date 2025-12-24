#!/usr/bin/env python3
"""
Interactive test script for the Beatriz-Gary workflow.
Allows testing the LLM agents without deploying the Discord bot.
"""

import os
import sys
from dotenv import load_dotenv
from llm_interface import get_llm

load_dotenv()

def print_section(title):
    """Print a formatted section header."""
    print("\n" + "=" * 80)
    print(f"  {title}")
    print("=" * 80)

def print_subsection(title):
    """Print a formatted subsection header."""
    print(f"\n--- {title} ---")

def test_workflow_interactive():
    """Interactive mode - ask questions and see the full workflow."""
    print_section("BEATRIZ & GARY WORKFLOW TESTER")
    print("\nThis tool lets you test the LLM workflow without deploying the bot.")
    print("You'll see each step: Beatriz's planning, Gary's SQL, and Beatriz's final response.")
    print("\nType 'quit' or 'exit' to stop.")

    if not os.getenv("OPENROUTER_API_KEY"):
        print("\n❌ ERROR: OPENROUTER_API_KEY not found in environment.")
        print("Make sure your .env file is set up correctly.")
        sys.exit(1)

    try:
        llm = get_llm()
        print("✓ LLM initialized successfully")
    except Exception as e:
        print(f"\n❌ ERROR: Failed to initialize LLM: {e}")
        sys.exit(1)

    recent_messages = []

    while True:
        print_section("NEW QUESTION")
        question = input("\nYour question: ").strip()

        if question.lower() in ['quit', 'exit', 'q']:
            print("\nGoodbye!")
            break

        if not question:
            print("Please enter a question.")
            continue

        try:
            # Step 1: Beatriz plans her response
            print_subsection("Step 1: Beatriz Plans Response")
            needs_data, response_or_request = llm.plan_response(question, recent_messages)

            if not needs_data:
                print(f"Decision: DIRECT RESPONSE")
                print(f"Beatriz's response: {response_or_request}")
                print_section("FINAL RESPONSE")
                print(response_or_request)
                continue

            # Step 2: Beatriz requests data from Gary
            data_request = response_or_request
            print(f"Decision: REQUEST DATA")
            print(f"Beatriz's data request: {data_request}")

            # Step 3: Gary generates SQL
            print_subsection("Step 2: Gary Generates SQL")
            sql_response = llm.generate_sql(data_request, question, recent_messages)
            sql_query = llm._extract_sql(sql_response)

            if not sql_query or sql_response.strip().lower() == "none":
                print(f"Gary's response: {sql_response}")
                print("\n⚠️  Gary couldn't generate a valid SQL query.")
                continue

            print(f"Gary's SQL query:\n{sql_query}")

            # Step 4: Execute the query
            print_subsection("Step 3: Execute Query")
            from llm_tools import execute_sql_query
            result = execute_sql_query(sql_query)

            if result.get('error'):
                print(f"❌ Query error: {result['error']}")
                continue

            print(f"Rows returned: {result.get('row_count', len(result.get('rows', [])))}")
            print(f"Columns: {result.get('columns', [])}")

            if result.get('rows'):
                print(f"First few rows:")
                for i, row in enumerate(result['rows'][:5], 1):
                    print(f"  {i}. {row}")
                if len(result['rows']) > 5:
                    print(f"  ... and {len(result['rows']) - 5} more rows")

            # Step 5: Beatriz summarizes
            print_subsection("Step 4: Beatriz Interprets Results")
            final_response = llm.summarize_results(question, data_request, sql_query, result, recent_messages)

            print_section("FINAL RESPONSE")
            print(final_response)

        except KeyboardInterrupt:
            print("\n\nInterrupted. Goodbye!")
            break
        except Exception as e:
            print(f"\n❌ ERROR: {e}")
            import traceback
            traceback.print_exc()
            continue

def test_workflow_examples():
    """Run a set of example questions to test the workflow."""
    examples = [
        "Hello!",
        "When was the most recent MIT acceptance?",
        "Which schools send the most interviews?",
        "How do my stats (3.5 GPA, 165 GRE) compare to Yale acceptances?",
        "What month do most acceptances come out?",
    ]

    print_section("BEATRIZ & GARY WORKFLOW TESTER - EXAMPLE MODE")
    print(f"\nRunning {len(examples)} example questions...")

    if not os.getenv("OPENROUTER_API_KEY"):
        print("\n❌ ERROR: OPENROUTER_API_KEY not found in environment.")
        sys.exit(1)

    try:
        llm = get_llm()
        print("✓ LLM initialized successfully\n")
    except Exception as e:
        print(f"\n❌ ERROR: Failed to initialize LLM: {e}")
        sys.exit(1)

    recent_messages = []

    for i, question in enumerate(examples, 1):
        print_section(f"EXAMPLE {i}/{len(examples)}: {question}")

        try:
            response, plot = llm.query(question, recent_messages)
            print(f"\nFinal response: {response}")
            if plot:
                print(f"Plot generated: {plot}")
        except Exception as e:
            print(f"❌ ERROR: {e}")
            import traceback
            traceback.print_exc()

        print("\n" + "-" * 80)
        input("Press Enter to continue to next example...")

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--examples":
        test_workflow_examples()
    else:
        test_workflow_interactive()
