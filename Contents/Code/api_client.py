# -*- coding: utf-8 -*-
import json
from time import sleep
import time as time_mod

try:
    import urllib.parse as url_parse
except ImportError:  # pragma: no cover - python 2
    import urlparse as url_parse

try:
    from email.utils import parsedate_tz as parse_date_tz
except ImportError:  # pragma: no cover - very old py2 stdlib
    parse_date_tz = None

import calendar

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
# Shortest free-text query the API accepts; the search builders and
# search() share this threshold so they cannot drift.
MIN_QUERY_LENGTH = 3

# Image fetches (fetch_bytes) are restricted to HTTPS on these hosts — the
# catalog's image CDN. URLs from the API are data, not instructions: anything
# else (http://, other hosts) is refused before the request is made.
ALLOWED_IMAGE_HOSTS = ('cdn.audiobookdb.org',)


def trusted_image_url(url):
    """
        True when the URL is HTTPS on an allowed image host. Unparseable
        URLs (None, bytes on py3, malformed) are rejected: urlparse raises
        for them and the exception is swallowed here.
    """
    try:
        parts = url_parse.urlparse(url)
    except (AttributeError, ValueError, TypeError):
        return False
    return parts.scheme == 'https' and \
        parts.netloc.lower() in ALLOWED_IMAGE_HOSTS


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


def retry_after_seconds(response):
    """
        Reads the Retry-After header in both valid forms — a delay-seconds
        integer and an HTTP-date (RFC 9110) — and returns how many seconds to
        wait, clamped to [0, MAX_RETRY_AFTER]. For an HTTP-date the delay is
        the time until that date (epoch - now), so a future date yields the
        server's requested interval. Negative or unparseable values fall back
        to DEFAULT_RETRY_AFTER.
    """
    try:
        headers_map = response.headers or {}
    except AttributeError:
        headers_map = {}
    raw = None
    for key in ('retry-after', 'Retry-After', 'RETRY-AFTER'):
        if key in headers_map:
            raw = headers_map[key]
            break
    if raw is None:
        return DEFAULT_RETRY_AFTER
    text = str(raw).strip()
    delay = None
    try:
        delay = int(text)
    except (ValueError, TypeError):
        # Second form: an HTTP-date, e.g. "Fri, 24 Oct 2026 08:12:00 GMT".
        if parse_date_tz is not None:
            try:
                parsed = parse_date_tz(text)
            except (TypeError, ValueError):
                parsed = None
            if parsed is not None:
                # parsed[0:9] is the (year..daylight) time tuple in GMT
                # (parsedate_tz normalizes the zone into the seconds);
                # timegm reads it as UTC, DST-safe.
                epoch = int(calendar.timegm(parsed[0:9])
                            - (parsed[9] or 0))
                delay = epoch - int(time_mod.time())
    if delay is None or delay < 0:
        delay = DEFAULT_RETRY_AFTER
    if delay > MAX_RETRY_AFTER:
        delay = MAX_RETRY_AFTER
    return delay


def request_with_retries(url, method=None, headers=None, data=None):
    """
        Makes an HTTP call, retrying on failure.

        A 429 sleeps Retry-After (default 1) seconds before the next attempt;
        any other non-2xx status or transport error also retries. Successful
        responses carry no added delay, and no sleep is performed after the
        final attempt. Returns the response (str()-able body plus
        .status/.headers) on the first 2xx, or None once MAX_ATTEMPTS is
        exhausted.
    """
    response = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        response = None
        try:
            response = HTTP.Request(
                url, method=method, headers=headers or {}, data=data,
                timeout=90
            )
        except Exception:
            log.error('API request failed (attempt %d): %s' % (attempt, url))
            response = None

        if response is None:
            if attempt < MAX_ATTEMPTS:
                sleep(DEFAULT_RETRY_AFTER)
            continue

        try:
            status = response.status
        except AttributeError:
            status = 200
        if 200 <= status < 300:
            return response

        if status == 429:
            retry_after = retry_after_seconds(response)
            log.warn('API rate limited, retrying in %d seconds: %s' % (
                retry_after, url))
        else:
            log.error('API status %s (attempt %d): %s' % (
                status, attempt, url))
            retry_after = DEFAULT_RETRY_AFTER
        if attempt < MAX_ATTEMPTS:
            sleep(retry_after)

    return None


def make_request(url):
    """
        GETs a URL and returns the decoded JSON object, or None on any
        failure (non-2xx, malformed JSON, JSON:API error envelope).

        The API key is attached per-request — only this and post_json()
        ever send it, and only to the trusted API origin.
    """
    response = request_with_retries(
        url, headers={'X-API-Key': api_key()})
    if response is None:
        return None
    return decode(str(response))


# Image redirects are followed by fetch_bytes() hop by hop, with the
# allowlist re-checked at every hop; a 3xx chain longer than this many
# hops is rejected outright.
MAX_IMAGE_REDIRECTS = 3


def location_header(response):
    """
        Returns the response's Location header value (case-insensitive
        keys), or None when absent.
    """
    try:
        headers_map = response.headers or {}
    except AttributeError:
        headers_map = {}
    for key in ('location', 'Location', 'LOCATION'):
        if headers_map.get(key):
            return headers_map[key]
    return None


def fetch_bytes(url):
    """
        GETs a URL and returns the raw response body (bytes), for images.

        The URL comes from catalog data, so it is validated first: only HTTPS
        URLs on the trusted image hosts (ALLOWED_IMAGE_HOSTS) are fetched.
        3xx responses are followed hop by hop here (not by the transport):
        every Location is resolved against the current URL and re-checked
        against the allowlist, and chains longer than MAX_IMAGE_REDIRECTS
        hops are rejected. Raises IOError for an untrusted URL, a redirect
        to an untrusted URL, a redirect loop, or a non-2xx response.

        Residual platform limitation: Plex's HTTP.Request has no option to
        disable redirect following, and on some transports the 3xx hop is
        consumed inside the transport — the final 2xx then arrives without a
        Location header, so the hop-by-hop check cannot see that redirect.
        The initial URL is always pre-validated, and any redirect the
        transport surfaces is enforced here.
    """
    if not trusted_image_url(url):
        raise IOError('Untrusted image URL: ' + str(url))
    for attempt in range(1, MAX_ATTEMPTS + 1):
        hops = 0
        while True:
            response = None
            try:
                response = HTTP.Request(
                    url, method='GET', headers={}, timeout=90
                )
            except Exception:
                log.error('Image request failed (attempt %d): %s'
                          % (attempt, url))
                response = None
            if response is None:
                break
            try:
                status = response.status
            except AttributeError:
                status = 200
            if 200 <= status < 300:
                # str() yields the raw body: py2 bytes (images) must stay
                # bytes; a py3 str body is re-encoded. Never UTF-8-encode
                # image bytes.
                body = str(response)
                try:
                    text_type = unicode
                except NameError:
                    text_type = str
                if isinstance(body, text_type):
                    body = body.encode('utf-8')
                return body
            if 300 <= status < 400:
                if hops >= MAX_IMAGE_REDIRECTS:
                    raise IOError('Too many redirects: ' + str(url))
                target = location_header(response)
                if not target:
                    raise IOError('Redirect without Location: ' + url)
                target = url_parse.urljoin(url, str(target))
                if not trusted_image_url(target):
                    raise IOError('Redirect to untrusted image URL: '
                                  + target)
                url = target
                hops += 1
                continue
            log.error('Image status %s (attempt %d): %s'
                      % (status, attempt, url))
            break
        if attempt < MAX_ATTEMPTS:
            sleep(DEFAULT_RETRY_AFTER)
    raise IOError('Failed to fetch: ' + url)


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
        Reads the API key from Prefs['api_key'] ('anonymous' when unset).

        The key is attached per-request to calls on the trusted API origin
        only; it is never a global HTTP.Headers default, so image downloads
        and off-origin requests never see it.
    """
    try:
        key = Prefs['api_key']
    except (AttributeError, KeyError):
        return 'anonymous'
    return key or 'anonymous'


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
        if len(q) < MIN_QUERY_LENGTH and not filters:
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
