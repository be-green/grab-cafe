from llm_tools import execute_sql_query, get_database_schema
import time

print("=" * 80)
print("TESTING LLM TOOLS (without loading full LLM)")
print("=" * 80)

print("\n1. Testing database schema retrieval...")
print("-" * 80)
schema = get_database_schema()
print(schema[:300] + "...")
print("✓ Schema retrieved successfully")

print("\n2. Testing SQL query execution...")
print("-" * 80)

test_queries = [
    ("Count total postings", "SELECT COUNT(*) as total FROM postings"),
    ("Top 5 schools by acceptances", "SELECT school, COUNT(*) as count FROM postings WHERE decision LIKE '%Accepted%' GROUP BY school ORDER BY count DESC LIMIT 5"),
    ("Average GPA of accepted students", "SELECT AVG(CAST(gpa AS REAL)) as avg_gpa FROM postings WHERE decision LIKE '%Accepted%' AND gpa != '' AND CAST(gpa AS REAL) <= 4.0"),
    ("International vs American", "SELECT status, COUNT(*) as count FROM postings WHERE status IN ('International', 'American') GROUP BY status"),
]

for desc, query in test_queries:
    print(f"\n{desc}:")
    print(f"Query: {query}")
    start = time.time()
    result = execute_sql_query(query)
    elapsed = time.time() - start

    if result.get('error'):
        print(f"✗ Error: {result['error']}")
    else:
        print(f"✓ Success ({elapsed*1000:.2f}ms)")
        print(f"  Columns: {result['columns']}")
        print(f"  Rows: {result['rows'][:3]}")
        if result['row_count'] > 3:
            print(f"  ... ({result['row_count']} total rows)")

print("\n3. Testing query safety...")
print("-" * 80)

dangerous_queries = [
    "DELETE FROM postings",
    "DROP TABLE postings",
    "UPDATE postings SET school = 'hacked'",
]

for query in dangerous_queries:
    result = execute_sql_query(query)
    if result.get('error'):
        print(f"✓ Blocked: {query[:50]}")
    else:
        print(f"✗ SECURITY ISSUE: {query} was allowed!")

print("\n" + "=" * 80)
print("BASIC TOOLS TEST COMPLETE")
print("=" * 80)
print("\nNOTE: Full LLM test requires downloading Qwen model (~600MB)")
print("To test with LLM, run: python -c \"from llm_interface import query_llm; print(query_llm('How many schools are in the database?'))\"")
