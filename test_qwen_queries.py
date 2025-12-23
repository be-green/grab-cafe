import sys
from llm_interface import query_llm

test_questions = [
    "How many total admissions results are in the database?",
    "What are the top 5 schools with the most acceptances?",
    "What is the average GPA of accepted students?",
    "What percentage of applicants are international vs American?",
]

print("=" * 80)
print("TESTING QWEN QUERIES")
print("=" * 80)
print("\nLoading Qwen model (this may take a minute on first run)...\n")

for i, question in enumerate(test_questions, 1):
    print(f"\n{'='*80}")
    print(f"QUESTION {i}: {question}")
    print(f"{'='*80}\n")

    try:
        response, plot_file = query_llm(question)
        print("RESPONSE:")
        print(response)

        if plot_file:
            print(f"\n📊 Generated plot: {plot_file}")

        print()

    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()

print("\n" + "=" * 80)
print("TEST COMPLETE")
print("=" * 80)
