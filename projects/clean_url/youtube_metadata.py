import os
import re
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs, urlparse

import pywikibot
import requests
from database_handler import DatabaseHandler
from dotenv import load_dotenv
from pywikibot.data import sparql

import shared_lib.change_wikidata as cwd
import shared_lib.constants as wd
import shared_lib.date_value as date_value

site = pywikibot.Site("wikidata", "wikidata")
repo = site.data_repository()

load_dotenv()  # reads .env file in the current directory
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
YOUTUBE_VIDEOS_API_URL = "https://www.googleapis.com/youtube/v3/videos"
YOUTUBE_CHANNELS_API_URL = "https://www.googleapis.com/youtube/v3/channels"

URL_PROPERTIES = ["P854", "P856", "P953", "P973", "P1325", "P2699", "P2888", "P8214"]


# ---------------------------------------------------------------------------
# Channel handle tracker  (channelId -> @handle, persisted across runs)
# ---------------------------------------------------------------------------


class ChannelHandleTracker(DatabaseHandler):
    """
    Persists YouTube channelId -> handle lookups so we never call the
    channels.list API twice for the same channel across runs.
    """

    def __init__(self):
        file_path = Path(__file__).parent / "channel_handles.json"
        create_script = Path("schemas/channel_handles.sql")
        super().__init__(file_path, create_script)

    def get_handle(self, channel_id: str) -> tuple[bool, str | None]:
        """
        Return (is_cached, handle_or_None).
        is_cached=True means we already looked this up (handle may still be None).
        """
        rows = self.execute_query(
            "SELECT handle, status FROM channel_handles WHERE channel_id = ?",
            (channel_id,),
        )
        if not rows:
            return False, None
        handle = rows[0][0]  # may be None
        return True, handle

    def save_handle(self, channel_id: str, handle: str | None) -> None:
        status = "found" if handle else "not_found"
        self.execute_procedure(
            "UPDATE OR INSERT INTO channel_handles (channel_id, handle, status) "
            "VALUES (?, ?, ?)",
            (channel_id, handle, status),
        )

    def save_error(self, channel_id: str) -> None:
        self.execute_procedure(
            "UPDATE OR INSERT INTO channel_handles (channel_id, handle, status) "
            "VALUES (?, ?, ?)",
            (channel_id, None, "error"),
        )

    def add_error(self, qid: str, error_msg):
        """Add an error record to the database."""

        sql = "INSERT INTO qerrors (qid, error_msg) VALUES (?, ?)"
        self.execute_procedure(sql, (qid, error_msg))

    def get_publisher(self, channel_key: str) -> tuple[bool, str | None]:
        """Return (is_cached, qid_or_None)."""
        rows = self.execute_query(
            "SELECT publisher_qid, status FROM channel_publishers WHERE channel_key = ?",
            (channel_key,),
        )
        if not rows:
            return False, None
        return True, rows[0][0]  # may be None

    def save_publisher(self, channel_key: str, qid: str | None) -> None:
        status = "found" if qid else "not_found"
        self.execute_procedure(
            "UPDATE OR INSERT INTO channel_publishers (channel_key, publisher_qid, status) "
            "VALUES (?, ?, ?)",
            (channel_key, qid, status),
        )


# ---------------------------------------------------------------------------
# YouTube API helpers
# ---------------------------------------------------------------------------


DURATION_THRESHOLD_SECONDS = 60  # videos under 1 minute → seconds, otherwise → minutes


def get_duration_for_wikidata(total_seconds: int) -> tuple[float, str]:
    """
    Return (amount, unit_qid) ready for a Wikidata quantity statement.
    Uses seconds for short videos (< 1 min), minutes for longer ones.
    Rounds to 1 decimal place if not a whole number of minutes.
    """
    if total_seconds < DURATION_THRESHOLD_SECONDS:
        return total_seconds, wd.QID_SECOND

    minutes = total_seconds / 60
    # Round to whole number if close enough, else 1 decimal
    if minutes == int(minutes):
        return int(minutes), wd.QID_MINUTE
    return round(minutes, 1), wd.QID_MINUTE


def language_code_to_qid(lang_code: str) -> str:
    # This mapping is not exhaustive, just some common languages we expect to see.
    mapping = {
        "en": wd.QID_ENGLISH,
        "de": wd.QID_GERMAN,
    }
    qid = mapping.get(lang_code.split("-")[0], None)
    if not qid:
        raise ValueError(f"Unsupported language code: {lang_code}")

    return qid


def parse_iso8601_duration(duration_str):
    match = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", duration_str)
    if not match:
        return None
    hours = int(match.group(1) or 0)
    minutes = int(match.group(2) or 0)
    seconds = int(match.group(3) or 0)
    return hours * 3600 + minutes * 60 + seconds


def extract_video_id(url):
    parsed = urlparse(url)
    if parsed.netloc in ("youtu.be",):
        return parsed.path.lstrip("/").split("?")[0]
    if "youtube.com" in parsed.netloc:
        params = parse_qs(parsed.query)
        if "v" in params:
            return params["v"][0]
        match = re.match(r"/(?:embed|v)/([^/?]+)", parsed.path)
        if match:
            return match.group(1)
    return None


def fetch_youtube_metadata(video_ids):
    """Fetch snippet+contentDetails for up to 50 video IDs in one call."""
    response = requests.get(
        YOUTUBE_VIDEOS_API_URL,
        params={
            "key": YOUTUBE_API_KEY,
            "id": ",".join(video_ids),
            "part": "snippet,contentDetails",
            "maxResults": 50,
        },
    )
    data = response.json()

    results = {}
    for item in data.get("items", []):
        vid_id = item["id"]
        snippet = item.get("snippet", {})
        content = item.get("contentDetails", {})

        duration_str = content.get("duration")
        duration_seconds = (
            parse_iso8601_duration(duration_str) if duration_str else None
        )

        results[vid_id] = {
            "title": snippet.get("title"),
            "published_at": snippet.get("publishedAt"),
            "channel_id": snippet.get("channelId"),
            "channel_title": snippet.get("channelTitle"),
            "audio_language": snippet.get("defaultAudioLanguage"),
            "duration_seconds": duration_seconds,
        }
    return results


def fetch_channel_handles(
    channel_ids: list[str], tracker: ChannelHandleTracker
) -> dict[str, str | None]:
    """
    Resolve a list of channelIds to their @handle, using the tracker as a
    cache so each channel is only looked up once across all runs.

    Returns dict { channel_id: handle_or_None }.
    """
    result = {}
    to_fetch = []

    for channel_id in channel_ids:
        is_cached, handle = tracker.get_handle(channel_id)
        if is_cached:
            pywikibot.output(f"  Channel {channel_id}: handle '{handle}' (cached)")
            result[channel_id] = handle
        else:
            to_fetch.append(channel_id)

    if not to_fetch:
        return result

    # Batch in groups of 50 (API limit)
    for i in range(0, len(to_fetch), 50):
        batch = to_fetch[i : i + 50]
        try:
            response = requests.get(
                YOUTUBE_CHANNELS_API_URL,
                params={
                    "key": YOUTUBE_API_KEY,
                    "id": ",".join(batch),
                    "part": "snippet",
                },
            )
            data = response.json()

            returned_ids = set()
            for item in data.get("items", []):
                channel_id = item["id"]
                returned_ids.add(channel_id)
                # customUrl is the @handle, e.g. "@channelname"
                handle = item.get("snippet", {}).get("customUrl") or None
                pywikibot.output(f"  Channel {channel_id}: handle '{handle}' (fetched)")
                tracker.save_handle(channel_id, handle)
                result[channel_id] = handle

            # Channels not returned by the API (deleted/private)
            for channel_id in batch:
                if channel_id not in returned_ids:
                    pywikibot.output(
                        f"  Channel {channel_id}: not found in API response"
                    )
                    tracker.save_handle(channel_id, None)
                    result[channel_id] = None

        except Exception as e:
            pywikibot.error(f"  Error fetching channel handles for batch: {e}")
            for channel_id in batch:
                tracker.save_error(channel_id)
                result[channel_id] = None

    return result


# ---------------------------------------------------------------------------
# Publisher lookup via SPARQL
# ---------------------------------------------------------------------------


def lookup_handle_qid(handle: Optional[str]) -> str | None:
    """
    Query Wikidata for an item that has the given YouTube channel ID or handle.
    Returns the QID (e.g. 'Q12345') or None if not found.
    """
    pid = wd.PID_YOUTUBE_HANDLE
    query = f"""
    SELECT ?item WHERE {{
      ?item wdt:{pid} "{handle}" .
    }}
    LIMIT 1
    """
    if not handle:
        return None
    try:
        query_object = sparql.SparqlQuery(repo=repo)
        results = query_object.select(query, full_data=False)
        if results:
            return results[0]["item"].replace(wd.BASE_URL, "")
    except Exception as e:
        pywikibot.error(f"  SPARQL error looking up '{handle}': {e}")
        raise
    return None


def lookup_channel_qid(channel_id: Optional[str]) -> str | None:
    """
    Query Wikidata for an item that has the given YouTube channel ID or handle.
    Returns the QID (e.g. 'Q12345') or None if not found.
    """
    pid = wd.PID_YOUTUBE_CHANNEL_ID
    query = f"""
    SELECT ?item WHERE {{
      ?item wdt:{pid} "{channel_id}" .
    }}
    LIMIT 1
    """
    if not channel_id:
        return None
    try:
        query_object = sparql.SparqlQuery(repo=repo)
        results = query_object.select(query, full_data=False)
        if results:
            return results[0]["item"].replace(wd.BASE_URL, "")
    except Exception as e:
        pywikibot.error(f"  SPARQL error looking up '{channel_id}': {e}")
        raise
    return None


def fetch_publisher_qid(
    channel_id: str | None,
    handle: str | None,
    tracker: ChannelHandleTracker,
) -> str | None:
    """
    Resolve a publisher QID from handle (preferred) or channel_id,
    using the tracker as a persistent cache.
    Raises if not found in Wikidata (caller logs to DB).
    """
    # Prefer handle as the lookup key since it's more stable as a Wikidata property
    channel_key = handle or channel_id
    if not channel_key:
        raise ValueError("No handle or channel_id to look up publisher")

    is_cached, qid = tracker.get_publisher(channel_key)
    if is_cached:
        pywikibot.output(f"  Publisher for '{channel_key}': {qid} (cached)")
        return qid

    try:
        qid = lookup_handle_qid(handle)
        if not qid:
            qid = lookup_channel_qid(channel_id)
    except Exception as e:
        tracker.save_error(channel_key)
        raise ValueError(f"SPARQL lookup failed for '{channel_key}': {e}") from e

    pywikibot.output(f"  Publisher for '{channel_key}': {qid} (fetched)")
    tracker.save_publisher(channel_key, qid)

    # if not qid:
    #     raise ValueError(f"No Wikidata item found for YouTube {channel_key}")
    return qid


# ---------------------------------------------------------------------------
# Qualifier helpers
# ---------------------------------------------------------------------------


def qualifier_already_exists(claim, qualifier_pid):
    return qualifier_pid in claim.qualifiers


def get_existing_qualifier_value(claim, qualifier_pid):
    """Return the current value of a qualifier, or None if not set."""
    if qualifier_pid not in claim.qualifiers:
        return None
    snak = claim.qualifiers[qualifier_pid][0]
    return snak.getTarget()


def strip_at(handle: str) -> str:
    """Remove leading @ from a YouTube handle if present."""
    return handle.lstrip("@")


# ---------------------------------------------------------------------------
# Item processing
# ---------------------------------------------------------------------------


def process_item(item_id, tracker: ChannelHandleTracker, test=True):
    item = pywikibot.ItemPage(repo, item_id)
    page = cwd.WikiDataPage(item, test=test)

    # ── Step 1: Collect YouTube URLs ─────────────────────────────────────────
    video_to_claims = {}
    for prop_id in URL_PROPERTIES:
        if prop_id not in page.claims:
            continue
        for claim in page.claims[prop_id]:
            if claim.rank == "deprecated" or claim.type != "url":
                continue
            target = claim.getTarget()
            if not isinstance(target, str):
                continue
            video_id = extract_video_id(target)
            if not video_id:
                continue
            video_to_claims.setdefault(video_id, []).append((prop_id, claim))

    if not video_to_claims:
        pywikibot.output(f"  No YouTube URLs found on {item_id}")
        return

    pywikibot.output(
        f"  Found {len(video_to_claims)} unique YouTube video(s) on {item_id}"
    )

    # ── Step 2: Fetch video metadata ─────────────────────────────────────────
    metadata = {}
    all_video_ids = list(video_to_claims.keys())
    for i in range(0, len(all_video_ids), 50):
        metadata.update(fetch_youtube_metadata(all_video_ids[i : i + 50]))

    # ── Step 3: Resolve channel handles (batched + cached) ───────────────────
    unique_channel_ids = list(
        {meta["channel_id"] for meta in metadata.values() if meta.get("channel_id")}
    )
    channel_handles = fetch_channel_handles(unique_channel_ids, tracker)

    # ── Step 4: Apply qualifiers ──────────────────────────────────────────────
    for video_id, claims_list in video_to_claims.items():
        meta = metadata.get(video_id)
        if not meta:
            raise ValueError(
                f"Video {video_id}: no metadata returned (private/deleted?)"
            )
        if not meta["title"]:
            raise ValueError(f"Video {video_id}: missing title in API response")

        channel_id = meta.get("channel_id")
        handle = channel_handles.get(channel_id)
        if not handle and not channel_id:
            raise ValueError(
                f"Video {video_id}: neither handle nor channel_id available"
            )

        raw_lang = meta.get("audio_language")
        if not raw_lang:
            raise ValueError(
                f"Video {video_id}: missing audio language in API response"
            )
        lang_code = raw_lang.split("-")[0] if raw_lang else None
        if lang_code and not language_code_to_qid(lang_code):
            raise ValueError(
                f"Video {video_id}: language '{raw_lang}' not in LANGUAGE_MAP"
            )
        lang_qid = language_code_to_qid(lang_code) if lang_code else None
        if not lang_qid:
            raise ValueError(
                f"Video {video_id}: could not resolve language code '{raw_lang}'"
            )

        publisher_qid = fetch_publisher_qid(channel_id, handle, tracker)

        pywikibot.output(
            f"  Video {video_id}: '{meta['title']}' / handle: {handle} / lang: {lang_code}"
        )

        for prop_id, claim in claims_list:

            # P1476 title
            if not qualifier_already_exists(claim, wd.PID_TITLE):
                title_lang = lang_code or "en"
                page.add_qualifier(
                    prop_id,
                    claim,
                    cwd.MonolingualTextQualifier(
                        wd.PID_TITLE, meta["title"], title_lang
                    ),
                )

            # P577 publication date
            if meta["published_at"] and not qualifier_already_exists(
                claim, wd.PID_PUBLICATION_DATE
            ):
                date_str = meta["published_at"][:10]
                y, m, d = map(int, date_str.split("-"))
                page.add_qualifier(
                    prop_id,
                    claim,
                    cwd.DateQualifier(
                        wd.PID_PUBLICATION_DATE, date_value.Date(y, m, d)
                    ),
                )

            # P2047 duration
            if meta["duration_seconds"] and not qualifier_already_exists(
                claim, wd.PID_DURATION
            ):
                amount, unit_qid = get_duration_for_wikidata(meta["duration_seconds"])
                page.add_qualifier(
                    prop_id,
                    claim,
                    cwd.QuantityQualifier(wd.PID_DURATION, amount, unit_qid),
                )

            # P11245 YouTube handle (strip @ prefix)
            if handle:
                clean_handle = strip_at(handle)
                existing_handle = get_existing_qualifier_value(
                    claim, wd.PID_YOUTUBE_HANDLE
                )
                if existing_handle is None:
                    page.add_qualifier(
                        prop_id,
                        claim,
                        cwd.StringQualifier(wd.PID_YOUTUBE_HANDLE, clean_handle),
                    )
                elif existing_handle != clean_handle:
                    raise ValueError(
                        f"Video {video_id}: existing handle '{existing_handle}' "
                        f"differs from fetched '{clean_handle}' -- manual check required"
                    )

            # Fallback: raw channel ID if no handle
            if channel_id:
                existing_channel = get_existing_qualifier_value(
                    claim, wd.PID_YOUTUBE_CHANNEL_ID
                )
                if existing_channel is None:
                    # only add channel_id if we don't have a handle, to avoid redundancy
                    if not handle:
                        page.add_qualifier(
                            prop_id,
                            claim,
                            cwd.StringQualifier(wd.PID_YOUTUBE_CHANNEL_ID, channel_id),
                        )
                elif existing_channel != channel_id:
                    raise ValueError(
                        f"Video {video_id}: existing channel ID '{existing_channel}' "
                        f"differs from fetched '{channel_id}' -- manual check required"
                    )

            # P123 publisher
            if publisher_qid:
                existing_publisher = get_existing_qualifier_value(
                    claim, wd.PID_PUBLISHER
                )
                if existing_publisher is None:
                    page.add_qualifier(
                        prop_id,
                        claim,
                        cwd.ItemQualifier(wd.PID_PUBLISHER, publisher_qid),
                    )
                elif existing_publisher.id != publisher_qid:
                    raise ValueError(
                        f"Video {video_id}: existing publisher '{existing_publisher.id}' "
                        f"differs from fetched '{publisher_qid}' -- manual check required"
                    )

            # P407 language of work
            if lang_qid and not qualifier_already_exists(
                claim, wd.PID_LANGUAGE_OF_WORK_OR_NAME
            ):
                page.add_qualifier(
                    prop_id,
                    claim,
                    cwd.ItemQualifier(wd.PID_LANGUAGE_OF_WORK_OR_NAME, lang_qid),
                )

    # Single commit for the entire page
    page.summary = "Add YouTube metadata qualifiers"
    page.apply()


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------


def load_items_from_file(filename):
    with open(filename, "r", encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip()]


def main():
    # print(lookup_channel_qid("UCmh7afBz-uWwOSSNTqUBAhg"))
    tracker = ChannelHandleTracker()  # shared across all items
    items = [wd.QID_WIKIDATASANDBOX3]
    # items = load_items_from_file("items.csv")
    for qid in items:
        pywikibot.output(f"Processing {qid}...")
        try:
            process_item(qid, tracker=tracker, test=False)
        except Exception as e:
            tracker.add_error(qid, str(e))
            print(f"Error processing {qid}: {e}")


if __name__ == "__main__":
    main()
