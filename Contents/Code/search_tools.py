# -*- coding: utf-8 -*-
import re
import unicodedata

# Import internal tools
from logging import Logging
import api_client
import metadata_ids

# Setup logger
log = Logging()

# Py2/py3 urllib compat (filename unquoting)
try:
    import urllib.parse as url_parse
except ImportError:  # pragma: no cover - python 2
    import urllib as url_parse

# Typed lookups keep the legacy broad grammar: users may paste any
# ten-character ID-shaped token.
asin_regex = re.compile(r'(?=.\d)[A-Z\d]{10}')

# Scanner filenames are untrusted bulk input: only the conventional
# Audible ASIN (B + 9 alphanumerics) counts as an edition hint, bounded so
# a hash or hex run is never read as one.
file_asin_regex = re.compile(
    r'(?<![A-Za-z0-9])B[A-Za-z0-9]{9}(?![A-Za-z0-9])', re.IGNORECASE)

YEAR_PREFIX = re.compile(r'\A\s*(\d{4})')

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


def release_narrator(release):
    for credit in release.get('people') or []:
        if not isinstance(credit, dict):
            continue
        if (credit.get('role') or {}).get('name') == 'Narrator':
            name = ((credit.get('person') or {}).get('name') or '').strip()
            if name:
                return name
    return None


def book_narrator(book, release_id=None):
    releases = book.get('releases') or []
    if release_id:
        for release in releases:
            if release.get('id') == release_id:
                return release_narrator(release)
    elif len(releases) == 1:
        return release_narrator(releases[0])
    return None


NARRATOR_SEPARATOR = {
    'de': 'mit', 'fr': 'ac', 'it': 'con', 'es': 'con', 'ja': u'\u8aad\u307f',
}


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
        return [match.group(0) for match in file_asin_regex.finditer(value)]

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
            for match in self.asin_matches(name):
                asin = match.upper()
                if asin not in asins:
                    asins.append(asin)
        return asins

    def check_for_asin(self):
        """
            Checks filename (for books) and/or search query for a
            quick-match ID: a native book./person. ID or a legacy ASIN.

            This is the sole appender of quick-match results: it appends
            the result(s) itself and returns True when the caller must
            stop the normal search, False to continue.
        """
        # Check scanner file hints for an ASIN if content type is books. A
        # manual (Fix Match) query takes precedence over those hints, so
        # the user can correct a wrong filename ASIN. Conflicting file
        # ASINs are ambiguous evidence: never look one up.
        if self.content_type == 'books' and not self.manual:
            asins = self.file_asins()
            if len(asins) > 1:
                log.info('Conflicting file ASINs. Not quick-matching.')
                return False
            if asins:
                log.info('ASIN found in file metadata')
                return self.append_quick_match_book(asins[0])

        # Check search query for an ID
        # Default to album and use artist if no album
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
            log.info('ASIN found in manual search')
            if self.content_type == 'books':
                return self.append_quick_match_book(asin)
            # Automatic person search must not guess.
            if not self.manual:
                return False
            return self.append_quick_match_person(asin)

        return False

    # Quick-match appenders (score 100; return True when appended)
    def append_quick_match_book(self, asin):
        """
            Resolves a legacy book ASIN and appends a score-100 result.
        """
        book, matched_release_id = api_client.resolve_asin_book(asin)
        if book is None:
            log.info('ASIN %s not in AudiobookDB catalog' % asin)
            return False
        title = book.get('title')
        if self.manual:
            title = append_narrator(
                title, book_narrator(book, matched_release_id), self.lang)
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
        return True

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
                title = append_narrator(title, release_narrator(release), self.lang)
            year = release_year(release) or year
            thumb = first_image_thumb(release.get('images')) or thumb
        elif self.manual:
            title = append_narrator(title, book_narrator(book), self.lang)
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
            Ambiguous matches only append in manual searches.
        """
        hits = api_client.resolve_asin_person(asin)
        if len(hits) == 0:
            log.info('ASIN %s not in AudiobookDB catalog' % asin)
            return False
        if len(hits) > 1:
            if not self.manual:
                log.info('ASIN %s is ambiguous (%d people)' % (
                    asin, len(hits)))
                return False
            appended = False
            for hit in hits:
                if self.append_person_detail(hit['id'], asin):
                    appended = True
            return appended
        return self.append_person_detail(hits[0]['id'], asin)

    def append_person_detail(self, person_id, asin=None):
        """
            Fetches a person detail, optionally confirming the Audible
            external ASIN, and appends a score-100 result.
        """
        person = api_client.get_person(person_id)
        if person is None:
            log.info('Person %s not found' % person_id)
            return False
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
                return False
        self.results.Append(
            MetadataSearchResult(
                id=metadata_ids.serialize_person_id(person['id']),
                lang=self.lang,
                name=person.get('name'),
                score=100,
                year=None,
            )
        )
        return True

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
                name=person.get('name'),
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
            return re.search(asin_regex, input)

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
        query = self.normalize_name()
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

    def normalize_name(self):
        """
            Normalizes the album name by removing
            unwanted characters and words.
        """
        input_name = self.media.album or self.media.title or ''

        def strip_bracket_tag(match):
            # Keep a bracketed book number (e.g. [Book 2]) as scoring
            # evidence, unbracketed, so the trailing digit stays visible
            # to the book-number conflict check; strip every other
            # bracketed tag (e.g. [2017], [Book Club],
            # [Book 2 - Unabridged] — a mixed tag is not a pure
            # book-number tag).
            bracket = match.group(0)
            inner = bracket.strip('[]')
            if re.match(r'\s*book\s+\d+\s*$', inner, re.IGNORECASE):
                return ' ' + inner + ' '
            return ' '

        name = re.sub(r'\[[^\]]*\]', strip_bracket_tag, input_name)
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
            if not isinstance(item, dict) or not item.get('id') or not item.get('title'):
                continue
            authors = []
            narrator = []
            for credit in item.get('people') or []:
                if not isinstance(credit, dict):
                    continue
                person = credit.get('person')
                role = credit.get('role')
                if not isinstance(person, dict) or not isinstance(role, dict):
                    continue
                name = person.get('name')
                role_name = role.get('name')
                if not name:
                    continue
                if role_name == 'Author':
                    author = {'name': name}
                    if person.get('id'):
                        author['id'] = person['id']
                    authors.append(author)
                elif role_name == 'Narrator' and not narrator:
                    narrator = [{'name': name}]
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


def unicode_text(value):
    if isinstance(value, TEXT_TYPE):
        return value
    return value.decode('utf-8', 'replace')


def match_text(value):
    return re.sub(r'[\W_]+', '', unicode_text(value).lower(), flags=re.UNICODE)


def fold_accents(value):
    """
        Strips combining marks (NFKD decomposition) so accented and
        unaccented spellings compare equal in the book-number stem check.
        The original title is never altered; this is a comparison key only.
    """
    text = unicode_text(value)
    decomposed = unicodedata.normalize('NFKD', text)
    stripped = [char for char in decomposed
                if not unicodedata.combining(char)]
    return u''.join(stripped)


def book_number(title):
    title = unicode_text(title)
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
    for series in candidate.get('series') or []:
        # Strip and fold both sides, mirroring the old match_text
        # comparison: a prefixed series title (The Saga) is the same
        # series as a bare stem (Saga), and accents are folded.
        if match_text(
                fold_accents(book_number_key(
                    series.get('title') or '')[0])) != query_key:
            continue
        position = series.get('position') or {}
        spans = position.get('spans') or []
        for span in spans:
            start, end = span.get('start'), span.get('end')
            if start is not None and end is not None and start <= number <= end:
                return False
        if spans and position.get('status') == 'complete':
            has_conflict = True
    if has_conflict:
        return True
    if title_key == query_key:
        return title_number is not None or number > 1
    return False


class ScoreTool:
    # Starting value for score before deductions are taken.
    INITIAL_SCORE = 100
    # Any score lower than this will be ignored.
    IGNORE_SCORE = 45

    def __init__(self, helper, index, info, levenshtein_distance,
                 result_dict):
        self.calculate_score = levenshtein_distance
        self.helper = helper
        self.index = index
        self.info = info
        self.result_dict = result_dict

    def run_score_author(self):
        self.asin = self.result_dict['id']
        self.author = self.result_dict['name']
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
        narrators = self.result_dict['narrator']
        self.narrator = narrators[0]['name'] if narrators else ''
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
        self.score_result(title_score + author_score)

    def score_create_result(self, score):
        result = {'id': self.asin, 'score': score}
        if self.author:
            result['author'] = self.author
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
            distance = min(distance, self.calculate_score(
                key, match_text(title + ' ' + subtitle)))
        return distance * 2

    def score_author(self, author):
        artist = self.helper.media.artist
        if not artist:
            return 20
        return self.calculate_score(match_text(artist), match_text(author)) * 10
