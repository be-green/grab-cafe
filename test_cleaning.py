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
    # Archive-related keywords that should appear in on-topic responses
    archive_keywords = [
        'archive', 'catalog', 'record', 'file', 'hexagon',
        'school', 'university', 'program', 'phd', 'master',
        'gpa', 'gre', 'accept', 'reject', 'interview', 'waitlist',
        'admit', 'decision', 'average', 'median', 'score',
        'mit', 'harvard', 'stanford', 'yale', 'princeton'
    ]

    response_lower = response.lower()
    has_archive_keyword = any(keyword in response_lower for keyword in archive_keywords)

    # If response is long and has NO archive keywords, it's likely off-topic advice
    if len(response) > 100 and not has_archive_keyword:
        return "The archive doesn't contain that."

    # If response mentions typical advice keywords without archive context
    advice_keywords = ['consider', 'should', 'try to', 'make sure', 'important to', 'help you',
                      'recommend', 'suggest', 'advice', 'balance', 'manage', 'maintain']
    advice_count = sum(1 for keyword in advice_keywords if keyword in response_lower)

    if advice_count >= 3 and not has_archive_keyword:
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
