# AudiobookDB Agent
# coding: utf-8
# Import internal tools
from _version import version
from logging import Logging
import api_client
from search_tools import (AlbumSearchTool, ArtistSearchTool, ScoreTool,
                          edition_tags, image_thumb, release_narrators,
                          release_year)
import metadata_ids
from update_tools import AlbumUpdateTool, ArtistUpdateTool

VERSION_NO = version

# Score required to short-circuit matching and stop searching.
GOOD_SCORE = 98

# Setup logger
log = Logging()


def ValidatePrefs():
    log.debug('ValidatePrefs function call')


def Start():
    HTTP.ClearCache()
    HTTP.CacheTime = CACHE_1WEEK
    HTTP.Headers['User-agent'] = api_client.USER_AGENT
    # The API key is attached per-request to the trusted API origin only
    # (see api_client); it must not ride along on off-origin image fetches.
    HTTP.Headers['Accept-Encoding'] = 'gzip'
    log.separator(
        msg=(
            "AudiobookDB Audiobooks Agent v" + VERSION_NO
        ),
        log_level="info"
    )


class AudiobookArtist(Agent.Artist):
    name = 'AudiobookDB Agent'
    languages = [
        Locale.Language.English,
        'de',
        'es',
        'fr',
        'it',
        'ja',
    ]
    primary_provider = True
    accepts_from = ['com.plexapp.agents.localmedia']

    prev_search_provider = 0

    def search(self, results, media, lang, manual):
        """
            Search for artist metadata.
        """
        # Instantiate search helper
        search_helper = ArtistSearchTool(
            'authors', lang, manual, media, Prefs, results)

        # Check if we can quick match based on ID (native or legacy ASIN).
        # The helper appends the result(s) itself.
        if search_helper.check_for_asin():
            return

        # Validate author name
        search_helper.validate_author_name()

        # Short circuit search if artist name is bad.
        if not search_helper.media.artist:
            return

        # Call search API
        result = self.call_search_api(search_helper)

        # Write search result status to log
        if not result:
            log.warn(
                'No results found for query "%s"',
                search_helper.media.artist
            )
            return
        log.debug(
            'Found %s result(s) for query "%s"',
            len(result),
            search_helper.media.artist
        )

        info = self.process_results(search_helper, result)

        # Output the final results.
        log.separator(log_level="debug")
        log.debug('Final result:')
        for i, r in enumerate(info):
            description = r['author']

            results.Append(
                MetadataSearchResult(
                    id=r['id'],
                    lang=lang,
                    name=description,
                    score=r['score']
                )
            )

            """
                If there are more than one result,
                and this one has a score that is >= GOOD SCORE,
                then ignore the rest of the results
            """
            if not manual and len(info) > 1 and r['score'] >= GOOD_SCORE:
                log.info(
                    '            *** The score for these results are great, '
                    'so we will use them, and ignore the rest. ***'
                )
                break

    def update(self, metadata, media, lang, force):
        """
            Update artist metadata.
        """
        log.separator(
            msg=(
                "UPDATING: " + media.title + (
                    " ID: " + metadata.id
                )
            ),
            log_level="info"
        )

        # Instantiate update helper
        update_helper = ArtistUpdateTool(
            'authors', force, lang, media, metadata, Prefs)

        # Resolve the stored ID to a person; leave metadata untouched on
        # any failure (unresolvable legacy ASIN, 404, ambiguous match).
        if not update_helper.resolve_item():
            return

        self.compile_metadata(update_helper)

    def call_search_api(self, helper):
        """
            Calls the AudiobookDB search API, returns the parsed results
            to the helper function.
        """
        body = helper.build_search_body()
        if not body:
            return []
        response = api_client.search(
            body.get('q'), body['type'], body.get('filters'))
        return helper.parse_api_response(response or [])

    def process_results(self, helper, result):
        """
            Process the results from the API call.
        """
        # Walk the found items and gather extended information
        info = []

        log.separator(msg="Search results", log_level="info")
        for index, result_dict in enumerate(result):
            score_helper = ScoreTool(
                helper,
                index,
                info,
                Util.LevenshteinDistance,
                result_dict,
            )
            score_helper.run_score_author()

            # Print separators for easy reading
            if index <= len(result):
                log.separator(log_level="info")

        for inf in info:
            inf.pop('title_deduction', None)
            inf.pop('series_eligible', None)
        info = sorted(info, key=lambda inf: inf['score'], reverse=True)
        return info

    def compile_metadata(self, helper):
        """
            Compiles the metadata for the artist.
        """
        # Description.
        helper.set_metadata_description()
        # Tags.
        helper.set_metadata_tags()
        # Title.
        helper.set_metadata_title()
        # Sort Title.
        helper.set_metadata_sort_title()
        # Thumb.
        # Kept here because of Proxy
        if helper.thumb:
            if helper.thumb not in helper.metadata.posters or helper.force:
                try:
                    helper.metadata.posters[helper.thumb] = Proxy.Media(
                        api_client.fetch_bytes(helper.thumb), sort_order=0
                    )
                except (IOError, OSError) as e:
                    # A poster failure must not abort the update: log it
                    # and continue without the poster.
                    log.warn('Skipping poster: %s', e)

        # Commit the native person ID last (after every setter succeeded),
        # so a failed setter leaves the old ID in place.
        helper.metadata.id = metadata_ids.serialize_person_id(
            helper.native_person_id)

        helper.log_update_metadata()


class AudiobookAlbum(Agent.Album):
    name = 'AudiobookDB Agent'
    languages = [
        Locale.Language.English,
        'de',
        'es',
        'fr',
        'it',
        'ja',
    ]
    primary_provider = True
    accepts_from = ['com.plexapp.agents.localmedia']

    prev_search_provider = 0

    def search(self, results, media, lang, manual):
        """
            Search for an album.
        """
        # Instantiate search helper
        search_helper = AlbumSearchTool(
            'books', lang, manual, media, Prefs, results)

        # Automatic file IDs can identify an album even when its tags are absent.
        if not manual and search_helper.check_for_asin():
            return
        if not search_helper.pre_search_logging():
            return
        # The pre-check copies a typed Fix Match query into media.album.
        if manual and search_helper.check_for_asin():
            return

        search_helper.validate_author_name()

        info = self.find_matches(search_helper)
        if not info:
            log.warn('No matches for query "%s"', search_helper.normalizedName)
            return

        author_separators = {'de': 'von', 'fr': 'de', 'it': 'di',
                             'es': 'de', 'ja': u'\u306b\u3088\u308b'}

        hints = search_helper.recording_hints() if manual else (None, None)
        for match in info:
            title = match['title']
            if len(title) > 36:
                title = title[:30] + '..'
            label = '"%s"' % title
            if match.get('author'):
                label += ' %s %s' % (
                    author_separators.get(lang, 'by'),
                    search_helper.name_to_initials(match['author']))
            book_id = metadata_ids.parse_metadata_id(match['id'], 'books')[1]
            releases = search_helper.releases_for_book(book_id) if manual else []
            if len(releases) == 1:
                self.append_album_match(search_helper, match, label, releases[0])
            elif releases:
                # Recordings only: a work-only pin carries no release data,
                # so Fix Match must not offer it beside selectable editions.
                ranked = sorted(releases, key=lambda release:
                                self.recording_rank(release, hints))
                # Bound edition rows per hit. Rows whose edition tags would
                # otherwise read identically carry the release publisher
                # (or year).
                shown = ranked[:5]
                tags = edition_tags(shown)
                for index, release in enumerate(shown):
                    recording = dict(match)
                    recording['id'] = metadata_ids.serialize_book_id(
                        book_id, release['id'])
                    recording['score'] = match['score'] - (index + 1)
                    self.append_album_match(search_helper, recording,
                                            label, release,
                                            ' [%s]' % tags[index])
            else:
                # No visible release: the work itself is the only match.
                # Plain search hits keep their book-level narrator display.
                self.append_album_match(search_helper, match, label)

            if not manual and match['score'] >= GOOD_SCORE:
                break

    def append_album_match(self, helper, match, label, release=None,
                           edition='', include_book_narrators=True):
        thumb = match.get('thumb')
        narrator = match.get('narrator') if include_book_narrators else None
        year = None
        if release is not None:
            narrator = release_narrators(release)
            year = release_year(release)
            for image in release.get('images') or []:
                cover = image_thumb(image)
                if cover:
                    thumb = cover
                    break
        label = helper.narrator_label(label, narrator, edition)

        helper.results.Append(MetadataSearchResult(
            id=match['id'], lang=helper.lang, name=label, score=match['score'],
            thumb=thumb, year=year))

    def recording_rank(self, release, hints):
        runtime, language = hints
        name = ((release.get('language') or {}).get('name') or '').strip().lower()
        language_rank = 1
        if name and language:
            language_rank = 0 if name == language.lower() else 2
        difference = None
        if runtime:
            try:
                hours, minutes, seconds = (release.get('duration') or '').split(':')
                duration = (int(hours) * 3600 + int(minutes) * 60 + int(seconds)) * 1000
                if duration > 0:
                    difference = abs(duration - runtime)
            except (TypeError, ValueError):
                pass
        return (language_rank, difference is None, difference or 0)

    def update(self, metadata, media, lang, force):
        """
            Update an album.
        """
        log.separator(
            msg=(
                "UPDATING: " + media.title + (
                    " ID: " + metadata.id
                )
            ),
            log_level="info"
        )

        # Instantiate update helper
        update_helper = AlbumUpdateTool(
            'books', force, lang, media, metadata, Prefs)

        # Resolve the stored ID to a book (+release); leave metadata
        # untouched on any failure (unresolvable legacy ASIN, 404).
        if not update_helper.resolve_item():
            return

        self.compile_metadata(update_helper)

    def find_matches(self, helper):
        body = helper.build_search_body()
        if not body:
            return []
        query = body['q']
        filters = body.get('filters')
        response = api_client.search(query, body['type'], filters,
                                     helper.SEARCH_FIELDS)
        if response is None:
            return []
        matches = self.process_results(helper, helper.parse_api_response(response))
        # Local credits and catalog spellings do not always agree. Retry the
        # title once when the author filter leaves no usable match.
        if not matches and filters and len(query) >= api_client.MIN_QUERY_LENGTH:
            response = api_client.search(query, body['type'], None,
                                         helper.SEARCH_FIELDS)
            matches = self.process_results(
                helper, helper.parse_api_response(response or []),
                relaxed_author=True)
        return matches

    def process_results(self, helper, result, relaxed_author=False):
        info = []
        for index, result_dict in enumerate(result):
            ScoreTool(helper, index, info, Util.LevenshteinDistance,
                      result_dict).run_score_book(relaxed_author)
        if helper.manual:
            self.apply_series_hint(info)
        for inf in info:
            inf.pop('title_deduction', None)
            inf.pop('series_eligible', None)
        return sorted(info, key=lambda inf: inf['score'], reverse=True)

    @staticmethod
    def apply_series_hint(info):
        """
            Adds the one-point series-name hint to Fix Match hits.

            All decisions use the unboosted base-score snapshot: a hit
            earns the point only when it cannot change the title
            ranking — its score is below 100, no other hit's base sits
            at base+1, and no hit tied at the same base has a smaller
            title deduction. One title edit costs two points, so the
            bonus never overtakes a better title match. Every boost is
            decided from the base scores before any is applied, so an
            earlier boost cannot free a slot for a later hit.
        """
        boosts = []
        for inf in info:
            if not inf.get('series_eligible') \
                    or inf['score'] >= ScoreTool.INITIAL_SCORE:
                continue
            blocked = False
            for other in info:
                if other is inf:
                    continue
                if other['score'] == inf['score'] + 1:
                    blocked = True
                    break
                if other['score'] == inf['score'] \
                        and other['title_deduction'] < inf['title_deduction']:
                    blocked = True
                    break
            if not blocked:
                boosts.append(inf)
        for inf in boosts:
            inf['score'] = inf['score'] + 1

    def compile_metadata(self, helper):
        """
            Compiles the metadata for the book.
        """
        # Date.
        helper.set_metadata_date()
        # Tags.
        helper.set_metadata_tags()
        # Title.
        helper.set_metadata_title()
        # Sort Title.
        helper.set_metadata_sort_title()
        # Studio.
        helper.set_metadata_studio()
        # Summary.
        helper.set_metadata_summary()
        # Thumb.
        # Kept here because of Proxy
        if helper.thumb:
            if helper.thumb not in helper.metadata.posters or helper.force:
                try:
                    helper.metadata.posters[helper.thumb] = Proxy.Media(
                        api_client.fetch_bytes(helper.thumb), sort_order=0
                    )
                    # Re-prioritize the poster to the first position
                    helper.metadata.posters.validate_keys([helper.thumb])
                except (IOError, OSError) as e:
                    # A poster failure must not abort the update: log it
                    # and continue without the poster.
                    log.warn('Skipping poster: %s', e)
        # Rating.
        helper.set_metadata_rating()
        helper.set_metadata_chapters()
        helper.set_metadata_series_collections()

        # Commit the native ID last (after every setter succeeded).
        helper.metadata.id = metadata_ids.serialize_book_id(
            helper.native_book_id, helper.native_release_id)

        # Log the resulting metadata
        helper.log_update_metadata()

