# AudiobookDB Agent

A [Plex](https://www.plex.tv) metadata agent for audiobooks that sources its
metadata from the [AudiobookDB](https://audiobookdb.org) public API
(`<https://audiobookdb.org/api>`).

It is the successor to the Audnexus agent and installs alongside it: it
registers under its own plug-in identifier (`com.plexapp.agents.audiobookdb`),
so the legacy `Audnexus.bundle` can stay installed. Data is sourced from
AudiobookDB (books, releases, people) instead of Audible/Audnexus; each library
keeps using whichever agent is selected for it until you switch it over (see
*Migrating from Audnexus*).

## Install

- **Release (recommended):** download `AudiobookDB.bundle.zip` from the
  [releases](https://github.com/laxamentumtech/AudiobookDB.bundle/releases)
  page, unzip it, and place the `AudiobookDB.bundle` folder in your Plex
  `Plug-ins` directory. Restart Plex.
- **From source:** clone this repository into your Plex `Plug-ins` directory
  (the `Contents/` folder must sit directly inside `AudiobookDB.bundle/`).
  Restart Plex.

**Coming from Audnexus:** `AudiobookDB.bundle` declares its own plug-in
identifier (`com.plexapp.agents.audiobookdb`), so it coexists with the legacy
`Audnexus.bundle` — nothing needs to be removed. Existing libraries keep using
Audnexus until you switch their agent in the library settings.

**Plex Media Server 1.43+:** the legacy agent system is hidden during library
setup unless *Show legacy agents during library setup* is enabled in the
server's library settings. Plex has announced that the legacy agent system is
being removed from new PMS releases in 2026; this bundle requires it.

## Configuration

| Preference | Default | Description |
|---|---|---|
| `api_key` | *(empty)* | Optional AudiobookDB API key. Raises rate limits; anonymous access works without one. |
| `keep_existing_genres` | `false` | Keep existing genres in place. |
| `store_author_as_mood` | `true` | Append authors as Mood tags. |
| `sort_author_by_last_name` | `true` | Sort artist by name `[Last, First]`. |
| `simplify_title` | `false` | Simplify book titles (remove subtitle, series part, (un)abridged, etc.). |
| `logging_level` | `WARN` | Level of plugin logging (`DEBUG`, `INFO`, `WARN`, `ERROR`). |

## Narrators and tags

Album updates read every `Narrator` credit from the selected release
(`release.people`) and write one Style tag per distinct narrator name. The
complete credit list is retained with each person's stable `person.id`; tags
are display text only. Two different people who share a display name produce
two credits but one Style tag, because Plex deduplicates identical tag text.
A forced refresh clears and re-adds narrator styles from the current release
detail, so a catalog rename is reflected on the next forced update.

Fix Match shows every narrator entry present in a search hit. When the complete
list does not fit the description budget, the names that fit are followed by an
explicit `+N` remaining count; the full list stays in the result data.
Book-level search hits (the recorded case) carry authors only; the agent does
not claim narrator completeness or borrow narrators from another release.

Clickable narrator profiles (portrait, bio, discography) are not available
through the Plex legacy music model: an album exposes only the album artist,
and music collections have no details page. The upstream prerequisite is a
Plex model/client change that exposes additional, client-rendered per-album
people; no plugin-side change closes that gap. Narrator discovery therefore
stops at Style tags and Fix Match display.

## Release selection

Album updates select, in order: a release pinned in the stored ID, the release
matched by an ASIN resolve, the only release on the book, or the
lexicographically lowest release ID as a deterministic fallback. The fallback
selects a recording; it does not verify that it is the user's edition. Accurate
matches come from an ASIN in the filename or manual search field, or from an
explicit `book.<id>.release.<id>` ID. Narrators are taken only from that
selected release, never aggregated across releases.

## Quick match

Put an ASIN in the manual search field (or in the media filename for albums)
and the agent resolves it directly to a score-100 result, skipping normal
search:

- `B0XXXXXXXXXX` — an Audible ASIN, resolved through
  `GET /audiobooks/external/audible/{ASIN}` (albums) or
  `GET /people?external=Audible:{ASIN}` (artists).
- Native IDs `book.<id>[.release.<id>]` and `person.<id>` are also accepted as
  manual search input; they are validated against the corresponding detail
  endpoint before a score-100 result is appended.

## Migrating from Audnexus

Once a library is switched to this agent, its old pinned IDs (`ASIN` /
`ASIN_region`) keep working: on the next refresh the agent resolves the ASIN
against AudiobookDB, populates metadata, and rewrites the pinned ID to the new
native form (`book.<id>.release.<id>` / `person.<id>`). Two cases are left
untouched and reported in the log: an ASIN not in the AudiobookDB catalog
(add the external link to AudiobookDB and retry), and an artist ASIN that
resolves to multiple people (use Fix Match — or enter the person ID
manually — to disambiguate before the ID can be rewritten).

Metadata by [AudiobookDB](https://audiobookdb.org)
