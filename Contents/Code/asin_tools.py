# -*- coding: utf-8 -*-
"""Reusable ASIN grammar and matching helpers."""

import re

# Typed lookups keep the legacy broad grammar: users may paste any
# ten-character ID-shaped token. The lookahead is inherited verbatim from
# the legacy agent.
TYPED_ASIN_RE = re.compile(r'(?=.\d)[A-Z\d]{10}')

# Scanner filenames are untrusted bulk input: only the conventional
# Audible ASIN (B + 9 alphanumerics) counts as an edition hint, bounded so
# a hash or hex run is never read as one.
FILE_ASIN_RE = re.compile(
    r'(?<![A-Za-z0-9])B[A-Za-z0-9]{9}(?![A-Za-z0-9])', re.IGNORECASE)


def typed_asin_match(value):
    """
        Returns the first ten-character ID-shaped token in value as a
        re.Match (read the token with .group(0)), or None.

        This is the broad grammar for text a user typed. It is wider than
        the scanner hint grammar on purpose.
    """
    if not value:
        return None
    return TYPED_ASIN_RE.search(value)


def file_asin_hints(value):
    """
        Returns unique conventional ASINs from a scanner name or path,
        uppercased, in first-seen order.
    """
    if not value:
        return []
    asins = []
    for match in FILE_ASIN_RE.finditer(value):
        asin = match.group(0).upper()
        if asin not in asins:
            asins.append(asin)
    return asins
