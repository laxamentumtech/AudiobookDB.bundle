import re

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

asin_regex = re.compile(r'(?=.\d)[A-Z\d]{10}')

# Narrow terminal book-ordinal shapes recognised for automatic ordering
# checks. Everything else (packs, volumes, ranges, years, fractions) abstains.
ordering_range_regex = re.compile(
    u'[0-9]+\\s*(?:-|\u2013|\u2014|to)\\s*[0-9]+\\s*$', re.IGNORECASE)
ordering_fraction_regex = re.compile(r'[0-9]+\.[0-9]+\s*$')
ordering_of_regex = re.compile(
    r'[0-9]+\s+of\s+[0-9]+\s*$', re.IGNORECASE)
ordering_pack_regex = re.compile(
    r"(?:\bpack\b|\bvolume\b|\bvol\.?)\s*#?\s*[0-9]{1,3}\s*$",
    re.IGNORECASE)
ordering_book_regex = re.compile(
    r'^(.*?)(?:\s+book\s*#?\s*([0-9]{1,3}))\s*$', re.IGNORECASE)
ordering_bare_regex = re.compile(
    u'^(.*?)[\\s\\-:,\u2013\u2014_#]+([0-9]{1,3})\\s*$')


class SearchTool:
    def __init__(self, content_type, lang, manual, media, prefs, results):
        self.content_type = content_type
        self.lang = lang
        self.manual = manual
        self.media = media
        self.prefs = prefs
        self.results = results

    def check_for_asin(self):
        """
            Checks filename (for books) and/or search query for a
            quick-match ID: a native book./person. ID or a legacy ASIN.

            This is the sole appender of quick-match results: it appends
            the result(s) itself and returns True when the caller must
            stop the normal search, False to continue.
        """
        # Check filename for ASIN if content type is books. A manual
        # (Fix Match) query takes precedence over the scanner's filename
        # hint, so the user can correct a wrong filename ASIN.
        if self.media.filename and self.content_type == 'books' \
                and not self.manual:
            try:
                # Provide a plain filename for ASIN search
                filename_unquoted = url_parse.unquote(self.media.filename)
                filename_unquoted = self.search_asin(filename_unquoted)
            except Exception as e:
                log.error('Error checking filename for ASIN: %s', e)
                filename_unquoted = None

            if filename_unquoted:
                log.info('ASIN found in filename')
                return self.append_quick_match_book(
                    filename_unquoted.group(0))

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
            asin = match.group(0)
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
        self.results.Append(
            MetadataSearchResult(
                id=metadata_ids.serialize_book_id(
                    book['id'], matched_release_id),
                lang=self.lang,
                name=book.get('title'),
                score=100,
                year=book.get('copyright'),
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
        if release_id:
            release = api_client.get_release(release_id)
            if release is None:
                log.info('Release %s not found' % release_id)
                return False
            release_book_id = (release.get('book') or {}).get('id')
            if release_book_id and release_book_id != book.get('id'):
                log.info('Release %s does not belong to book %s' % (
                    release_id, book_id))
                return False
        self.results.Append(
            MetadataSearchResult(
                id=metadata_ids.serialize_book_id(book['id'], release_id),
                lang=self.lang,
                name=book.get('title'),
                score=100,
                year=book.get('copyright'),
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
    def build_search_body(self):
        """
            Builds the search body for the API call.
            Returns None when there is nothing to search for.
        """
        # First, normalize the name
        self.normalize_name()

        body = {'type': 'books'}
        filters = {}
        # Fix match/manual search doesn't provide author
        if self.media.artist:
            filters['person'] = self.media.artist
        if self.normalizedName \
                and len(self.normalizedName) >= api_client.MIN_QUERY_LENGTH:
            body['q'] = self.normalizedName
        if filters:
            body['filters'] = filters
        if 'q' not in body and not filters:
            return None
        return body

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
        # Get name from either album or title
        input_name = self.media.album if self.media.album else self.media.title
        log.debug('Input Name: %s', input_name)

        if not input_name:
            self.normalizedName = ''
            return self.normalizedName

        # Remove Diacritics
        name = String.StripDiacritics(input_name)
        # Remove brackets and text inside
        name = re.sub(r'\[[^"]*\]', '', name)
        # Remove unwanted characters
        name = re.sub(r'[^\w\s]', '', name)
        # Remove unwanted words
        name = re.sub(r'\b(official|audiobook|unabridged|abridged)\b',
                      '', name, flags=re.IGNORECASE)
        # Remove unwanted whitespaces
        name = re.sub(r'\s+', ' ', name)
        # Remove leading and trailing whitespaces
        name = name.strip()
        # Set class variable
        self.normalizedName = name
        log.debug('Normalized Name: %s', self.normalizedName)

        return name

    def parse_api_response(self, api_response):
        """
            Collects keys used for each item from API response,
            for Plex search results.
        """
        search_results = []
        for item in api_response:
            # Only append results which have valid keys
            if isinstance(item, dict) and \
                    set(item.keys()) >= {'id', 'title', 'people'}:
                authors = [
                    {'name': p['person']['name']}
                    for p in item.get('people') or []
                    if (p.get('role') or {}).get('name') == 'Author'
                ]
                narrator = []
                for p in item.get('people') or []:
                    if (p.get('role') or {}).get('name') == 'Narrator':
                        narrator = [{'name': p['person']['name']}]
                        break
                series = []
                for series_item in item.get('seriesWithId') or []:
                    if not isinstance(series_item, dict):
                        continue
                    series.append(
                        {
                            'title': series_item.get('title'),
                            'ordinal': series_item.get('ordinal'),
                            'position': series_item.get('position'),
                        }
                    )
                search_results.append(
                    {
                        'book_id': metadata_ids.serialize_book_id(
                            item['id']),
                        'author': authors,
                        'date': None,
                        'language': item.get('originalLanguage'),
                        'narrator': narrator,
                        'title': item['title'],
                        'subtitle': item.get('subtitle'),
                        'seriesWithId': series,
                    }
                )
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


class ScoreTool:
    # Starting value for score before deductions are taken.
    INITIAL_SCORE = 100
    # Any score lower than this will be ignored.
    IGNORE_SCORE = 45
    # Deduction for a candidate the folder's series ordinal contradicts.
    # INITIAL_SCORE - ORDERING_PENALTY - index stays below IGNORE_SCORE.
    ORDERING_PENALTY = 60

    def __init__(
        self,
        helper,
        index,
        info,
        locale,
        levenshtein_distance,
        result_dict,
        year=None
    ):
        self.calculate_score = levenshtein_distance
        self.helper = helper
        self.index = index
        self.info = info
        self.english_locale = locale
        self.result_dict = result_dict
        self.year = year

    def reduce_string(self, string):
        """
            Reduces a string to lowercase and removes
            punctuation and spaces.
        """
        normalized = string \
            .lower() \
            .replace('-', '') \
            .replace(' ', '') \
            .replace('.', '') \
            .replace(',', '')
        return normalized

    def run_score_author(self):
        """
            Scores an author result.
        """
        self.asin = self.result_dict['id']
        self.author = self.result_dict['name']
        self.authors_concat = self.author
        self.date = None
        self.language = None
        self.narrator = None
        self.title = None
        return self.score_result()

    def run_score_book(self):
        """
            Scores a book result.
        """
        self.asin = self.result_dict['book_id']
        authors = self.result_dict['author']
        self.authors_concat = ', '.join(
            author['name'] for author in authors
        ) if authors else ''
        self.author = authors[0]['name'] if authors else ''
        self.date = self.result_dict['date']
        self.language = (self.result_dict['language'] or '').title()
        narrators = self.result_dict['narrator']
        self.narrator = narrators[0]['name'] if narrators else ''
        self.title = self.result_dict['title']
        return self.score_result()

    def sum_scores(self, numberlist):
        """
            Sums a list of numbers.
        """
        # Because builtin sum() isn't available
        return reduce(
            lambda x, y: x + y, numberlist, 0
        )

    def score_create_result(self, score):
        """
            Creates a result dict for the score.
            Logs the score and the data used to calculate it.
        """
        data_to_log = []
        plex_score_dict = {}

        # Go through all the keys for the result and log as we go
        if self.asin:
            plex_score_dict['id'] = self.asin
            data_to_log.append({'ID is': self.asin})
        if self.author:
            plex_score_dict['author'] = self.author
            data_to_log.append({'Author is': self.author})
        if self.date:
            plex_score_dict['date'] = self.date
            data_to_log.append({'Date is': self.date})
        if self.narrator:
            plex_score_dict['narrator'] = self.narrator
            data_to_log.append({'Narrator is': self.narrator})
        if score:
            plex_score_dict['score'] = score
            data_to_log.append({'Score is': str(score)})
        if self.title:
            plex_score_dict['title'] = self.title
            data_to_log.append({'Title is': self.title})
        if self.year:
            plex_score_dict['year'] = self.year

        log.metadata(data_to_log, log_level="info")
        return plex_score_dict

    def score_result(self):
        """
            Scores a result.
        """
        # Array to hold score points for processing
        all_scores = []

        # Album name score
        if self.title:
            title_score = self.score_album(self.title)
            if title_score:
                all_scores.append(title_score)
        # Author name score
        if self.authors_concat:
            author_score = self.score_author(self.authors_concat)
            if author_score:
                all_scores.append(author_score)
        # Library language score
        if self.language:
            lang_score = self.score_language(self.language)
            if lang_score:
                all_scores.append(lang_score)
        # Series ordering score (automatic searches only)
        ordering_score = self.score_ordering()
        if ordering_score:
            all_scores.append(ordering_score)

        # Subtract difference from initial score
        # Subtract index to use relevance as weight
        score = self.INITIAL_SCORE - self.sum_scores(all_scores) - self.index

        log.info("Result #" + str(self.index + 1))

        # Create result dict
        plex_score_dict = self.score_create_result(score)

        if score >= self.IGNORE_SCORE:
            self.info.append(plex_score_dict)
        else:
            log.info(
                '# Score is below ignore boundary (%s)... Skipping!',
                self.IGNORE_SCORE
            )

    def score_album(self, title):
        """
            Compare the input album similarity to the search result album.
            Score is calculated with LevenshteinDistance
        """
        scorebase1 = self.helper.media.album
        if not scorebase1:
            log.error('No album title found in file metadata')
            return 50
        scorebase2 = title.encode('utf-8')
        album_score = self.calculate_score(
            self.reduce_string(scorebase1),
            self.reduce_string(scorebase2)
        ) * 2
        log.debug("Score deduction from album: " + str(album_score))
        return album_score

    def plain_integer(self, value):
        """
            Returns a positive ASCII integer, or None for anything else
            (floats, labels, negative or zero positions).
        """
        if isinstance(value, float):
            return None
        if isinstance(value, int):
            return value if value > 0 else None
        try:
            text = value.strip()
        except AttributeError:
            return None
        if not text:
            return None
        for index in range(len(text)):
            if text[index] not in '0123456789':
                return None
        number = int(text)
        return number if number > 0 else None

    def ordering_suffix(self, text):
        """
            Splits a supported terminal book ordinal from a title.

            Returns (stem, number), or None when the title carries no
            ordinal the scorer can reason about: packs, volumes, ranges,
            fractions, years, Roman or spelled-out numbers all abstain.
        """
        if not text:
            return None
        if ordering_range_regex.search(text) \
                or ordering_fraction_regex.search(text) \
                or ordering_of_regex.search(text) \
                or ordering_pack_regex.search(text):
            return None
        match = ordering_book_regex.match(text)
        if match is None:
            match = ordering_bare_regex.match(text)
        if match is None:
            return None
        stem = match.group(1).strip(
            u' \t-:;,._#\u2013\u2014')
        number = int(match.group(2))
        if not stem or number <= 0:
            return None
        return stem, number

    def series_position(self, entry):
        """
            Returns the complete [(start, end), ...] ranges an entry claims,
            or None when the position is unknown. Unknown data is never
            treated as a contradiction.
        """
        position = entry.get('position')
        if position is None or position == {}:
            ordinal = self.plain_integer(entry.get('ordinal'))
            if ordinal is None:
                return None
            return [(ordinal, ordinal)]
        if not isinstance(position, dict):
            return None
        status = position.get('status')
        if status and status != 'complete':
            return None
        kind = position.get('kind')
        if kind and kind not in ('point', 'range'):
            return None
        spans = position.get('spans')
        if spans:
            ranges = []
            for span in spans:
                if not isinstance(span, dict):
                    return None
                start = self.plain_integer(span.get('start'))
                end = self.plain_integer(span.get('end'))
                if start is None or end is None:
                    return None
                ranges.append((start, end))
            return ranges
        value = position.get('value')
        if value is not None:
            value_number = self.plain_integer(value)
            if value_number is None:
                return None
            return [(value_number, value_number)]
        label = position.get('label')
        if label is None or label == '':
            return None
        label_value = self.plain_integer(label)
        if label_value is None:
            return None
        return [(label_value, label_value)]

    def score_ordering(self):
        """
            Deducts when the folder's book ordinal positively contradicts
            the candidate. Manual searches are never penalised, and
            unknown or unsupported numbering data abstains.
        """
        if self.helper.manual:
            return 0
        if not self.title:
            return 0
        album_suffix = self.ordering_suffix(self.helper.media.album)
        if album_suffix is None:
            return 0
        stem, number = album_suffix
        stem_key = self.reduce_string(stem)
        if not stem_key:
            return 0

        title_suffix = self.ordering_suffix(self.title)
        if title_suffix is None:
            candidate_number = None
            candidate_key = self.reduce_string(self.title)
        else:
            candidate_stem, candidate_number = title_suffix
            candidate_key = self.reduce_string(candidate_stem)

        series_entries = []
        for entry in self.result_dict.get('seriesWithId') or []:
            if not isinstance(entry, dict):
                continue
            series_title = entry.get('title')
            if series_title and \
                    self.reduce_string(series_title) == stem_key:
                series_entries.append(entry)

        if candidate_key != stem_key and not series_entries:
            return 0

        supported = False
        contradicted = False

        # The candidate's own title number is the strongest evidence.
        if candidate_number is not None:
            if candidate_number == number:
                supported = True
            else:
                contradicted = True

        # Any relevant series membership that covers the number supports it;
        # one book can hold different positions in different series.
        for entry in series_entries:
            position = self.series_position(entry)
            if position is None:
                continue
            entry_supports = False
            for span in position:
                if span[0] <= number <= span[1]:
                    entry_supports = True
            if entry_supports:
                supported = True
            else:
                contradicted = True

        if supported:
            return 0
        if contradicted:
            log.debug(
                'Series ordering mismatch: folder book %s, candidate "%s"',
                number, self.title)
            return self.ORDERING_PENALTY
        if candidate_number is None and not series_entries and number > 1:
            log.debug(
                'Series ordering mismatch: folder book %s, unnumbered "%s"',
                number, self.title)
            return self.ORDERING_PENALTY
        return 0

    def score_author(self, author):
        """
            Compare the input author similarity to the search result author.
            Score is calculated with LevenshteinDistance
        """
        if self.helper.media.artist:
            scorebase3 = self.helper.media.artist
            scorebase4 = author
            author_score = self.calculate_score(
                self.reduce_string(scorebase3),
                self.reduce_string(scorebase4)
            ) * 10
            log.debug("Score deduction from author: " + str(author_score))
            return author_score

        log.warn('No artist found in file metadata')
        return 20

    def score_language(self, language):
        """
            Compare the library language to search results
            and knock off 2 points if they don't match.
        """
        lang_dict = {
            self.english_locale: 'English',
            'de': 'German',
            'es': 'Spanish',
            'fr': 'French',
            'it': 'Italian',
            'ja': 'Japanese',
        }

        if language != lang_dict[self.helper.lang]:
            log.debug(
                'Audible language: %s; Library language: %s',
                language,
                lang_dict[self.helper.lang]
            )
            log.debug("Book is not library language, deduct 2 points")
            return 2
        return 0
