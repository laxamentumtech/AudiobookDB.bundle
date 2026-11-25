# -*- coding: utf-8 -*-
"""Tests for the reusable ASIN grammar in asin_tools.py."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import plex_shim  # noqa: F401,E402  (adds Contents/Code to sys.path)
import asin_tools  # noqa: E402


class TestTypedAsinMatch(unittest.TestCase):
    def test_b_prefixed_asin(self):
        match = asin_tools.typed_asin_match('The Martian B00B5HZGUG')
        self.assertEqual(match.group(0), 'B00B5HZGUG')

    def test_numeric_id(self):
        match = asin_tools.typed_asin_match('title 0593168070')
        self.assertEqual(match.group(0), '0593168070')

    def test_longer_run_keeps_legacy_window(self):
        # The legacy lookahead anchors the match start, not its end.
        match = asin_tools.typed_asin_match('1B00B5HZGUG')
        self.assertEqual(match.group(0), 'B00B5HZGUG')

    def test_no_match(self):
        self.assertIsNone(asin_tools.typed_asin_match('no asin here'))

    def test_empty_and_none(self):
        self.assertIsNone(asin_tools.typed_asin_match(''))
        self.assertIsNone(asin_tools.typed_asin_match(None))


class TestFileAsinHints(unittest.TestCase):
    def test_uppercases_and_dedupes(self):
        self.assertEqual(
            asin_tools.file_asin_hints(
                'part b00b5hzgug.mp3 B00B5HZGUG'),
            ['B00B5HZGUG'])

    def test_bounded_match_rejects_longer_run(self):
        self.assertEqual(
            asin_tools.file_asin_hints('XB00B5HZGUGX.mp3'), [])

    def test_rejects_non_audible_token(self):
        self.assertEqual(
            asin_tools.file_asin_hints('recording A000000001.mp3'), [])

    def test_preserves_first_seen_order(self):
        self.assertEqual(
            asin_tools.file_asin_hints(
                'B00G0WYW92 then B00B5HZGUG'),
            ['B00G0WYW92', 'B00B5HZGUG'])

    def test_url_encoding_is_left_to_the_caller(self):
        self.assertEqual(
            asin_tools.file_asin_hints('B00B5HZGUG%20The%20Martian'),
            ['B00B5HZGUG'])

    def test_empty_and_none(self):
        self.assertEqual(asin_tools.file_asin_hints(''), [])
        self.assertEqual(asin_tools.file_asin_hints(None), [])


if __name__ == '__main__':
    unittest.main()
