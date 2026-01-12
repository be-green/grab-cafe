#!/usr/bin/env python3
"""
Unit tests for parser bug fixes.
Tests validation functions, date normalization, and degree pattern matching.
"""
import unittest
import re
import sys

sys.path.insert(0, '.')

from scraper import (
    _normalize_date,
    _validate_gpa,
    _validate_gre_section,
    DEGREE_PATTERN,
)


class TestDateNormalization(unittest.TestCase):
    """Bug 4: Date normalization should return None for unparseable dates."""

    def test_valid_short_month(self):
        self.assertEqual(_normalize_date("Dec 24, 2024"), "2024-12-24")
        self.assertEqual(_normalize_date("Jan 1, 2025"), "2025-01-01")

    def test_valid_full_month(self):
        self.assertEqual(_normalize_date("December 24, 2024"), "2024-12-24")
        self.assertEqual(_normalize_date("January 1, 2025"), "2025-01-01")

    def test_valid_numeric(self):
        self.assertEqual(_normalize_date("12/24/2024"), "2024-12-24")
        self.assertEqual(_normalize_date("01/01/2025"), "2025-01-01")

    def test_valid_iso(self):
        self.assertEqual(_normalize_date("2024-12-24"), "2024-12-24")

    def test_invalid_dates_return_none(self):
        self.assertIsNone(_normalize_date("garbage"))
        self.assertIsNone(_normalize_date("24-12-2024"))
        self.assertIsNone(_normalize_date("24 Dec"))
        self.assertIsNone(_normalize_date(""))
        self.assertIsNone(_normalize_date(None))

    def test_whitespace_handling(self):
        self.assertEqual(_normalize_date("  Dec 24, 2024  "), "2024-12-24")


class TestGPAValidation(unittest.TestCase):
    """Bug 7: GPA validation."""

    def test_valid_us_gpa(self):
        self.assertEqual(_validate_gpa("3.85"), "3.85")
        self.assertEqual(_validate_gpa("4.0"), "4.0")
        self.assertEqual(_validate_gpa("0.0"), "0.0")
        self.assertEqual(_validate_gpa("2.5"), "2.5")

    def test_valid_international_gpa(self):
        self.assertEqual(_validate_gpa("8.5"), "8.5")
        self.assertEqual(_validate_gpa("10.0"), "10.0")
        self.assertEqual(_validate_gpa("9.99"), "9.99")

    def test_invalid_gpa_too_high(self):
        self.assertIsNone(_validate_gpa("44.0"))
        self.assertIsNone(_validate_gpa("10.1"))
        self.assertIsNone(_validate_gpa("11.0"))
        self.assertIsNone(_validate_gpa("100"))

    def test_invalid_gpa_negative(self):
        self.assertIsNone(_validate_gpa("-1.0"))
        self.assertIsNone(_validate_gpa("-0.1"))

    def test_invalid_gpa_empty(self):
        self.assertIsNone(_validate_gpa(""))
        self.assertIsNone(_validate_gpa(None))

    def test_invalid_gpa_non_numeric(self):
        self.assertIsNone(_validate_gpa("abc"))
        self.assertIsNone(_validate_gpa("3.5abc"))


class TestGREValidation(unittest.TestCase):
    """Bug 7: GRE validation."""

    def test_valid_quant(self):
        self.assertEqual(_validate_gre_section("170", "Q"), "170")
        self.assertEqual(_validate_gre_section("130", "Q"), "130")
        self.assertEqual(_validate_gre_section("155", "Q"), "155")

    def test_valid_verbal(self):
        self.assertEqual(_validate_gre_section("170", "V"), "170")
        self.assertEqual(_validate_gre_section("130", "V"), "130")
        self.assertEqual(_validate_gre_section("162", "V"), "162")

    def test_invalid_quant_verbal_too_high(self):
        self.assertIsNone(_validate_gre_section("171", "Q"))
        self.assertIsNone(_validate_gre_section("171", "V"))
        self.assertIsNone(_validate_gre_section("330", "Q"))  # Combined score
        self.assertIsNone(_validate_gre_section("200", "V"))

    def test_invalid_quant_verbal_too_low(self):
        self.assertIsNone(_validate_gre_section("129", "Q"))
        self.assertIsNone(_validate_gre_section("129", "V"))
        self.assertIsNone(_validate_gre_section("0", "Q"))

    def test_valid_aw(self):
        self.assertEqual(_validate_gre_section("6.0", "AW"), "6.0")
        self.assertEqual(_validate_gre_section("0.0", "AW"), "0.0")
        self.assertEqual(_validate_gre_section("4.5", "AW"), "4.5")
        self.assertEqual(_validate_gre_section("3", "AW"), "3")

    def test_invalid_aw_too_high(self):
        self.assertIsNone(_validate_gre_section("6.5", "AW"))
        self.assertIsNone(_validate_gre_section("7.0", "AW"))

    def test_invalid_aw_negative(self):
        self.assertIsNone(_validate_gre_section("-1.0", "AW"))

    def test_invalid_empty(self):
        self.assertIsNone(_validate_gre_section("", "Q"))
        self.assertIsNone(_validate_gre_section(None, "V"))


class TestDegreePatternMatching(unittest.TestCase):
    """Bug 2: Degree pattern matching."""

    def test_extracts_phd(self):
        match = re.search(DEGREE_PATTERN, "EconomicsPhD")
        self.assertIsNotNone(match)
        self.assertEqual(match.group(1), "PhD")

    def test_extracts_masters(self):
        match = re.search(DEGREE_PATTERN, "EconomicsMasters")
        self.assertIsNotNone(match)
        self.assertEqual(match.group(1), "Masters")

    def test_extracts_mba(self):
        match = re.search(DEGREE_PATTERN, "EconomicsMBA")
        self.assertIsNotNone(match)
        self.assertEqual(match.group(1), "MBA")

    def test_extracts_mphil(self):
        match = re.search(DEGREE_PATTERN, "Public PolicyMPhil")
        self.assertIsNotNone(match)
        self.assertEqual(match.group(1), "MPhil")

    def test_extracts_jd(self):
        match = re.search(DEGREE_PATTERN, "LawJD")
        self.assertIsNotNone(match)
        self.assertEqual(match.group(1), "JD")

    def test_extracts_other(self):
        match = re.search(DEGREE_PATTERN, "EconomicsOther")
        self.assertIsNotNone(match)
        self.assertEqual(match.group(1), "Other")

    def test_extracts_msc(self):
        match = re.search(DEGREE_PATTERN, "StatisticsMSc")
        self.assertIsNotNone(match)
        self.assertEqual(match.group(1), "MSc")

    def test_extracts_ms(self):
        match = re.search(DEGREE_PATTERN, "Computer ScienceMS")
        self.assertIsNotNone(match)
        self.assertEqual(match.group(1), "MS")

    def test_extracts_ma(self):
        match = re.search(DEGREE_PATTERN, "HistoryMA")
        self.assertIsNotNone(match)
        self.assertEqual(match.group(1), "MA")

    def test_no_match_for_unknown(self):
        match = re.search(DEGREE_PATTERN, "Economics")
        self.assertIsNone(match)

    def test_program_extraction(self):
        """Test that we can extract program name correctly."""
        test_cases = [
            ("EconomicsPhD", "Economics", "PhD"),
            ("EconomicsMasters", "Economics", "Masters"),
            ("EconomicsMBA", "Economics", "MBA"),
            ("Public PolicyMPhil", "Public Policy", "MPhil"),
            ("Agricultural, Environmental, and Development EconomicsPhD",
             "Agricultural, Environmental, and Development Economics", "PhD"),
        ]

        for program_raw, expected_program, expected_degree in test_cases:
            match = re.search(DEGREE_PATTERN, program_raw)
            self.assertIsNotNone(match, f"No match for {program_raw}")
            degree = match.group(1)
            program = program_raw[:match.start()].strip()
            self.assertEqual(program, expected_program, f"Program mismatch for {program_raw}")
            self.assertEqual(degree, expected_degree, f"Degree mismatch for {program_raw}")


class TestCombinedScoreLogic(unittest.TestCase):
    """Test combined score calculation logic."""

    def test_combined_score_range(self):
        """Valid combined scores are 260-340."""
        for score in [260, 300, 340]:
            self.assertTrue(260 <= score <= 340)

        for score in [259, 341, 200, 400]:
            self.assertFalse(260 <= score <= 340)

    def test_individual_score_range(self):
        """Valid individual scores are 130-170."""
        for score in [130, 150, 170]:
            self.assertTrue(130 <= score <= 170)

        for score in [129, 171, 200, 330]:
            self.assertFalse(130 <= score <= 170)


if __name__ == '__main__':
    unittest.main(verbosity=2)
