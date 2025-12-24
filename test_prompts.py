#!/usr/bin/env python3
"""
Test script to verify the LLM prompts are configured correctly
"""

def test_prompts():
    print("Testing LLM prompt configuration...")
    print("=" * 60)

    # Read the llm_interface.py file
    with open('llm_interface.py', 'r') as f:
        content = f.read()

    # Check for critical prompt elements
    checks = [
        ("ALWAYS use the 'phd' table by default", "phd table default instruction"),
        ("ONLY use the 'masters' table if", "masters table conditional usage"),
        ("NEVER query the 'postings' table", "postings table exclusion"),
        ("SELECT COUNT(*) FROM phd", "phd table in examples"),
        ("decision_date", "decision_date field reference"),
        ("strftime('%m', decision_date)", "decision_date date functions"),
        ("CRITICAL: Always query the 'phd' table", "Gary system message phd default"),
        ("PhD economics graduate admissions", "Beatriz context awareness"),
    ]

    passed = 0
    failed = 0

    print("\nChecking prompt content:\n")
    for search_text, description in checks:
        if search_text in content:
            print(f"✓ {description}")
            passed += 1
        else:
            print(f"✗ MISSING: {description}")
            failed += 1

    # Check that old instructions are removed
    if "Only use the 'postings' table" in content:
        print("✗ WARNING: Old instruction to use only postings table still present!")
        failed += 1
    else:
        print("✓ Old 'only postings' instruction removed")
        passed += 1

    # Read the llm_tools.py schema
    with open('llm_tools.py', 'r') as f:
        schema_content = f.read()

    print("\nChecking schema documentation:\n")
    schema_checks = [
        ("Table: phd (the DEFAULT)", "phd marked as DEFAULT"),
        ("Table: masters", "masters table documented"),
        ("decision_date: DATE", "decision_date as DATE type"),
        ("ISO format YYYY-MM-DD", "decision_date format specified"),
    ]

    for search_text, description in schema_checks:
        if search_text in schema_content:
            print(f"✓ {description}")
            passed += 1
        else:
            print(f"✗ MISSING: {description}")
            failed += 1

    print("\n" + "=" * 60)
    print(f"Results: {passed} passed, {failed} failed")

    if failed == 0:
        print("✓ All prompt configuration tests passed!")
    else:
        print(f"✗ {failed} checks failed")

    return failed == 0

if __name__ == '__main__':
    success = test_prompts()
    exit(0 if success else 1)
