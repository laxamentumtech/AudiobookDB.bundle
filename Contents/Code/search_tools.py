# -*- coding: utf-8 -*-
import re
import unicodedata

# Import internal tools
from logging import Logging
import api_client
import asin_tools
import metadata_ids
from credits import collect_role_credits

# Setup logger
log = Logging()

# Py2/py3 urllib compat (filename unquoting)
try:
    import urllib.parse as url_parse
except ImportError:  # pragma: no cover - python 2
    import urllib as url_parse

# The legacy agent's bundle identifier. A stored GUID only qualifies as
# migration evidence when it belongs to this agent.
AUDNEXUS_AGENT = 'com.plexapp.agents.audnexus'

YEAR_PREFIX = re.compile(r'\A\s*(\d{4})')

# A trailing bracketed volume marker ((Vol.1), [Volume 3], {Volume 3}, ...).
# The capture group keeps the volume text so normalize_name can unbracket
# it (scoring evidence) while the API query drops it (the search API reads
# "Vol. N" as a volume-pattern filter that drops books cataloged as
# "Book N"). Only a flush-trailing marker is an edition tag; volume text
# woven into the title (e.g. "The History (Vol. 1) of the Civil War") is
# kept. QUERY_VOLUME also removes a bare trailing "Vol. N" left after
# unbracketing, since the API filter fires on the text, not the brackets.
VOLUME_TAG = r'vol(?:ume)?\.?\s*\d+'
# group 1 = the full marker text ("Vol.1"): normalize_name's unbracket
# keeps it as scoring evidence. group 2 = the number: the hint's
# contradiction check needs it.
VOLUME_MARKER = re.compile(
    r'[\[\({]\s*(vol(?:ume)?\.?\s*(\d+))\s*[\]\)}]\s*\Z', re.IGNORECASE)
QUERY_VOLUME = re.compile(
    r'[\[\({]\s*' + VOLUME_TAG + r'\s*[\]\)}]\s*\Z|\s+' + VOLUME_TAG
    + r'\s*\Z', re.IGNORECASE)
# A bare trailing volume number ("... Vol. 1"): the query cleanup strips
# it, so the hint's contradiction check reads it from the raw name when
# book_number finds none (book_number deliberately ignores volume
# suffixes).
BARE_VOLUME_NUMBER = re.compile(
    r'\s+' + VOLUME_TAG + r'\s*\Z', re.IGNORECASE)

# Stream language codes map to the catalog's display names
# (release language.name) so the two can be compared softly.
STREAM_LANGUAGE_NAMES = {
    'en': 'English', 'eng': 'English',
    'de': 'German', 'deu': 'German', 'ger': 'German',
    'fr': 'French', 'fra': 'French', 'fre': 'French',
    'it': 'Italian', 'ita': 'Italian',
    'es': 'Spanish', 'spa': 'Spanish',
    'ja': 'Japanese', 'jpn': 'Japanese',
}


def release_year(release):
    """
        Year of an explicitly identified release, or None.
    """
    if not isinstance(release, dict):
        return None
    value = release.get('releaseDate')
    if not value:
        return None
    try:
        match = YEAR_PREFIX.match(value)
    except TypeError:
        # A non-text releaseDate (e.g. a bare year number) has no year.
        return None
    if match:
        return int(match.group(1))
    return None


# Longest rendered edition tag. narrator_label reserves the suffix
# verbatim and shortens the title first, so an unbounded publisher would
# crowd the book title out of the row.
EDITION_TAG_LIMIT = 24


def bounded_tag(value):
    """
        Rendered, length-bounded form of an edition-tag candidate, or
        None when the value has no text.
    """
    text = unicode_text(value)
    if text is None:
        text = u'%s' % value
    text = text.strip()
    if not text:
        return None
    if len(text) <= EDITION_TAG_LIMIT:
        return text
    return text[:EDITION_TAG_LIMIT - 2] + u'..'


def release_publisher(release):
    """
        First usable publisher credited on a release, or None. The
        credited name wins so the display matches the release's own
        credit line. The API returns a ``publishers`` list; older payloads
        carry one ``publisher`` object.
    """
    if not isinstance(release, dict):
        return None
    publishers = release.get('publishers')
    if not isinstance(publishers, list):
        publishers = []
    for publisher in publishers + [release.get('publisher')]:
        if not isinstance(publisher, dict):
            continue
        for key in ('creditedName', 'name'):
            name = unicode_text(publisher.get(key))
            if name and name.strip():
                return name.strip()
    return None


def edition_tags(releases):
    """
        Fix Match edition tags for the visible recording rows.

        The release disambiguation is the tag. A tag two visible rows
        share (for example two 'unabridged' releases) cannot tell them
        apart, so each row gets its release publisher, or its release
        year when no publisher is credited. Rows that still collide get a
        numbered tag, so every row stays distinguishable and selectable.
    """
    tags = []
    for index, release in enumerate(releases):
        tag = unicode_text(release.get('disambiguation')) \
            if isinstance(release, dict) else None
        # A long disambiguation must not push the book title out of the
        # row, so it gets the same bound as the detail tags.
        if tag and len(tag) > EDITION_TAG_LIMIT:
            tag = bounded_tag(tag)
        tags.append(tag or u'%d' % (index + 1))
    # Group by the tag text that renders, in first-seen order.
    groups = []
    group_index = {}
    for index, tag in enumerate(tags):
        if tag not in group_index:
            group_index[tag] = len(groups)
            groups.append([tag, []])
        groups[group_index[tag]][1].append(index)
    used = set(tags)
    for tag, indices in groups:
        if len(indices) < 2:
            continue
        # The group's reservations commit to `used` only if the whole
        # group lands; a group that falls back to numbered tags leaves no
        # stale claim for the next group to trip over.
        replacements = []
        taken = set()
        for index in indices:
            release = releases[index]
            detail = release_publisher(release) or release_year(release)
            candidate = bounded_tag(detail) if detail else None
            if not candidate or candidate in used or candidate in taken:
                replacements = None
                break
            taken.add(candidate)
            replacements.append((index, candidate))
        if replacements is not None:
            used.update(taken)
            for index, candidate in replacements:
                tags[index] = candidate
            continue
        # Nothing unique separates the rows: number them. The position
        # suffix counts against the limit, so the base is bounded to fit
        # the final text, not just the base.
        base = bounded_tag(tag)
        position = 1
        for index in indices:
            suffix = u' (%d)' % position
            if base is not None \
                    and len(base) + len(suffix) > EDITION_TAG_LIMIT:
                base = base[:EDITION_TAG_LIMIT - len(suffix)]
            candidate = u'%s%s' % (base, suffix)
            while candidate in used:
                position += 1
                suffix = u' (%d)' % position
                if base is not None \
                        and len(base) + len(suffix) > EDITION_TAG_LIMIT:
                    base = base[:EDITION_TAG_LIMIT - len(suffix)]
                candidate = u'%s%s' % (base, suffix)
            used.add(candidate)
            tags[index] = candidate
            position += 1
    return tags


def image_thumb(image):
    """
        Small derivative URL for a catalog image, or None.

        The image URL is data from the API, so the composed derivative is
        re-validated before it is handed to Plex.
    """
    if not isinstance(image, dict):
        return None
    url = image.get('url')
    if not url:
        return None
    thumb = url.rstrip('/') + '/small.jpg'
    if api_client.trusted_image_url(thumb):
        return thumb
    return None


def first_image_thumb(images):
    if not images:
        return None
    for image in images:
        thumb = image_thumb(image)
        if thumb:
            return thumb
    return None


def book_thumb(book):
    """
        First usable small cover derivative for a book summary.
    """
    thumb = image_thumb(book.get('coverImage'))
    if thumb:
        return thumb
    return first_image_thumb(book.get('images'))


def language_name(value):
    """
        Normalizes a stream language code or name to a catalog name.
    """
    if not value:
        return None
    key = value.strip().lower()
    if not key:
        return None
    if key in STREAM_LANGUAGE_NAMES:
        return STREAM_LANGUAGE_NAMES[key]
    for name in STREAM_LANGUAGE_NAMES.values():
        if name.lower() == key:
            return name
    return value.strip()


def release_narrators(release):
    """
        Complete ordered narrator-name list for one release. Name-only
        credits are kept; person IDs are used for deduplication when present.
    """
    credits = collect_role_credits(
        release.get('people'), 'release', release.get('id'), 'Narrator')
    return [credit['name'] for credit in credits]


def book_narrators(book, release_id=None):
    releases = book.get('releases') or []
    if release_id:
        for release in releases:
            if release.get('id') == release_id:
                return release_narrators(release)
    elif len(releases) == 1:
        return release_narrators(releases[0])
    return []


NARRATOR_SEPARATOR = {
    'de': 'mit', 'fr': 'ac', 'it': 'con', 'es': 'con', 'ja': u'\u8aad\u307f',
}

# Approximate character budget for a Fix Match result description.
DESCRIPTION_LIMIT = 60


def append_narrator(label, narrator, lang):
    if not narrator:
        return label
    return '%s %s %s' % (label, NARRATOR_SEPARATOR.get(lang, 'w/'), narrator)


class SearchTool:
    def __init__(self, content_type, lang, manual, media, prefs, results):
        self.content_type = content_type
        self.lang = lang
        self.manual = manual
        self.media = media
        self.prefs = prefs
        self.results = results

    def local_file_parts(self):
        """
            Local media parts from the scanner's tree, when PMS supplied it.
            Album trees expose parts under tracks; other levels own items.
        """
        try:
            tree = self.media.tree
        except AttributeError:
            return []
        if not tree:
            return []
        parts = []
        try:
            items = tree.items
        except AttributeError:
            items = []
        for item in items:
            parts.extend(item.parts or [])
        # The index-keyed track map can drop tracks with the same number
        # on different discs. The children list keeps every track.
        try:
            tracks = tree.children
        except AttributeError:
            tracks = []
        for track in tracks:
            for item in track.items:
                parts.extend(item.parts or [])
        return parts

    def asin_matches(self, value):
        """
            Conventional Audible ASINs in a scanner name or path.
        """
        if not value:
            return []
        try:
            value = url_parse.unquote(value)
        except Exception as e:
            log.error('Error unquoting filename for ASIN: %s', e)
        return asin_tools.file_asin_hints(value)

    def file_asins(self):
        """
            Unique ASINs hinted by the scanner: album filename plus every
            local file part. Empty when no tree or filename is available.
        """
        names = []
        if self.media.filename:
            names.append(self.media.filename)
        for part in self.local_file_parts():
            try:
                file_name = part.file
            except AttributeError:
                continue
            if file_name:
                names.append(file_name)
        asins = []
        for name in names:
            for asin in self.asin_matches(name):
                if asin not in asins:
                    asins.append(asin)
        return asins

    def shorten_label(self, label, length):
        """
            Truncates a base label to ``length`` characters, marking the
            cut with '..'. Returns the label unchanged when it already fits.
        """
        if length >= len(label):
            return label
        if length <= 2:
            return label[:length]
        return label[:length - 2] + '..'

    def narrator_label(self, label, narrators, suffix=''):
        """
            Appends the complete narrator list to a result label within the
            description budget.

            ``suffix`` (for example an edition discriminator) is reserved
            verbatim. The full label is kept when everything fits. Otherwise
            the base label is shortened just enough to leave room for the
            suffix, separator, and compacted narrator display, so the count
            stays visible. If a single narrator name alone cannot fit, the
            name is shortened too, keeping the total within the budget.
        """
        if not narrators:
            suffix = self.shorten_label(suffix, DESCRIPTION_LIMIT)
            return self.shorten_label(
                label, max(DESCRIPTION_LIMIT - len(suffix), 0)) + suffix
        separator = NARRATOR_SEPARATOR.get(self.lang, 'w/')
        # A single name is kept whole whenever it can fit at all; otherwise
        # the compact +1 marker replaces it. Multiple names are compacted
        # by format_narrators against the remaining budget.
        single_display = None
        if len(narrators) == 1:
            full_name = self.format_narrators(narrators, DESCRIPTION_LIMIT)
            # Reserve the suffix too: a name that cannot fit beside it even
            # with an empty base label is replaced by the compact count,
            # leaving room for the book title.
            max_display = DESCRIPTION_LIMIT - len(separator) - 2 \
                - len(suffix)
            single_display = full_name if len(full_name) <= max_display else '+1'
        for length in range(len(label), -1, -1):
            candidate = self.shorten_label(label, length)
            budget = DESCRIPTION_LIMIT - len(candidate) - len(suffix) \
                - len(separator) - 2
            if single_display is not None:
                display = single_display
            else:
                display = self.format_narrators(narrators, budget)
            output = append_narrator(candidate + suffix, display, self.lang)
            if len(output) <= DESCRIPTION_LIMIT:
                return output
        # Last resort: preserve the edition suffix and the explicit count,
        # shortening the suffix only when it cannot fit beside +N.
        compact = '+%d' % len(narrators)
        for length in range(len(suffix), -1, -1):
            candidate = self.shorten_label(suffix, length)
            output = append_narrator(candidate, compact, self.lang)
            if len(output) <= DESCRIPTION_LIMIT:
                return output
        return append_narrator('', compact, self.lang)

    def format_narrators(self, names, limit):
        """
            Formats the complete narrator list for the Fix Match line.

            Names are converted to initials and joined while they fit in
            ``limit`` characters. When the list does not fit, the first
            names are shown with an explicit ``+N`` count so no narrator
            silently disappears. A single name is never truncated; when no
            full name fits alongside the count, the count alone is shown.
            The complete list stays in the result data.
        """
        initials = [
            self.name_to_initials(name) for name in names if name
        ]
        if not initials:
            return ''
        full = ', '.join(initials)
        if len(full) <= limit:
            return full
        if len(initials) == 1:
            return full
        for count in range(len(initials) - 1, 0, -1):
            candidate = ', '.join(initials[:count]) + ' +%d' % (
                len(initials) - count)
            if len(candidate) <= limit:
                return candidate
        # No full name fits alongside the count: keep the count explicit
        # instead of pushing it past the description budget.
        return '+%d' % len(initials)

    def name_to_initials(self, input_name):
        """
            Converts a name to initials.
            Shorten input_name by splitting on whitespaces
            Only the surname stays as whole, the rest gets truncated
            and merged with dots.
            Example: 'Arthur Conan Doyle' -> 'A.C.Doyle'
            Example: 'J K Rowling' -> 'J.K.Rowling'
            Example: 'J. R. R. Tolkien' -> 'J.R.R.Tolkien'
        """

        # Remove quotation marks
        input_name = input_name.replace('"', '')

        # Split name into parts
        name_parts = self.clear_contributor_text(input_name).split()

        # Check if prename and surname exist, otherwise exit
        if len(name_parts) < 2:
            return input_name

        new_name = ""
        # Truncate prenames
        for part in name_parts[:-1]:
            try:
                # Try to get first letter of prename and add dot
                new_name += part[0] + "." if part[1] != "." else part
            except IndexError:
                # If there is only one letter, add dot and return
                new_name += part + "." if part != "." else part
        # Add surname
        new_name += name_parts[-1]

        return new_name

    def stored_plex_asin(self):
        """
            Legacy ASIN from the item's current Plex GUID when the item
            still carries the previous Audnexus match.

            The framework builds the media tree from the item's database
            ID, so the GUID is available without a direct PMS request.
            Only an Audnexus GUID is migration evidence: local, none, and
            foreign agent GUIDs are ignored even when their payload would
            pass the ASIN grammar.
        """
        try:
            guid = self.media.tree.guid
        except AttributeError:
            return None
        if not guid:
            return None
        identifier, separator, payload = guid.partition('://')
        if not separator or identifier != AUDNEXUS_AGENT:
            return None
        raw = payload.split('?', 1)[0]
        parsed = metadata_ids.parse_metadata_id(raw, self.content_type)
        if parsed[0] != 'legacy':
            return None
        return parsed[1]

    def stop_on_unavailable(self, asin, status):
        """
            True when an ASIN lookup came back LOOKUP_UNAVAILABLE and the
            automatic path must stop for this item: an outage must not be
            mistaken for a catalog miss, so the item is left for Fix Match
            (or a later refresh) instead of falling back to a less precise
            name search.
        """
        if status == api_client.LOOKUP_UNAVAILABLE:
            log.warn(
                'ASIN %s lookup unavailable; not falling back to a less '
                'precise match.' % asin)
            return True
        return False

    def check_for_asin(self):
        """
            Checks the stored Plex GUID, scanner filename/parts, and the
            search query for a quick-match ID: a native book./person. ID
            or a legacy ASIN.

            This is the sole appender of quick-match results: it appends
            the result(s) itself when one matches, and returns True when
            the caller must stop the normal search, False to continue. A
            stop is not always an append: the conflict and unavailable
            stops return True without appending.

            A stored Audnexus GUID is the previous agent's match. A
            confirmed miss falls through to file hints and title search.
            An unavailable lookup stops the automatic path so an outage
            cannot replace the prior match with a less precise result. A
            stored GUID that contradicts a distinct file ASIN is left for
            Fix Match.
        """
        stored_asin = None
        if not self.manual:
            stored_asin = self.stored_plex_asin()
            if stored_asin:
                log.info('ASIN found in stored Plex GUID')
                if self.content_type == 'books':
                    # A distinct file ASIN contradicts the stored match;
                    # check before appending so the conflict is not
                    # masked by a score-100 stored result.
                    distinct = [a for a in self.file_asins()
                                if a != stored_asin]
                    if distinct:
                        log.info(
                            'Stored ASIN %s conflicts with file '
                            'ASIN(s) %s; not auto-matching.' % (
                                stored_asin, ', '.join(distinct)))
                        return True
                    appended, status = self.append_quick_match_book(
                        stored_asin)
                else:
                    appended, status = self.append_quick_match_person(
                        stored_asin)
                if appended:
                    return True
                if self.stop_on_unavailable(stored_asin, status):
                    return True

        # Check scanner file hints for an ASIN if content type is books. A
        # manual (Fix Match) query takes precedence over those hints, so
        # the user can correct a wrong filename ASIN. Conflicting file
        # ASINs are ambiguous evidence: never look one up.
        if self.content_type == 'books' and not self.manual:
            asins = self.file_asins()
            if stored_asin:
                # A distinct file ASIN already stopped the automatic path
                # above, so the file carried only the ID read from the
                # stored GUID. Do not repeat that lookup.
                asins = []
            if len(asins) > 1:
                log.info('Conflicting file ASINs. Not quick-matching.')
                return False
            if asins:
                log.info('ASIN found in file metadata')
                appended, status = self.append_quick_match_book(asins[0])
                if self.stop_on_unavailable(asins[0], status):
                    return True
                return appended

        # Check search query for an ID. The album fallback also runs in
        # automatic mode when no stored or file ASIN was usable.
        manual_input = self.media.album if self.media.album \
            else self.media.artist
        if not manual_input:
            return False

        # Native-ID manual matching first
        parsed = metadata_ids.parse_metadata_id(
            manual_input, self.content_type)
        if parsed[0] == 'book':
            return self.append_quick_match_book_id(
                parsed[1], parsed[2])
        if parsed[0] == 'person':
            return self.append_quick_match_person_id(parsed[1])

        # Legacy ASIN quick match
        match = self.search_asin(manual_input)
        if match:
            asin = match.group(0).upper()
            if not self.manual and stored_asin and asin == stored_asin:
                log.info(
                    'ASIN %s was already tried from the stored Plex GUID'
                    % asin)
                return False
            log.info('ASIN found in manual search')
            if self.content_type == 'books':
                appended, status = self.append_quick_match_book(asin)
                if self.stop_on_unavailable(asin, status):
                    return True
                return appended
            # Automatic person search must not guess.
            if not self.manual:
                return False
            appended, status = self.append_quick_match_person(asin)
            if self.stop_on_unavailable(asin, status):
                return True
            return appended

        return False

    # Quick-match appenders (score 100; return (appended, lookup status))
    def append_quick_match_book(self, asin):
        """
            Resolves a legacy book ASIN and appends a score-100 result.
            Returns (appended, lookup status) so automatic migration can
            tell a confirmed catalog miss from an unavailable lookup.
        """
        book, matched_release_id, status = api_client.resolve_asin_book(asin)
        if status != api_client.LOOKUP_OK or book is None:
            if status == api_client.LOOKUP_MISSING:
                log.info('ASIN %s not in AudiobookDB catalog' % asin)
            else:
                log.warn('ASIN %s lookup unavailable' % asin)
                status = api_client.LOOKUP_UNAVAILABLE
            return (False, status)
        title = book.get('title')
        if self.manual:
            title = self.narrator_label(
                title, book_narrators(book, matched_release_id))
        year = book.get('copyright')
        thumb = book_thumb(book)
        if matched_release_id:
            for release in book.get('releases') or []:
                if not isinstance(release, dict) \
                        or release.get('id') != matched_release_id:
                    continue
                year = release_year(release) or year
                thumb = first_image_thumb(release.get('images')) or thumb
                break
        self.results.Append(
            MetadataSearchResult(
                id=metadata_ids.serialize_book_id(
                    book['id'], matched_release_id),
                lang=self.lang,
                name=title,
                score=100,
                year=year,
                thumb=thumb,
            )
        )
        return (True, api_client.LOOKUP_OK)

    def append_quick_match_book_id(self, book_id, release_id):
        """
            Validates a native book ID against the detail endpoints and
            appends a score-100 result.
        """
        book = api_client.get_book(book_id)
        if book is None:
            log.info('Book %s not found' % book_id)
            return False
        title = book.get('title')
        year = book.get('copyright')
        thumb = book_thumb(book)
        if release_id:
            release = api_client.get_release(release_id)
            if release is None:
                log.info('Release %s not found' % release_id)
                return False
            release_book_id = (release.get('book') or {}).get('id')
            if release_book_id != book.get('id'):
                log.info('Release %s does not belong to book %s' % (
                    release_id, book_id))
                return False
            if self.manual:
                title = self.narrator_label(title, release_narrators(release))
            year = release_year(release) or year
            thumb = first_image_thumb(release.get('images')) or thumb
        elif self.manual:
            title = self.narrator_label(title, book_narrators(book))
        self.results.Append(
            MetadataSearchResult(
                id=metadata_ids.serialize_book_id(book['id'], release_id),
                lang=self.lang,
                name=title,
                score=100,
                year=year,
                thumb=thumb,
            )
        )
        return True

    def append_quick_match_person(self, asin):
        """
            Resolves a legacy artist ASIN and appends score-100 result(s).
            Returns (appended, lookup status). Ambiguous matches only
            append in manual searches. A failed person-detail fetch
            propagates LOOKUP_UNAVAILABLE so the automatic path stops
            instead of falling through to a less precise match.
        """
        hits, status = api_client.resolve_asin_person(asin)
        if status != api_client.LOOKUP_OK:
            if status == api_client.LOOKUP_MISSING:
                log.info('ASIN %s not in AudiobookDB catalog' % asin)
            else:
                log.warn('ASIN %s lookup unavailable' % asin)
            return (False, status)
        if len(hits) == 0:
            log.info('ASIN %s not in AudiobookDB catalog' % asin)
            return (False, api_client.LOOKUP_MISSING)
        if len(hits) > 1:
            if not self.manual:
                log.info('ASIN %s is ambiguous (%d people)' % (
                    asin, len(hits)))
                return (False, api_client.LOOKUP_AMBIGUOUS)
            appended = False
            unavailable = False
            for hit in hits:
                ok, detail_status = self.append_person_detail(
                    hit['id'], asin)
                if ok:
                    appended = True
                elif detail_status == api_client.LOOKUP_UNAVAILABLE:
                    unavailable = True
            if appended:
                return (True, api_client.LOOKUP_OK)
            if unavailable:
                return (False, api_client.LOOKUP_UNAVAILABLE)
            return (False, api_client.LOOKUP_REJECTED)
        ok, detail_status = self.append_person_detail(hits[0]['id'], asin)
        if ok:
            return (True, api_client.LOOKUP_OK)
        return (False, detail_status)

    def person_display_name(self, person):
        """
            Appends the catalog disambiguation hint to a person's display
            name. The hint is display-only; result identity stays person.id.
        """
        name = person.get('name')
        if person.get('disambiguation'):
            return '%s (%s)' % (name, person['disambiguation'])
        return name

    def append_person_detail(self, person_id, asin=None):
        """
            Fetches a person detail, optionally confirming the Audible
            external ASIN, and appends a score-100 result.

            Returns (appended, lookup status): LOOKUP_OK when a result is
            appended, LOOKUP_REJECTED for a successful detail response
            that does not confirm the ASIN, and LOOKUP_UNAVAILABLE when
            the detail fetch itself failed (an outage must stop the
            automatic path, not fall through to a less precise match).
        """
        person, status = api_client.get_person_status(person_id)
        if person is None:
            if status == 404:
                log.info('Person %s not found' % person_id)
                return (False, api_client.LOOKUP_MISSING)
            log.warn('Person %s detail unavailable' % person_id)
            return (False, api_client.LOOKUP_UNAVAILABLE)
        if asin:
            confirmed = False
            for ext in person.get('external') or []:
                if ext.get('itemId') == asin and (
                        ext.get('category') or {}).get('title') == 'Audible':
                    confirmed = True
                    break
            if not confirmed:
                log.info('Person %s does not confirm ASIN %s' % (
                    person_id, asin))
                return (False, api_client.LOOKUP_REJECTED)
        self.results.Append(
            MetadataSearchResult(
                id=metadata_ids.serialize_person_id(person['id']),
                lang=self.lang,
                name=self.person_display_name(person),
                score=100,
                year=None,
            )
        )
        return (True, api_client.LOOKUP_OK)

    def append_quick_match_person_id(self, person_id):
        """
            Validates a native person ID against the detail endpoint and
            appends a score-100 result.
        """
        person = api_client.get_person(person_id)
        if person is None:
            log.info('Person %s not found' % person_id)
            return False
        self.results.Append(
            MetadataSearchResult(
                id=metadata_ids.serialize_person_id(person['id']),
                lang=self.lang,
                name=self.person_display_name(person),
                score=100,
                year=None,
            )
        )
        return True

    def clear_contributor_text(self, string):
        contributor_regex = '.+?(?= -)'
        if re.match(contributor_regex, string):
            return re.match(contributor_regex, string).group(0)
        return string

    def search_asin(self, input):
        """
            Searches for ASIN in a string.
        """
        if input:
            return asin_tools.typed_asin_match(input)

    def validate_author_name(self):
        """
            Checks a list of known bad author names.
            If matched, author name is set to None to prevent
            it being used in search query.
        """
        if self.content_type == 'authors':
            self.get_primary_author()

        strings_to_check = [
            "[Unknown Artist]"
        ]
        for test_name in strings_to_check:
            if self.media.artist == test_name:
                self.media.artist = None
                log.info(
                    "Artist name seems to be bad, "
                    "not using it in search."
                )
                break


class AlbumSearchTool(SearchTool):
    # Avoid fetching live release schedules or fields unused for matching.
    SEARCH_FIELDS = ['id', 'title', 'subtitle', 'people', 'seriesWithId',
                     'image']

    def parent_author_id(self):
        """
            Native person ID from the album's parent artist, or None.
        """
        try:
            raw = self.media.parent_metadata.id
        except AttributeError:
            return None
        parsed = metadata_ids.parse_metadata_id(raw, 'authors')
        if parsed[0] == 'person':
            return parsed[1]
        return None

    def build_search_body(self):
        # normalize_name keeps volume text (unbracketed) as scoring
        # evidence; the API query drops it so the API's volume-pattern
        # filter does not hide "Book N" catalog entries.
        query = QUERY_VOLUME.sub(' ', self.normalize_name())
        query = ' '.join(query.split())
        artist = (self.media.artist or '').strip()
        if not query:
            return None
        short_query = len(query) < api_client.MIN_QUERY_LENGTH
        body = {'q': query, 'type': 'books'}
        # A native parent person ID is authoritative author evidence. An
        # exact name filter can hide the right work when local and catalog
        # credit spellings differ, so a full-length title is searched
        # without it. Short titles need the filter to be accepted at all.
        if short_query:
            if not artist:
                return None
            body['filters'] = {'person': artist, 'role': 'Author'}
        elif artist and not self.parent_author_id():
            body['filters'] = {'person': artist, 'role': 'Author'}
        return body

    def releases_for_book(self, book_id):
        """
            Release dicts that belong to one book, [] when the detail is
            unusable. The single GET supplies the manual-edition rows; the
            original dicts are returned unchanged so renderers keep every
            field (people, images, language, disambiguation).
        """
        if not book_id:
            return []
        book = api_client.get_book(book_id, include='releases')
        if not book:
            return []
        # A merged book 301s to the canonical winner; releases reference
        # the winner's id, so the response's id is the comparison key.
        canonical_id = book.get('id') or book_id
        releases = []
        seen = []
        for release in book.get('releases') or []:
            if not isinstance(release, dict) or not release.get('id'):
                continue
            release_book_id = (release.get('book') or {}).get('id')
            if release_book_id and release_book_id != canonical_id:
                continue
            if release['id'] in seen:
                continue
            seen.append(release['id'])
            releases.append(release)
        return releases

    def recording_hints(self):
        """
            Soft recording hints: (total track duration in ms, release
            language name). Either side is None when the tree does not
            expose a complete, consistent signal.
        """
        return (self.track_duration_ms(), self.file_language_name())

    def track_duration_ms(self):
        """
            Sum of every track duration, None when any is missing.
        """
        try:
            tracks = self.media.tree.children
        except AttributeError:
            return None
        if not tracks:
            return None
        total = 0
        for track in tracks:
            try:
                duration = int(track.duration)
            except (AttributeError, TypeError, ValueError):
                return None
            if duration <= 0:
                return None
            total += duration
        return total

    def stream_language_name(self, stream):
        try:
            code = stream.languageCode
        except AttributeError:
            code = None
        key = None
        if code:
            key = code.strip().lower()
        if key in STREAM_LANGUAGE_NAMES:
            return STREAM_LANGUAGE_NAMES[key]
        try:
            label = stream.language
        except AttributeError:
            label = None
        name = language_name(label)
        if name:
            return name
        # A display label carried in the code field (e.g. 'English') is a
        # usable hint; an unmapped code (e.g. 'und') is not.
        if key:
            for name in STREAM_LANGUAGE_NAMES.values():
                if name.lower() == key:
                    return name
        return None

    def file_language_name(self):
        """
            Consistent audio stream language across all local parts, or
            None when none is exposed, one is missing, or they disagree.
        """
        names = []
        for part in self.local_file_parts():
            try:
                streams = part.streams or []
            except AttributeError:
                return None
            found_audio = False
            for stream in streams:
                try:
                    stream_type = str(stream.type)
                except AttributeError:
                    continue
                if stream_type != '2':
                    continue
                found_audio = True
                name = self.stream_language_name(stream)
                if not name:
                    return None
                if name not in names:
                    names.append(name)
            if not found_audio:
                return None
        if len(names) != 1:
            return None
        return names[0]

    def normalize_name(self):
        """
            Normalizes the album name by removing
            unwanted characters and words.
        """
        input_name = self.media.album or self.media.title or ''

        def strip_bracket_tag(match):
            # Keep a bracketed book number (e.g. [Book 2]) as scoring
            # evidence, unbracketed, so the trailing digit stays visible
            # to the book-number conflict check; keep a bracketed volume
            # marker the same way (mid-title volume text is title
            # evidence, and the API query drops it); strip every other
            # bracketed tag (e.g. [2017], [Book Club],
            # [Book 2 - Unabridged] — a mixed tag is not a pure
            # book-number tag).
            bracket = match.group(0)
            inner = bracket.strip('[]')
            if re.match(r'\s*book\s+\d+\s*$', inner, re.IGNORECASE):
                return ' ' + inner + ' '
            if re.match(r'\s*' + VOLUME_TAG + r'\s*$', inner,
                        re.IGNORECASE):
                return ' ' + inner + ' '
            return ' '

        # A trailing bracketed volume marker is an edition tag for the
        # API query, but the volume text is scoring evidence for local
        # matching (a catalog title "Saga One (Vol. 2)" must stay
        # distinct from "Saga One"), so it is unbracketed here and
        # stripped from the query by AlbumSearchTool.query.
        # A leading space keeps the volume text separated from the
        # preceding title word (unspaced input like "Saga(Vol.1)") and
        # lets the query cleanup see a removable marker.
        name = VOLUME_MARKER.sub(r' \1', input_name)
        name = re.sub(r'\[[^\]]*\]', strip_bracket_tag, name)
        name = re.sub(r'\(\s*(?:unabridged|abridged|audiobook)\s*\)',
                      ' ', name, flags=re.IGNORECASE)
        name = re.sub(r'\s+audiobook\s*$', '', name, flags=re.IGNORECASE)
        self.normalizedName = ' '.join(name.split())
        return self.normalizedName

    def parse_api_response(self, api_response):
        """
            Collects keys used for each item from API response,
            for Plex search results.
        """
        search_results = []
        for item in api_response:
            # A title must be nonempty usable text: a numeric title
            # (e.g. 1984) or an empty string reaches rendering and breaks
            # len()/substring work or drops the key, so it is rejected
            # here, not downstream.
            if not isinstance(item, dict) or not item.get('id') \
                    or not unicode_text(item.get('title')):
                continue
            authors = collect_role_credits(
                item.get('people'), 'book', item['id'], 'Author')
            narrator = collect_role_credits(
                item.get('people'), 'book', item['id'], 'Narrator')
            search_results.append({
                'book_id': metadata_ids.serialize_book_id(item['id']),
                'author': authors,
                'narrator': narrator,
                'title': item['title'],
                'subtitle': item.get('subtitle'),
                'series': item.get('seriesWithId') or [],
                'thumb': image_thumb(item.get('image')),
            })
        return search_results

    def pre_search_logging(self):
        """
            Logs basic metadata before search.
        """
        log.separator(msg='ALBUM SEARCH', log_level="info")
        # Log basic metadata
        data_to_log = [
            {'ID': self.media.parent_metadata.id},
            {'Title': self.media.title},
            {'Name': self.media.name},
            {'Album': self.media.album},
            {'Artist': self.media.artist},
        ]
        log.metadata(data_to_log)
        log.separator(log_level="info")

        # Handle a couple of edge cases where
        # album search will give bad results.
        if self.media.album is None and not self.manual:
            if self.media.title:
                log.warn('Using track title since album title is missing.')
                self.media.album = self.media.title
                return True
            log.info('Album Title is NULL on an automatic search.  Returning')
            return None
        if self.media.album == '[Unknown Album]' and not self.manual:
            log.info(
                'Album Title is [Unknown Album]'
                ' on an automatic search.  Returning'
            )
            return None

        if self.manual:
            # If this is a custom search,
            # use the user-entered name instead of the scanner hint.
            if self.media.name:
                log.info(
                    'Custom album search for: ' + self.media.name
                )
                self.media.album = self.media.name
        return True


class ArtistSearchTool(SearchTool):
    def build_search_body(self):
        """
            Builds the search body for the API call.
            Returns None when there is nothing to search for.
        """
        modified_artist_name = self.cleanup_author_name(self.media.artist)
        if not modified_artist_name \
                or len(modified_artist_name) < api_client.MIN_QUERY_LENGTH:
            return None
        return {'q': modified_artist_name, 'type': 'people'}

    def cleanup_author_name(self, name):
        """
            Cleans up the author name by removing
            unwanted characters and words.
        """
        log.debug('Artist name before cleanup: ' + name)

        # Remove brackets and text inside
        name = re.sub(r'\[[^"]*\]', '', name)
        # Remove certain strings, such as titles
        str_to_remove = [
            'Dr.',
            'EdD',
            'Prof.',
            'Professor',
        ]
        str_to_remove_regex = re.compile(
            '|'.join(map(re.escape, str_to_remove))
        )
        name = str_to_remove_regex.sub('', name)
        # Remove periods between double initials
        initials_regex = "^((?:[A-Z]\.\s?)*[A-Z]\.(?!\S)).(\w+)"
        initials_matched = re.search(initials_regex, name)
        if initials_matched:
            log.debug('Found initials to clean')
            cleaned_initials = (
                initials_matched.group(1)
                .replace(' ', '')
                .replace('.', ' ')
            )
            name = cleaned_initials + ' ' + initials_matched.group(2)

        log.debug('Artist name after cleanup: ' + name)
        return name

    def find_non_contributor(self, author_array):
        """
            Finds the first author in the list
            that is not a contributor.
        """
        # Go through list of artists until we find a non contributor
        for i, r in enumerate(author_array):
            if self.clear_contributor_text(r) != r:
                log.debug('Author #' + str(i+1) + ' is a contributor')
                # If all authors are contributors use the first
                if i == len(author_array) - 1:
                    log.debug(
                        'All authors are contributors, using the first one'
                    )
                    self.media.artist = self.clear_contributor_text(
                        author_array[0]
                    )
                    return
                continue
            log.info(
                'Merging multi-author "' +
                self.media.artist +
                '" into top-level author "' +
                r + '"'
            )
            self.media.artist = r
            return

    def handle_multi_artist(self):
        """
            Handles multi-artist lists.
        """
        author_array = self.media.artist.split(', ')
        if len(author_array) > 1:
            self.find_non_contributor(author_array)
        else:
            if (
                self.clear_contributor_text(self.media.artist)
                !=
                self.media.artist
            ):
                log.debug('Stripped contributor tag from author')
                self.media.artist = self.clear_contributor_text(
                    self.media.artist
                )

    def get_primary_author(self):
        """
            Checks for combined authors
            If matched, author name is set to None to prevent
            it being used in search query.
        """
        self.set_media_artist()

        # We need an author name to continue
        if not self.media.artist:
            return

        # Handle multi-artist
        self.handle_multi_artist()

    def parse_api_response(self, api_response):
        """
            Collects keys used for each item from API response,
            for Plex search results.
        """
        search_results = []
        for item in api_response:
            # Only append results which have valid keys
            if isinstance(item, dict) and \
                    set(item.keys()) >= {'id', 'name'}:
                search_results.append(
                    {
                        'id': metadata_ids.serialize_person_id(item['id']),
                        'name': item['name'],
                        'description': item.get('description'),
                        'disambiguation': item.get('disambiguation'),
                        'genres': item.get('genres'),
                    }
                )
        return search_results

    def set_media_artist(self):
        """
            Sometimes artist isn't set but title is.
        """
        if self.media.title:
            self.media.artist = self.media.title
        else:
            log.error("No artist to validate")


# Interpret only a trailing bare number or "Book N". Years, edition packs,
# ranges and fractional positions in titles are not single book numbers.
BOOK_NUMBER = re.compile(r'^(.+?)[\s,:]+(?:book\s*#?\s*)?([0-9]{1,3})$',
                         re.IGNORECASE)
NON_BOOK_SUFFIX = re.compile(u'(?:\\b(?:vol\\.?|volume|pack|to|through|and|books)'
                             u'\\s*\\.?$|[0-9]\\s*[-&./:\u2013\u2014]+\\s*$)',
                             re.IGNORECASE)

try:
    TEXT_TYPE = unicode
except NameError:  # pragma: no cover - python 3
    TEXT_TYPE = str

try:
    BYTES_TYPE = bytes
except NameError:  # pragma: no cover - python 2
    BYTES_TYPE = str


def unicode_text(value):
    if isinstance(value, TEXT_TYPE):
        return value
    if isinstance(value, BYTES_TYPE):
        return value.decode('utf-8', 'replace')
    # Malformed catalog data (e.g. a numeric series title) must degrade
    # to unknown, not raise.
    return None


def match_text(value):
    text = unicode_text(value)
    if text is None:
        return u''
    return re.sub(r'[\W_]+', '', text.lower(), flags=re.UNICODE)


def phrase_key(value):
    """
        Accent-folded, lower-cased phrase for whole-token containment:
        separators (punctuation, underscores) become single spaces, so
        'Foo-Bar', 'Foo_Bar' and 'Foo Bar' compare equal while 'Foobar'
        does not. Unicode word semantics keep non-Latin letters (Cyrillic,
        Japanese, ...) as letters in Python 2. None when the value is not
        usable text.
    """
    text = unicode_text(value)
    if text is None:
        return None
    return re.sub(r'[\W_]+', ' ', fold_accents(text).lower(),
                  flags=re.UNICODE).strip()


def fold_accents(value):
    """
        Strips combining marks (NFKD decomposition) so accented and
        unaccented spellings compare equal in the book-number stem check.
        The original title is never altered; this is a comparison key only.
    """
    text = unicode_text(value)
    if text is None:
        return u''
    decomposed = unicodedata.normalize('NFKD', text)
    # Index, do not iterate: Plex compiles a for/comprehension over a value
    # into x.__iter__(), and Python 2 unicode has no __iter__ (plain Python
    # 2 iterates text through the sequence protocol, so tests in a plain
    # interpreter miss it).
    stripped = []
    for index in range(len(decomposed)):
        char = decomposed[index]
        if not unicodedata.combining(char):
            stripped.append(char)
    return u''.join(stripped)


def book_number(title):
    title = unicode_text(title)
    if title is None:
        return u'', None
    match = BOOK_NUMBER.match(title)
    if match:
        stem = match.group(1).rstrip()
        if not NON_BOOK_SUFFIX.search(stem) and not re.search(
                r'[0-9][.,:]\s*[0-9]+$', title):
            return match_text(stem), int(match.group(2))
    return match_text(title), None


def book_number_key(title):
    """
        (accent-folded stem, number) for the book-number comparison.
        Folding is scoped to this key; the title itself is unchanged.
    """
    stem, number = book_number(title)
    return fold_accents(stem), number


def integral_number(value):
    """
        The integral value of a finite number, or None. Fractional and
        non-finite values are unknown, never integer book numbers.
    """
    if value != value or value in (float('inf'), float('-inf')):
        return None
    if value != int(value):
        return None
    return int(value)


def position_number(value):
    """
        Integral numeric value from a structured series position or legacy
        ordinal. Fractional, non-finite and malformed values return None.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, float):
        return integral_number(value)
    if isinstance(value, (str, TEXT_TYPE)):
        text = value.strip()
        if re.match(r'^[0-9]+$', text):
            return int(text)
        match = re.match(r'^([0-9]+)\.([0-9]+)$', text)
        if match:
            # Check the fractional digits exactly: float('1.0000000000000001')
            # rounds to 1.0, which would turn a fractional position into an
            # integer contradiction.
            if match.group(2).strip('0'):
                return None
            return int(match.group(1))
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def conflicts_with_book_number(query, candidate):
    stem, number = book_number(query)
    if not stem or number is None:
        return False
    # The comparison key folds accents so an accented stem (Canción) and
    # its unaccented spelling (Cancion) match; the raw titles used for the
    # API request and display are left untouched.
    query_key = fold_accents(stem)
    title_key, title_number = book_number_key(candidate['title'])
    if title_key == query_key and title_number == number:
        return False

    # Only use positions for a series named by the input. The first sort
    # ordinal is not enough to decide whether an omnibus includes a book.
    has_conflict = False
    has_unknown = False
    for series in candidate.get('series') or []:
        if not isinstance(series, dict):
            continue
        # Strip and fold both sides, mirroring the old match_text
        # comparison: a prefixed series title (The Saga) is the same
        # series as a bare stem (Saga), and accents are folded.
        if match_text(
                fold_accents(book_number_key(
                    series.get('title') or '')[0])) != query_key:
            continue
        position = series.get('position')
        if position is None or position == {}:
            # Legacy membership: a numeric ordinal is the only position.
            ordinal = position_number(series.get('ordinal'))
            if ordinal is None:
                has_unknown = True
            elif ordinal == number:
                return False
            else:
                has_conflict = True
            continue
        if not isinstance(position, dict):
            has_unknown = True
            continue
        # Spans are authoritative only for a complete position; malformed,
        # reversed or partial spans are never evidence for a hit.
        usable_spans = []
        for span in position.get('spans') or []:
            if not isinstance(span, dict):
                continue
            start = position_number(span.get('start'))
            end = position_number(span.get('end'))
            if start is None or end is None or start > end:
                continue
            usable_spans.append((start, end))
        if position.get('status') == 'complete':
            for start, end in usable_spans:
                if start <= number <= end:
                    return False
            if usable_spans:
                has_conflict = True
            else:
                has_unknown = True
        else:
            # Explicit absent/partial/unparsed position data is unknown,
            # not support and not a contradiction.
            has_unknown = True
    if has_conflict:
        return True
    # An explicit number on the same title stem is a contradiction even when
    # a membership position is unknown; support already returned above.
    if title_key == query_key and title_number is not None:
        return True
    if has_unknown:
        return False
    if title_key == query_key:
        return number > 1
    return False


# Minimum letters/digits (separators excluded) for a series title to count
# as a Fix Match name hint; shorter names are too common to be evidence.
SERIES_HINT_MIN_CHARS = 6


def series_title_text(series):
    """
        The series title as usable text, or None for a malformed
        membership entry.
    """
    if not isinstance(series, dict):
        return None
    return unicode_text(series.get('title'))


def series_name_in_text(name, text):
    """
        True when the series title appears in ``text`` as a contiguous
        whole-token phrase: accent-folded, case-insensitive, with
        punctuation and underscores treated as separators. One qualifying
        membership is all the hint needs; nothing stacks.
    """
    if not name or not text:
        return False
    name_key = phrase_key(name)
    if not name_key:
        return False
    if len(re.sub(r'\s', '', name_key)) < SERIES_HINT_MIN_CHARS:
        return False
    text_key = phrase_key(text)
    if not text_key:
        return False
    # Padding makes containment a token-boundary test, so a short series
    # title cannot match inside a longer word.
    return ' ' + name_key + ' ' in ' ' + text_key + ' '


def series_supports_number(series, number):
    """
        Position evidence from one membership for a requested book
        number: True when it supports, False when it contradicts, None
        when the membership carries no usable position.

        A book-number conflict withholds the name hint: a series name is
        evidence for the series, not for a particular volume.
    """
    if number is None:
        return None
    position = series.get('position')
    if position is None or position == {} or not isinstance(position, dict):
        # Legacy membership: a numeric ordinal is the only position.
        ordinal = position_number(series.get('ordinal'))
        if ordinal is None:
            return None
        return ordinal == number
    if position.get('status') != 'complete':
        # Explicit absent/partial/unparsed position data is unknown, not
        # support and not a contradiction.
        return None
    # A complete position speaks only through its usable spans, mirroring
    # the conflict check: usable spans that miss the number contradict
    # it; an empty or malformed span set is unknown.
    spans = position.get('spans')
    if not isinstance(spans, list):
        return None
    usable = False
    for span in spans:
        if not isinstance(span, dict):
            continue
        start = position_number(span.get('start'))
        end = position_number(span.get('end'))
        if start is None or end is None or start > end:
            continue
        usable = True
        if start <= number <= end:
            return True
    if usable:
        return False
    return None


def requested_book_number(name):
    """
        The book number the local album name asks for: the number from
        ``book_number`` (a trailing bare number or "Book N"), else the
        number of a trailing bracketed volume marker ("(Vol.1)",
        "[Volume 2]", "{Volume 3}"). The query cleanup drops the marker,
        so the hint reads it from the raw name. None when the name
        carries no usable number.
    """
    number = book_number(name)[1]
    if number is not None:
        return number
    text = unicode_text(name)
    if text is None:
        return None
    match = VOLUME_MARKER.search(text)
    if match:
        return position_number(match.group(2))
    # A bare trailing volume number the query will strip.
    match = BARE_VOLUME_NUMBER.search(text)
    if match:
        return position_number(re.search(r'\d+', match.group(0)).group(0))
    return None


def series_hint_eligible(name, candidate):
    """
        Fix Match hint eligibility: a qualifying series-name match in the
        local album name that no matching membership's position
        contradicts. Every matching membership is checked, so a
        contradiction later in the list still withholds the hint.
        Unknown positions never block it.
    """
    if not name:
        return False
    memberships = candidate.get('series')
    if not isinstance(memberships, list):
        return False
    number = requested_book_number(name)
    matched = False
    for series in memberships:
        title = series_title_text(series)
        if title is None:
            continue
        if not series_name_in_text(title, name):
            continue
        matched = True
        if series_supports_number(series, number) is False:
            return False
    return matched


class ScoreTool:
    # Starting value for score before deductions are taken.
    INITIAL_SCORE = 100
    # Any score lower than this will be ignored.
    IGNORE_SCORE = 45

    def __init__(self, helper, index, info, levenshtein_distance,
                 result_dict):
        self.calculate_score = levenshtein_distance
        self.disambiguation = None
        # Scoring metadata recorded by run_score_book; defaults keep the
        # artist path (run_score_author) result-free of book fields.
        self.title_score = 0
        self.series_eligible = False
        self.helper = helper
        self.index = index
        self.info = info
        self.result_dict = result_dict

    def run_score_author(self):
        self.asin = self.result_dict['id']
        self.author = self.result_dict['name']
        self.disambiguation = self.result_dict.get('disambiguation')
        self.narrator = None
        self.title = None
        self.thumb = None
        self.score_result(self.score_author(self.author))

    def run_score_book(self, relaxed_author=False):
        query = self.helper.normalizedName
        if not self.helper.manual and conflicts_with_book_number(
                query, self.result_dict):
            log.info('Skipping title with conflicting book number: %s',
                     self.result_dict['title'])
            return
        self.asin = self.result_dict['book_id']
        authors = [author['name'] for author in self.result_dict['author']]
        self.author = authors[0] if authors else ''
        self.disambiguation = None
        narrators = self.result_dict['narrator']
        self.narrator = [n['name'] for n in narrators] if narrators else []
        self.title = self.result_dict['title']
        self.thumb = self.result_dict.get('thumb')
        title_score = self.score_album(query, self.title,
                                       self.result_dict.get('subtitle'))
        author_score = 0
        if self.helper.media.artist:
            if authors:
                # A file can credit one co-author or list the whole group.
                author_score = min(self.score_author(author) for author in
                                   authors + [', '.join(authors)])
            else:
                author_score = 20
            if relaxed_author and self.helper.manual:
                author_score = min(20, author_score)
        # A catalog credit ID that matches the album's parent person is
        # positive author evidence: no name-distance penalty. A missing or
        # different ID is not evidence against the hit.
        try:
            parent_id = self.helper.parent_author_id()
        except AttributeError:
            parent_id = None
        if parent_id:
            for credit in self.result_dict['author']:
                if credit.get('id') == parent_id:
                    author_score = 0
                    break
        # Fix Match series-name hint: eligibility is decided here (the
        # raw effective album name is the hint surface) and the point is
        # applied later, only where it cannot change a title ranking. The
        # per-hit title deduction feeds the gate's tie-break.
        self.title_score = title_score
        self.series_eligible = False
        if self.helper.manual:
            self.series_eligible = series_hint_eligible(
                self.helper.media.album, self.result_dict)
        self.score_result(title_score + author_score)

    def score_create_result(self, score):
        result = {'id': self.asin, 'score': score,
                  'title_deduction': self.title_score,
                  'series_eligible': self.series_eligible}
        if self.author:
            author = self.author
            if self.disambiguation:
                author = '%s (%s)' % (self.author, self.disambiguation)
            result['author'] = author
        if self.narrator:
            result['narrator'] = self.narrator
        if self.title:
            result['title'] = self.title
        if self.thumb:
            result['thumb'] = self.thumb
        return result

    def score_result(self, deduction):
        score = self.INITIAL_SCORE - deduction - self.index
        log.info('Result #%s (%s): score %s', self.index + 1, self.asin, score)
        if score >= self.IGNORE_SCORE:
            self.info.append(self.score_create_result(score))

    def score_album(self, query, title, subtitle=None):
        if not query:
            return 50
        key = match_text(query)
        query_number = book_number(query)
        if query_number[1] is not None and query_number == book_number(title):
            return 0
        distance = self.calculate_score(key, match_text(title))
        if subtitle:
            # A catalog title or subtitle may arrive as a number or list;
            # keep the concatenation text-only, and skip a non-text
            # subtitle rather than raise.
            title_text = unicode_text(title)
            subtitle_text = unicode_text(subtitle)
            if title_text is not None and subtitle_text is not None:
                distance = min(distance, self.calculate_score(
                    key, match_text(title_text + ' ' + subtitle_text)))
        return distance * 2

    def score_author(self, author):
        artist = self.helper.media.artist
        if not artist:
            return 20
        return self.calculate_score(match_text(artist), match_text(author)) * 10
