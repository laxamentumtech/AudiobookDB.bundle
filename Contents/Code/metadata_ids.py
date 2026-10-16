import re

# Legacy ASIN grammar: exactly 10 base36 chars, optional '_xx' region suffix.
# ASINs are uppercased on parse; the region suffix is discarded.
_LEGACY_ASIN_RE = re.compile(r'\A([A-Za-z0-9]{10})(?:_([A-Za-z]{2}))?\Z')

# Native grammar tokens.
_BOOK_PREFIX = 'book.'
_RELEASE_SEGMENT = '.release.'
_PERSON_PREFIX = 'person.'


def parse_metadata_id(raw, content_type):
    """
        Parses a metadata ID into a uniform 3-tuple.

        Returns one of:
            ('book', book_id, release_id_or_None)
            ('person', person_id, None)
            ('legacy', asin, None)
            ('invalid', None, None)

        content_type is the helper's 'books'/'authors'; it disambiguates a
        bare legacy ASIN (the legacy string form is identical for books and
        people). A native ID whose entity type does not match content_type
        parses as invalid.
    """
    if not raw:
        return ('invalid', None, None)

    if raw.startswith(_BOOK_PREFIX):
        if content_type != 'books':
            return ('invalid', None, None)
        rest = raw[len(_BOOK_PREFIX):]
        if not rest:
            return ('invalid', None, None)
        if _RELEASE_SEGMENT in rest:
            book_id, release_id = rest.split(_RELEASE_SEGMENT, 1)
            if not book_id or not release_id:
                return ('invalid', None, None)
            return ('book', book_id, release_id)
        return ('book', rest, None)

    if raw.startswith(_PERSON_PREFIX):
        if content_type != 'authors':
            return ('invalid', None, None)
        person_id = raw[len(_PERSON_PREFIX):]
        if not person_id:
            return ('invalid', None, None)
        return ('person', person_id, None)

    match = _LEGACY_ASIN_RE.match(raw)
    if match:
        asin = match.group(1).upper()
        return ('legacy', asin, None)

    return ('invalid', None, None)


def serialize_book_id(book_id, release_id=None):
    """
        Serializes a book ID: 'book.<id>' or 'book.<id>.release.<id>'.
    """
    if not book_id:
        return None
    if release_id:
        return _BOOK_PREFIX + book_id + _RELEASE_SEGMENT + release_id
    return _BOOK_PREFIX + book_id


def serialize_person_id(person_id):
    """
        Serializes a person ID: 'person.<id>'.
    """
    if not person_id:
        return None
    return _PERSON_PREFIX + person_id
