# -*- coding: utf-8 -*-
"""Tests for Contents/Code/region_tools.py (RegionTool + region table)."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import plex_shim  # noqa: F401,E402  (framework fakes must load first)

from region_tools import RegionTool, available_regions  # noqa: E402


class TestRegionTool(unittest.TestCase):
    def setUp(self):
        self.region = RegionTool(
            region='us', content_type='books', id='B00B5HZGUG',
            query='title=The%20Martian')

    def test_get_region(self):
        self.assertEqual(self.region.get_region(), 'us')

    def test_get_region_name(self):
        self.assertEqual(self.region.get_region_name(), 'United States')

    def test_get_region_query(self):
        self.assertEqual(self.region.get_region_query(), '?region=us')

    def test_get_region_tld(self):
        self.assertEqual(self.region.get_region_tld(), 'com')

    def test_get_content_type_url(self):
        self.assertEqual(
            self.region.get_content_type_url(),
            'https://api.audnex.us/books'
        )

    def test_get_search_url(self):
        self.assertEqual(
            self.region.get_search_url(),
            'https://api.audnex.us/books?region=us&title=The%20Martian'
        )

    def test_get_id_url(self):
        self.assertEqual(
            self.region.get_id_url(),
            'https://api.audnex.us/books/B00B5HZGUG?region=us'
        )

    def test_get_id_url_with_query(self):
        self.assertEqual(
            self.region.get_id_url_with_query(),
            'https://api.audnex.us/books/B00B5HZGUG?region=us'
            '&title=The%20Martian'
        )

    def test_get_api_region_url(self):
        self.assertEqual(
            self.region.get_api_region_url(),
            'https://api.audible.com'
        )

    def test_get_api_params(self):
        self.assertEqual(
            self.region.get_api_params(),
            '?response_groups=contributors,product_desc,product_attrs'
            '&num_results=25&products_sort_by=Relevance'
        )

    def test_get_api_search_url(self):
        self.assertEqual(
            self.region.get_api_search_url(),
            'https://api.audible.com/1.0/catalog/products'
            '?response_groups=contributors,product_desc,product_attrs'
            '&num_results=25&products_sort_by=Relevance'
            '&title=The%20Martian'
        )


class TestAvailableRegions(unittest.TestCase):
    def test_all_regions(self):
        expected = {
            'au': ('Australia', 'com.au'),
            'ca': ('Canada', 'ca'),
            'de': ('Germany', 'de'),
            'es': ('Spain', 'es'),
            'fr': ('France', 'fr'),
            'in': ('India', 'in'),
            'it': ('Italy', 'it'),
            'jp': ('Japan', 'co.jp'),
            'us': ('United States', 'com'),
            'uk': ('United Kingdom', 'co.uk'),
        }
        self.assertEqual(len(available_regions), 10)
        for code, (name, tld) in expected.items():
            self.assertEqual(available_regions[code]['name'], name)
            self.assertEqual(available_regions[code]['TLD'], tld)

    def test_region_urls_for_all_regions(self):
        expected_api = {
            'au': 'https://api.audible.com.au',
            'ca': 'https://api.audible.ca',
            'de': 'https://api.audible.de',
            'es': 'https://api.audible.es',
            'fr': 'https://api.audible.fr',
            'in': 'https://api.audible.in',
            'it': 'https://api.audible.it',
            'jp': 'https://api.audible.co.jp',
            'us': 'https://api.audible.com',
            'uk': 'https://api.audible.co.uk',
        }
        for code, url in expected_api.items():
            helper = RegionTool(region=code, content_type='books',
                                id='B00B5HZGUG')
            self.assertEqual(helper.get_api_region_url(), url, code)
            self.assertEqual(
                helper.get_id_url(),
                'https://api.audnex.us/books/B00B5HZGUG?region=' + code,
                code
            )
