# Import internal tools
from logging import Logging
import api_client
import metadata_ids
import re
from credits import collect_role_credits

# Setup logger
log = Logging()


class UpdateTool:
    def __init__(self, content_type, force, lang, media, metadata, prefs):
        self.content_type = content_type
        self.force = force
        self.lang = lang
        self.media = media
        self.metadata = metadata
        self.prefs = prefs
        # Parse the stored ID once; resolution branches on this 3-tuple.
        self.parsed_id = metadata_ids.parse_metadata_id(
            metadata.id, self.content_type)
        # Native IDs stashed by resolve_item for the agent's ID commit.
        self.native_book_id = None
        self.native_release_id = None
        self.native_person_id = None

    def select_release(self, book, pinned_release_id=None,
                       matched_release_id=None):
        """
            Shared release-selection precedence:
              (1) release pinned in a native ID
              (2) matchedReleaseId from an ASIN resolve
              (3) the only release in book['releases']
              (4) lexicographically lowest release id (deterministic default)
              (5) None -> work-only path
            Returns a release id or None.
        """
        releases = book.get('releases') or []
        ids = [r['id'] for r in releases]
        if pinned_release_id and pinned_release_id in ids:
            return pinned_release_id
        if matched_release_id and matched_release_id in ids:
            return matched_release_id
        if len(releases) == 1:
            return releases[0]['id']
        if releases:
            selected = min(ids)
            log.info('No matched release; defaulting to lowest release ID: %s'
                     % selected)
            return selected
        return None

    def getDateFromString(self, string):
        """
            Converts a string to a date object.
        """
        try:
            return Datetime.ParseDate(string).date()
        except AttributeError:
            return None
        except ValueError:
            return None

    def cleanup_html(self):
        """
            Cleans up HTML in either the description or synopsis.
        """
        html_tags = '<[^<]+?>'

        # Clean up HTML in the description
        if self.content_type == 'authors':
            # First handle special cases
            self.description = self.replace_html_special(self.description)
            self.description = re.sub(
                html_tags, '', self.description)
        # Clean up HTML in the synopsis
        if self.content_type == 'books':
            # First handle special cases
            self.synopsis = self.replace_html_special(self.synopsis)
            self.synopsis = re.sub(
                html_tags, '', self.synopsis)

    def replace_html_special(self, input_html):
        """
            Replaces HTML lists with a bullet point.
            Replaces HTML paragraphs with a newline.
            Replaces HTML line breaks with a newline.
        """
        return (
            input_html.replace("<ul>", "")
            .replace("</ul>", "\n")
            .replace("<ol>", "")
            .replace("</ol>", "\n")
            .replace("<li>", " \u2022 ")
            .replace("</li>", "\n")
            .replace("<br />", "")
            .replace("<p>", "")
            .replace("</p>", "\n")
            .strip()
        )

    def collect_metadata_to_log(self):
        """
            Collects the metadata to log.
        """
        # Start an array with common metadata
        data_to_log = [{'ID': self.metadata.id}]

        # Determine which metadata to log
        if self.content_type == 'books':
            data_to_log.extend(
                [
                    {'Book poster URL': self.thumb},
                    {'Book publisher': self.metadata.studio},
                    {'Book release date': str(
                        self.metadata.originally_available_at)},
                    {'Book sort title': self.metadata.title_sort},
                    {'Book summary': self.metadata.summary},
                    {'Book title': self.metadata.title},
                ]
            )
        elif self.content_type == 'authors':
            data_to_log.extend(
                [
                    {'Author bio': self.metadata.summary},
                    {'Author name': self.metadata.title},
                    {'Author poster URL': self.thumb},
                    {'Author sort name': self.metadata.title_sort},
                    {'Similar Authors': ', '.join([author['name']
                                                   for author in self.similar] if self.similar else [])},
                ]
            )

        return data_to_log

    def collect_metadata_arrs_to_log(self):
        """
            Collects the metadata arrays to log.
        """
        # Start an array with common metadata
        multi_arr = [{'Genres': self.metadata.genres}]

        # Book metadata
        book_multi_arr = [
            {'Moods (Authors)': self.metadata.moods},
            {'Styles (Narrators)': self.metadata.styles},
        ]

        # Determine which metadata to log
        if self.content_type == 'book':
            multi_arr.extend(book_multi_arr)

        return multi_arr

    def log_update_metadata(self):
        """
            Writes metadata information to log.
        """
        # Send a separator to the log
        log.separator(
            msg=(
                'FINALIZED: ' + self.metadata.title +
                ', ID: ' + self.metadata.id
            ),
            log_level="info"
        )

        # Collect metadata to log
        data_to_log = self.collect_metadata_to_log()
        log.metadata(data_to_log, log_level="info")

        # Collect metadata arrays to log
        multi_arr = self.collect_metadata_arrs_to_log()
        log.metadata_arrs(multi_arr, log_level="info")

        log.separator(log_level="info")


class AlbumUpdateTool(UpdateTool):
    def resolve_item(self):
        """
            Resolves the stored ID to a book (+ optional release) and
            populates the helper. Returns True on success; on any failure
            leaves metadata untouched and returns False.
        """
        kind = self.parsed_id[0]

        # a. invalid / native-but-wrong-type
        if kind == 'invalid':
            log.info(
                'ID %s is not a valid %s ID; leaving metadata untouched.'
                % (self.metadata.id, self.content_type))
            return False

        book = None
        release = None
        release_id = None

        if kind == 'legacy':
            # b. legacy ASIN
            asin = self.parsed_id[1]
            book, matched_release_id = api_client.resolve_asin_book(asin)
            if book is None:
                log.info(
                    'ASIN %s not in AudiobookDB catalog; use Fix Match or '
                    'add the external link to AudiobookDB.' % asin)
                return False
            release_id = self.select_release(
                book, matched_release_id=matched_release_id)
            if release_id:
                release = api_client.get_release(release_id)
                if release is None:
                    # A release selected (matched/only/lowest) that is
                    # unavailable: fall back to the work-only path rather
                    # than pinning a composite ID that would fail closed.
                    log.info(
                        'Release %s not found; updating work-level '
                        'metadata only.' % release_id)
                    release_id = None
        elif kind == 'book':
            book_id, pinned_release_id = self.parsed_id[1], self.parsed_id[2]
            if pinned_release_id:
                # c. book.<id>.release.<id>
                release = api_client.get_release(pinned_release_id)
                if release is None:
                    log.info(
                        'Release %s not found; leaving metadata untouched '
                        '(require rematching).' % pinned_release_id)
                    return False
                book_id = (release.get('book') or {}).get('id')
                book = api_client.get_book(book_id)
                release_id = pinned_release_id
            else:
                # d. book.<id>
                book = api_client.get_book(book_id)
                if book is None:
                    log.info(
                        'Book %s not found; leaving metadata untouched.'
                        % book_id)
                    return False
                release_id = self.select_release(book)
                if release_id:
                    release = api_client.get_release(release_id)
                    if release is None:
                        # A selected (matched/only/lowest) release that
                        # is unavailable: fall back to the work-only path
                        # rather than pinning a composite ID that would
                        # fail closed on the next update.
                        log.info(
                            'Release %s not found; updating work-level '
                            'metadata only.' % release_id)
                        release_id = None
            if book is None:
                return False

        # e. population
        self.native_book_id = book['id']
        self.native_release_id = release_id
        self.parse_api_response(book, release)
        return True

    def parse_api_response(self, book, release):
        """
            Parses the book and release into helper variables, defaulting
            every nullable field before conditional assignment.
        """
        self.set_empty_variables()

        self.title = book.get('title') or ''
        self.subtitle = book.get('subtitle') or ''
        self.synopsis = book.get('description') or ''
        # Authors attach to the book; narrators attach to the selected
        # release. Each credit keeps its person.id and is deduplicated by
        # (scope, person.id, role), so same-named people stay distinct.
        # Entries whose person is absent/null, has no ID, or has a blank
        # name are dropped: tagging calls re.match()/.strip() on the name.
        self.author = collect_role_credits(
            book.get('people'), 'book', book.get('id'), 'Author')
        self.narrator = []
        if release:
            self.narrator = collect_role_credits(
                release.get('people'), 'release', release.get('id'),
                'Narrator')
        self.studio = ((release.get('publisher') or {}).get('name')
                       or '') if release else ''
        self.date = (self.getDateFromString(release.get('releaseDate'))
                     if release else None)
        self.genres = [
            {'name': g.get('title')} for g in book.get('genres') or []
        ]

        # Rating: select the audible chip specifically (never by position).
        self.rating = None
        for chip in api_client.get_ratings(book['id']):
            if chip.get('source') == 'audible' \
                    and chip.get('average') is not None:
                self.rating = chip['average']
                break

        # Series from book['series'][0]/[1].
        series_list = book.get('series') or []
        if len(series_list) > 0:
            entry = series_list[0]
            self.series = (entry.get('series') or {}).get('title')
            self.volume = self.series_volume(entry)
        if len(series_list) > 1:
            entry = series_list[1]
            self.series2 = (entry.get('series') or {}).get('title')
            self.volume2 = self.series_volume(entry)

        # Thumb from coverImage (sized derivative).
        cover = book.get('coverImage')
        self.thumb = (cover['url'] + '/large.jpg') if cover else ''
        self.similar = None

    def series_volume(self, entry):
        """
            Returns the prefixed volume label for a series entry, or '' when
            the position is absent or has no label.
        """
        pos = entry.get('position') or {}
        if pos.get('status') != 'absent' and pos.get('label'):
            return self.volume_prefix(pos['label'])
        return ''

    def set_metadata_date(self):
        """
            Sets the date.
        """
        if self.date is not None:
            if not self.metadata.originally_available_at or self.force:
                self.metadata.originally_available_at = self.date

    def set_empty_variables(self):
        """
            Sets empty variables.
        """
        self.author = []
        self.date = None
        self.genres = None
        self.narrator = []
        self.rating = None
        self.series = ''
        self.series2 = ''
        self.similar = None
        self.studio = ''
        self.subtitle = ''
        self.thumb = ''
        self.title = ''
        self.volume = ''
        self.volume2 = ''

    def set_metadata_rating(self):
        """
            Sets the rating.
        """
        # We always want to refresh the rating
        if self.rating:
            self.metadata.rating = float(self.rating) * 2

    def set_metadata_summary(self):
        """
            Sets the summary.
        """
        self.cleanup_html()
        # No description (or nothing but markup) upstream: don't erase an
        # existing summary, forced update or not.
        if not self.synopsis.strip():
            log.info(
                'No book description available; keeping existing summary.')
            return
        if not self.metadata.summary or self.force:
            self.metadata.summary = self.synopsis

    def set_metadata_studio(self):
        """
            Sets the studio.
        """
        # Work-only updates have no release studio: don't erase an
        # existing studio value.
        if not self.studio:
            return
        if not self.metadata.studio or self.force:
            self.metadata.studio = self.studio

    def set_metadata_sort_title(self):
        """
            Sets the sort title.
        """
        # Add series/volume to sort title where possible.
        series_with_volume = ''
        if self.series and self.volume:
            series_with_volume = self.series + ', ' + self.volume
        # Only include subtitle in sort if not in a series
        if not self.volume:
            self.title = self.metadata.title
        if not self.metadata.title_sort or self.force:
            self.metadata.title_sort = ' - '.join(
                filter(
                    None, [(series_with_volume), self.title]
                )
            )

    def set_metadata_tags(self):
        """
            Set tags of artist
        """
        # Create tagger.
        tagger = TagTool(self, self.prefs)

        # Clears moods if force (refresh) is true.
        if self.force:
            tagger.clear_moods()
            # Narrator styles are release-specific: on work-only updates
            # there is nothing to re-add, so don't clear existing styles.
            if self.narrator:
                tagger.clear_styles()

        # Genres.
        tagger.add_genres()
        # Narrators.
        tagger.add_narrators_to_styles()
        # Authors.
        if self.prefs['store_author_as_mood']:
            tagger.add_authors_to_moods()
        # Series.
        tagger.add_series_to_moods()
        # Similar.
        tagger.add_similar()

    def set_metadata_title(self):
        """
            Sets the title.
        """
        # If the `simplify_title` option is selected, don't append subtitle
        # and remove extra endings on the title
        if self.prefs['simplify_title']:
            album_title = self.simplify_title()
        elif self.subtitle:
            album_title = self.title + ': ' + self.subtitle
        else:
            album_title = self.title
        if not self.metadata.title or self.force:
            self.metadata.title = album_title

    def simplify_title(self):
        """
            Remove extra description text from the title
        """
        # If the title ends with a series part, remove it
        # works for "Book 1" and "Book One"
        album_title = re.sub(
            r", book [\w\s-]+\s*$", "", self.title, flags=re.IGNORECASE)
        # If the title ends with "unabridged"/"abridged", with or without parenthesis
        # remove them; case insensitive
        album_title = re.sub(r" *\(?(un)?abridged\)?$", "",
                             album_title, flags=re.IGNORECASE)
        # Trim any leading/trailing spaces just in case
        album_title = album_title.strip()

        return album_title

    def volume_prefix(self, string):
        """
            Prefixes volume number with 'Book' if it doesn't exist.
        """
        book_regex = '(Book ?(\d*\.)?\d+[+-]?[\d]?)'
        if not re.match(book_regex, string):
            prefixed_string = ('Book ' + string)
            return prefixed_string
        return string


class ArtistUpdateTool(UpdateTool):
    def resolve_item(self):
        """
            Resolves the stored ID to a person and populates the helper.
            Returns True on success; on any failure leaves metadata
            untouched and returns False.
        """
        kind = self.parsed_id[0]

        # a. invalid / native-but-wrong-type
        if kind == 'invalid':
            log.info(
                'ID %s is not a valid %s ID; leaving metadata untouched.'
                % (self.metadata.id, self.content_type))
            return False

        person = None
        if kind == 'legacy':
            # b. legacy ASIN
            asin = self.parsed_id[1]
            hits = api_client.resolve_asin_person(asin)
            if len(hits) == 0:
                log.info(
                    'ASIN %s not in AudiobookDB catalog; use Fix Match or '
                    'add the external link to AudiobookDB.' % asin)
                return False
            if len(hits) > 1:
                log.info(
                    'ASIN %s is ambiguous (%d people); leaving metadata '
                    'untouched.' % (asin, len(hits)))
                return False
            candidate = hits[0]['id']
            person = api_client.get_person(candidate)
            if person is None:
                return False
            confirmed = False
            for ext in person.get('external') or []:
                if ext.get('itemId') == asin and (
                        ext.get('category') or {}).get('title') == 'Audible':
                    confirmed = True
                    break
            if not confirmed:
                log.info(
                    'Person %s does not confirm ASIN %s; leaving metadata '
                    'untouched.' % (candidate, asin))
                return False
        elif kind == 'person':
            # c. person.<id>
            person_id = self.parsed_id[1]
            person = api_client.get_person(person_id)
            if person is None:
                log.info(
                    'Person %s not found; leaving metadata untouched.'
                    % person_id)
                return False

        # d. population
        self.native_person_id = person['id']
        self.parse_api_response(person)
        # The native ID is committed by the agent's compile_metadata,
        # after every setter succeeds (legacy ID stays on failure).
        return True

    def parse_api_response(self, person):
        """
            Parses the person into helper variables, defaulting every
            nullable field before conditional assignment.
        """
        self.set_empty_variables()

        self.name = person.get('name') or ''
        self.description = person.get('description') or ''
        self.genres = [
            {'name': g.get('title')} for g in person.get('genres') or []
        ]
        images = person.get('images') or []
        if images and images[0].get('url'):
            self.thumb = images[0]['url'] + '/large.jpg'
        else:
            self.thumb = ''
        self.similar = None

    def set_metadata_description(self):
        """
            Set description of artist
        """
        self.cleanup_html()
        # No description (or nothing but markup) upstream: don't erase an
        # existing summary, forced update or not.
        if not self.description.strip():
            log.info(
                'No author description available; keeping existing summary.')
            return
        if not self.metadata.summary or self.force:
            self.metadata.summary = self.description

    def set_empty_variables(self):
        """
            Sets empty variables.
        """
        self.date = None
        self.description = ''
        self.genres = None
        self.name = ''
        self.similar = None
        self.thumb = ''

    def set_metadata_sort_title(self):
        """
            Set sort title of artist
        """
        if not self.metadata.title_sort or self.force:
            # An empty name yields no sort title; set_metadata_title has
            # already blanked metadata.title, so use the title as-is.
            if not self.name:
                self.metadata.title_sort = self.metadata.title
                return
            single_word_name = re.match(r'\A[\w-]+\Z', self.name)
            if self.prefs['sort_author_by_last_name'] and not single_word_name:
                split_author_surname = re.match(
                    '^(.+?).([^\s,]+)(,?.(?:[JS]r\.?|III?|IV))?$',
                    self.name,
                )
                if split_author_surname:
                    self.metadata.title_sort = ', '.join(
                        filter(
                            None,
                            [
                                (split_author_surname.group(2) + ', ' +
                                    split_author_surname.group(1)),
                                split_author_surname.group(3)
                            ]
                        )
                    )
                else:
                    self.metadata.title_sort = self.metadata.title
            else:
                self.metadata.title_sort = self.metadata.title

    def set_metadata_tags(self):
        """
            Set tags of artist
        """
        # Create tagger.
        tagger = TagTool(self, self.prefs)
        # Genres.
        tagger.add_genres()
        # Similar.
        tagger.add_similar()

    def set_metadata_title(self):
        """
            Set title of artist
        """
        if not self.metadata.title or self.force:
            self.metadata.title = self.name


class TagTool:
    def __init__(self, helper, Prefs):
        self.helper = helper
        self.prefs = Prefs

    def add_genres(self):
        """
            Add genre(s) to Plex where available and depending on preference.
        """
        if not self.prefs['keep_existing_genres'] and self.helper.genres:
            if not self.helper.metadata.genres or self.helper.force:
                self.helper.metadata.genres.clear()
                for genre in self.helper.genres:
                    if genre['name']:
                        self.helper.metadata.genres.add(genre['name'])

    def add_narrators_to_styles(self):
        """
            Adds narrators to styles.
        """
        # No narrators (e.g. a forced work-only update): keep whatever
        # styles already exist instead of clearing them.
        if not self.helper.narrator:
            return
        if not self.helper.metadata.styles or self.helper.force:
            self.helper.metadata.styles.clear()
            for narrator in self.helper.narrator:
                self.helper.metadata.styles.add(narrator['name'].strip())

    def add_authors_to_moods(self):
        """
            Adds authors to moods, except for cases in contibutors list.
        """
        contributor_regex = '.+?(?= -)'
        if not self.helper.metadata.moods or self.helper.force:
            # Loop through authors to check if it has contributor wording
            for author in self.helper.author:
                if not re.match(contributor_regex, author['name']):
                    self.helper.metadata.moods.add(author['name'].strip())

    def add_series_to_moods(self):
        """
            Adds book series' to moods, since collections are not supported
        """
        if self.helper.series:
            self.helper.metadata.moods.add("Series: " + self.helper.series)
        if self.helper.series2:
            self.helper.metadata.moods.add("Series: " + self.helper.series2)

    def add_similar(self):
        """
            Adds similar items.
        """
        if self.helper.similar:
            for item in self.helper.similar:
                self.helper.metadata.similar.add(item['name'])

    def clear_moods(self):
        """
            Clears moods.
        """
        self.helper.metadata.moods.clear()

    def clear_styles(self):
        """
            Clears styles.
        """
        self.helper.metadata.styles.clear()
