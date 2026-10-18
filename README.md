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
native form (`book.<id>.release.<id>` / `person.<id>`). If an ASIN is not in
the AudiobookDB catalog, the item is left untouched and the failure is reported
in the log — add the external link to AudiobookDB and retry.

Metadata by [AudiobookDB](https://audiobookdb.org)
