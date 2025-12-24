#!/usr/bin/env python3
"""
Test the response cleaning functionality
"""
import re

def _clean_and_validate_response(response: str) -> str:
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
    school_match = re.search(school_patterns, response_lower)
    has_specific_school = bool(school_match)
    matched_schools = [school_match.group(1)] if school_match else []
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

    # Debug output
    print(f"  DEBUG: len={len(response)}, advice_count={advice_count}, is_about_data={is_about_data}")
    print(f"  DEBUG: has_numbers={has_numbers_with_context}, has_school={has_specific_school}")
    if matched_schools:
        print(f"  DEBUG: matched_schools={matched_schools}")
    print(f"  DEBUG: has_metadata={has_archive_metadata}, has_summary={has_data_summary}")

    # If long response with lots of advice and NO data, it's off-topic
    if len(response) > 150 and advice_count >= 3 and not is_about_data:
        return "The archive doesn't contain that."

    # If any advice but no data whatsoever, likely off-topic
    if advice_count >= 5 and not is_about_data:
        return "The archive doesn't contain that."

    return response

# Test cases
test_cases = [
    {
        "name": "Bulleted life advice (off-topic)",
        "input": """It's understandable to feel that pressure, especially when aiming for a competitive PhD program. To keep your workload sustainable and protect your mental health, consider the following:

- Set firm work boundaries – designate specific hours for study and stick to them.
- Take regular breaks – short breaks improve focus and prevent burnout.
- Maintain physical health – exercise, sleep, and nutrition are critical for mental resilience.
- Build a support system – talk to peers, mentors, or a counselor about stress.
- Practice mindfulness or meditation – these can help manage anxiety.
- Stay organized – planning ahead reduces last-minute stress.
- Know your limits – it's okay to adjust goals if you're feeling overwhelmed.

Taking care of yourself now sets the foundation for a successful, sustainable academic career."""
    },
    {
        "name": "Short archive response",
        "input": "MIT averaged 3.8 GPA, Harvard 3.9."
    },
    {
        "name": "Archive response with bold",
        "input": "The archive shows **MIT** averaged 3.8 GPA, while **Harvard** averaged 3.9."
    },
    {
        "name": "Archive response with bullets",
        "input": """The records show:
- MIT: 3.8 GPA
- Harvard: 3.9 GPA
- Stanford: 3.85 GPA"""
    }
]

print("Testing response cleaning functionality\n")
print("=" * 80)

for i, test in enumerate(test_cases, 1):
    print(f"\n### Test {i}: {test['name']}")
    print(f"\nOriginal ({len(test['input'])} chars):")
    print(test['input'])
    print(f"\nCleaned:")
    cleaned = _clean_and_validate_response(test['input'])
    print(cleaned)
    print(f"({len(cleaned)} chars)")
    print("-" * 80)
