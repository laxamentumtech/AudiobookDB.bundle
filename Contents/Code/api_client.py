import json
from time import sleep

from logging import Logging
from _version import version

# The Plex sandbox does not expose the ``bytes`` name and on Python 2
# ``str`` is bytes; resolve the type at import time.
try:
    BYTES_TYPE = bytes
except NameError:  # pragma: no cover - python 2 sandbox
    BYTES_TYPE = str

log = Logging()

BASE_URL = 'https://audiobookdb.org/api'
USER_AGENT = 'AudiobookDB.bundle/' + version + \
    ' (+https://github.com/laxamentumtech/AudiobookDB.bundle)'

# Max total attempts for any call (including the first).
MAX_ATTEMPTS = 4
DEFAULT_RETRY_AFTER = 1
# Server-supplied Retry-After values are clamped to this upper bound.
MAX_RETRY_AFTER = 60


def decode(body):
    """
        Decodes a JSON body, returning None for malformed JSON and for
        JSON:API error envelopes ({"errors": [...]}).
    """
    if body is None:
        return None
    if isinstance(body, BYTES_TYPE):
        body = body.decode('utf-8')
    if not body:
        return None
    try:
        data = json.loads(body, encoding='utf-8')
    except (ValueError, AttributeError):
        return None
    if isinstance(data, dict) and 'errors' in data:
        return None
    return data


def request_with_retries(url, method=None, headers=None, data=None):
    """
        Makes an HTTP call, retrying on failure.

        A 429 sleeps Retry-After (default 1) seconds before the next attempt;
        any other non-2xx status or transport error also retries. Returns the
        response (str()-able body plus .status/.headers) on the first 2xx, or
        None once MAX_ATTEMPTS is exhausted.
    """
    response = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        response = None
        try:
            response = HTTP.Request(
                url, method=method, headers=headers or {}, data=data,
                timeout=90, sleep=DEFAULT_RETRY_AFTER
            )
        except Exception:
            log.error('API request failed (attempt %d): %s' % (attempt, url))
            response = None

        if response is None:
            sleep(DEFAULT_RETRY_AFTER)
            continue

        try:
            status = response.status
        except AttributeError:
            status = 200
        if 200 <= status < 300:
            return response

        if status == 429:
            try:
                headers_map = response.headers or {}
            except AttributeError:
                headers_map = {}
            retry_after = DEFAULT_RETRY_AFTER
            for key in ('retry-after', 'Retry-After', 'RETRY-AFTER'):
                if key in headers_map:
                    try:
                        retry_after = int(headers_map[key])
                    except (ValueError, TypeError):
                        retry_after = DEFAULT_RETRY_AFTER
                    # Clamp: a hostile/buggy value must not abort the
                    # request (negative) or block the UI (oversized).
                    if retry_after < 0:
                        retry_after = DEFAULT_RETRY_AFTER
                    if retry_after > MAX_RETRY_AFTER:
                        retry_after = MAX_RETRY_AFTER
            log.warn('API rate limited, retrying in %d seconds: %s' % (
                retry_after, url))
            sleep(retry_after)
        else:
            log.error('API status %s (attempt %d): %s' % (
                status, attempt, url))
            sleep(DEFAULT_RETRY_AFTER)

    return None


def make_request(url):
    """
        GETs a URL and returns the decoded JSON object, or None on any
        failure (non-2xx, malformed JSON, JSON:API error envelope).
    """
    response = request_with_retries(url)
    if response is None:
        return None
    return decode(str(response))


def fetch_bytes(url):
    """
        GETs a URL and returns the raw response body (bytes), for images.
        Raises IOError once attempts are exhausted.
    """
    response = request_with_retries(url)
    if response is None:
        raise IOError('Failed to fetch: ' + url)
    # str() yields the raw body: py2 bytes (images) must stay bytes;
    # a py3 str body is re-encoded. Never UTF-8-encode image bytes.
    body = str(response)
    try:
        text_type = unicode
    except NameError:
        text_type = str
    if isinstance(body, text_type):
        body = body.encode('utf-8')
    return body


def post_json(path, body):
    """
        POSTs a JSON body to BASE_URL + path. Returns the decoded JSON
        object, or None on any failure.
    """
    url = BASE_URL + path
    headers = {
        'Content-Type': 'application/json',
        'User-Agent': USER_AGENT,
        'X-API-Key': api_key(),
    }
    response = request_with_retries(
        url, method='POST', headers=headers,
        data=json.dumps(body, ensure_ascii=True)
    )
    if response is None:
        return None
    return decode(str(response))


def api_key():
    """
        Reads the API key from the transport headers (Start() installs
        Prefs['api_key'] or 'anonymous' there).
    """
    try:
        headers = HTTP.Headers or {}
    except AttributeError:
        headers = {}
    return headers.get('X-API-Key', 'anonymous')


def resolve_asin_book(asin):
    """
        Resolves an Audible ASIN to a Book via
        /audiobooks/external/audible/{asin}.

        Returns (book, matchedReleaseId-or-None); (None, None) on 404 and on
        any other failure (the log distinguishes them).
    """
    data = make_request(
        '%s/audiobooks/external/audible/%s' % (BASE_URL, asin))
    if not isinstance(data, dict) or 'id' not in data:
        if data is None:
            log.warn('ASIN %s not resolved (404 or transport failure)' % asin)
        return (None, None)
    return (data, data.get('matchedReleaseId'))


def resolve_asin_person(asin):
    """
        Resolves an Audible author ASIN to Person hits via
        /people?external=Audible:{asin}&take=2.

        Returns the hits list (0, 1, or 2+); [] on any failure.
    """
    data = make_request(
        '%s/people?external=Audible%%3A%s&take=2' % (BASE_URL, asin))
    if not isinstance(data, list):
        return []
    return data


def get_book(book_id, include=None):
    """
        GETs /books/{id}; include appends ?include=<value>.
        Returns the decoded object or None on failure.
    """
    url = '%s/books/%s' % (BASE_URL, book_id)
    if include:
        url += '?include=' + include
    return make_request(url)


def get_release(release_id):
    """
        GETs /releases/{id}. Returns the decoded object or None on failure.
    """
    return make_request('%s/releases/%s' % (BASE_URL, release_id))


def get_person(person_id):
    """
        GETs /people/{id}. Returns the decoded object or None on failure.
    """
    return make_request('%s/people/%s' % (BASE_URL, person_id))


def search(q, type_, filters=None):
    """
        POSTs /search with body {'q': q, 'type': type_} plus 'filters' when
        given. Returns the hit array, or [] on any failure / when the query
        is shorter than 3 characters with no filters (the API 400s on
        short q).
    """
    body = {'type': type_}
    if q:
        if len(q) < 3 and not filters:
            # The API 400s on short q; skip the request entirely.
            return []
        body['q'] = q
    else:
        if not filters:
            return []
    if filters:
        body['filters'] = filters
    data = post_json('/search', body)
    if not isinstance(data, list):
        return []
    return data


def get_ratings(book_id):
    """
        GETs /items/book/{id}/ratings. Returns the chips list, [] on failure.
    """
    data = make_request(
        '%s/items/book/%s/ratings' % (BASE_URL, book_id))
    if not isinstance(data, dict):
        return []
    chips = data.get('chips')
    if not isinstance(chips, list):
        return []
    return chips
