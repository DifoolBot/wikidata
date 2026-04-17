import os
import random
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
import requests

site = pywikibot.Site("wikidata", "wikidata")
repo = site.data_repository()
edit_group = "fa3ffa532b70"  # "{:x}".format(random.randrange(0, 2**48))

# query used:
# https://qlever.dev/wikidata/euqcXi
# https://qlever.dev/wikidata/?query=PREFIX+wd%3A+%3Chttp%3A%2F%2Fwww.wikidata.org%2Fentity%2F%3E%0APREFIX+wdt%3A+%3Chttp%3A%2F%2Fwww.wikidata.org%2Fprop%2Fdirect%2F%3E%0APREFIX+p%3A+%3Chttp%3A%2F%2Fwww.wikidata.org%2Fprop%2F%3E%0APREFIX+xsd%3A+%3Chttp%3A%2F%2Fwww.w3.org%2F2001%2FXMLSchema%23%3E%0APREFIX+wikibase%3A+%3Chttp%3A%2F%2Fwikiba.se%2Fontology%23%3E%0ASELECT+DISTINCT+%3Fitem+WHERE+%7B%0A++VALUES+%3Fprop+%7B%0A++++p%3AP854+p%3AP856+p%3AP953+p%3AP973+p%3AP1325+p%3AP2699+p%3AP2888+p%3AP8214%0A++%7D%0A++%3Fitem+%3Fprop+%3Fstatement+.%0A++%3Fstatement+%3FpsDirect+%3Furl+.%0A++FILTER%28%0A++++CONTAINS%28STR%28%3Furl%29%2C+%22youtube.com%22%29+%7C%7C%0A++++CONTAINS%28STR%28%3Furl%29%2C+%22youtu.be%22%29%0A++%29%0A%0A%7D%0A

load_dotenv()  # reads .env file in the current directory
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
YOUTUBE_VIDEOS_API_URL = "https://www.googleapis.com/youtube/v3/videos"
YOUTUBE_CHANNELS_API_URL = "https://www.googleapis.com/youtube/v3/channels"

URL_PROPERTIES = ["P854", "P856", "P953", "P973", "P1325", "P2699", "P2888", "P8214"]

# This video is no longer available because the YouTube account associated with this video has been terminated.
# reason for deprecation: deactivated account (Q56631052)
# This video is private
# reason for deprecation: unavailable video (Q137217079)
# This video isn't available anymore
# reason for deprecation: unavailable video (Q137217079)


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

    def mark_failed(self, qid: str, error: Exception) -> None:
        e = str(error)
        if len(e) > 255:
            e = e[:252] + "..."
        self.execute_procedure(
            "UPDATE OR INSERT INTO qids (qid, status, error_msg) VALUES (?, ?, ?)",
            (qid, "failed", e),
        )

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

    def is_processed(self, qid: str) -> bool:
        """Return True if the QID has any existing record (success or failure)."""
        rows = self.execute_query("SELECT status FROM qids WHERE qid = ?", (qid,))
        return bool(rows)

    def mark_success(self, qid: str, summary: str):
        self.execute_procedure(
            "UPDATE OR INSERT INTO qids (qid, status, summary) VALUES (?, ?, ?)",
            (qid, "success", summary),
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
        "af": wd.QID_AFRIKAANS,
        "ar": wd.QID_ARABIC,
        "az": wd.QID_AZERBAIJANI,
        "bg": wd.QID_BULGARIAN,
        "bn": wd.QID_BANGLA,
        "cs": wd.QID_CZECH,
        "da": wd.QID_DANISH,
        "de": wd.QID_GERMAN,
        "el": wd.QID_GREEK,
        "en": wd.QID_ENGLISH,
        "eo": wd.QID_ESPERANTO,
        "es": wd.QID_SPANISH,
        "et": wd.QID_ESTONIAN,
        "eu": wd.QID_BASQUE,
        "fa": wd.QID_PERSIAN,
        "fi": wd.QID_FINNISH,
        "fr": wd.QID_FRENCH,
        "he": wd.QID_HEBREW,
        "hi": wd.QID_HINDI,
        "hr": wd.QID_CROATIAN,
        "hu": wd.QID_HUNGARIAN,
        "id": wd.QID_INDONESIAN,
        "it": wd.QID_ITALIAN,
        "iw": wd.QID_HEBREW,
        "ja": wd.QID_JAPANESE,
        "ka": wd.QID_GEORGIAN,
        "ko": wd.QID_KOREAN,
        "lt": wd.QID_LITHUANIAN,
        "lv": wd.QID_LATVIAN,
        "mi": wd.QID_MAORI,
        "mr": wd.QID_MARATHI,
        "nl": wd.QID_DUTCH,
        "pa": wd.QID_PUNJABI,
        "pl": wd.QID_POLISH,
        "pt": wd.QID_PORTUGUESE,
        "ro": wd.QID_ROMANIAN,
        "ru": wd.QID_RUSSIAN,
        "sl": wd.QID_SLOVENE,
        "sr": wd.QID_SERBIAN,
        "sv": wd.QID_SWEDISH,
        "sw": wd.QID_SWAHILI,
        "ta": wd.QID_TAMIL,
        "tr": wd.QID_TURKISH,
        "uk": wd.QID_UKRAINIAN,
        "und": wd.QID_UNDETERMINED_LANGUAGE,
        "ur": wd.QID_URDU,
        "uz": wd.QID_UZBEK,
        "yo": wd.QID_YORUBA,
        "yue": wd.QID_YUE_CHINESE,
        "zh": wd.QID_CHINESE,
        "zxx": wd.QID_NO_LINGUISTIC_CONTENT,
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
        match = re.match(r"/(?:embed|v|shorts|live)/([^/?]+)", parsed.path)
        if match:
            return match.group(1)
        else:
            raise ValueError(f"Could not extract video ID from YouTube URL: {url}")
    return None


def resolve_youtube_custom_url(url: str) -> str | None:
    """
    Resolve legacy /c/, /user/, /channel/ URLs to a @handle or channel ID.
    Returns the handle (without @) or channel ID extracted from the final URL.
    """
    try:
        r = requests.get(url, allow_redirects=True, timeout=10)
        final_url = r.url  # e.g. https://www.youtube.com/@medlifecrisis
        parsed = urlparse(final_url)
        path = parsed.path  # e.g. /@medlifecrisis or /channel/UCxxx

        if path.startswith("/@"):
            return strip_at(path[1:])  # strip leading / and @
        if path.startswith("/channel/"):
            return path.replace("/channel/", "")  # returns raw UCxxx ID
    except Exception as e:
        pywikibot.error(f"Failed to resolve YouTube URL {url}: {e}")
    return None


def check_youtube_url(url: str) -> str | None:
    """
    Check if the URL is a YouTube URL that can be resolved to a cleaner format.
    If so, return the cleaner URL (e.g. with @handle or channel ID). Otherwise, return None.
    """
    if "youtube.com" in url or "youtu.be" in url:
        handle_or_id = resolve_youtube_custom_url(url)
        if handle_or_id:
            if handle_or_id.startswith("UC"):
                return f"https://www.youtube.com/channel/{handle_or_id}"
            else:
                return f"https://www.youtube.com/@{handle_or_id}"
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
    if not handle:
        return None
    pid = wd.PID_YOUTUBE_HANDLE
    clean_handle = strip_at(handle)
    query = f"""
    SELECT ?item WHERE {{
      ?item wdt:{pid} "{clean_handle}" .
    }}
    LIMIT 1
    """
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


def always_ignore(qid: str) -> bool:
    """Return True for global YouTube-related QIDs to skip processing."""
    ignored_qids = {
        "Q112247183",  # YouTube LLC
        "Q41697543",  # YouTube
        "Q125499732",  # YouTube Music
        "Q866",  # YouTube
        "Q28404534",  # YouTube Music
        "Q125499708",  # YouTube Studio
        "Q115926044",  # YouTube Studio
        "Q53720737",  # YouTube TV
        "Q110227693",  # YouTube website
        "Q18157148",  # YouTube
        "Q116733536",  # YouTube Music Global Charts
        "Q15128315",  # YouTube Music Awards
        "Q111772254",  # YouTube Standard License
        "Q99438379",  # YouTube Shorts
        "Q98987800",  # YouTube auto-generated game page
        "Q61942967",  # Diamond Play Button
        "Q55020669",  # YouTube Gaming
        "Q21411063",  # YouTube Space
        "Q18643737",  # YouTube Premium
        "Q18157145",  # YouTube Creator Awards
    }
    return qid in ignored_qids


def specific_ignore(qid: str) -> bool:
    """Return True for global YouTube-related QIDs to skip processing."""
    ignored_qids = {
        "Q130259713",  # Domian Parodie
    }
    return qid in ignored_qids


def is_link_rot(claim) -> bool:
    # online access status (P6954)
    if wd.PID_ONLINE_ACCESS_STATUS in claim.qualifiers:
        for qualifier in claim.qualifiers[wd.PID_ONLINE_ACCESS_STATUS]:
            if qualifier.getTarget().id == wd.QID_LINK_ROT:
                return True
    return False


def process_item(qid, tracker: ChannelHandleTracker, test=True):
    if always_ignore(qid):
        tracker.mark_success(qid, "Skipped (always-ignore list)")
        pywikibot.output(f"  Skipping {qid} (in always-ignore list)")
        return
    if specific_ignore(qid):
        tracker.mark_success(qid, "Skipped (specific-ignore list)")
        pywikibot.output(f"  Skipping {qid} (in specific-ignore list)")
        return
    item = pywikibot.ItemPage(repo, qid)
    page = cwd.WikiDataPage(item, test=test)
    page.edit_group = edit_group

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
            # change_url = check_youtube_url(target)
            # if change_url and change_url != target:
            #     page.change_claim(prop_id, claim, change_url)
            #     continue
            video_id = extract_video_id(target)
            if not video_id:
                continue
            if is_link_rot(claim):
                pywikibot.output(f"  Skipping {target} (link rot suspected)")
                continue
            video_to_claims.setdefault(video_id, []).append((prop_id, claim))

    if not video_to_claims:
        tracker.mark_success(qid, "No YouTube URLs found")
        pywikibot.output(f"  Not found any YouTube URLs on {qid}")
        return

    pywikibot.output(f"  Found {len(video_to_claims)} unique YouTube video(s) on {qid}")

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
        if lang_code == "iw":
            lang_code = "he"  # YouTube uses 'iw' for Hebrew, but Wikidata uses 'he'
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
                # case insensitive check
                elif existing_handle.lower() != clean_handle.lower():
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
    if page.apply():
        summary = page.used_summary or ""
        if test:
            summary = f"(DRY RUN) {summary}"
        tracker.mark_success(qid, summary)
    else:
        tracker.mark_success(qid, "Nothing done")


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------


def check_video_availability(video_id: str) -> str:
    url = f"https://www.youtube.com/watch?v={video_id}"
    response = requests.get(url, headers={"Accept-Language": "en-US"})

    if "Video unavailable" in response.text:
        response = "Video is deleted or removed"
    elif "This video has been removed" in response.text:
        response = "Video was removed by YouTube"
    else:
        response = "Video likely exists"

    return response


def load_items_from_file(filename):
    with open(filename, "r", encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip()]


def main():
    # print(lookup_channel_qid("UCmh7afBz-uWwOSSNTqUBAhg"))
    tracker = ChannelHandleTracker()  # shared across all items
    # items = ["Q123306649"]
    items = load_items_from_file(r"D:\python\wikidata\projects\clean_url\items.csv")
    for qid in items:
        pywikibot.output(f"Processing {qid}...")
        try:
            if tracker.is_processed(qid):
                continue
            process_item(qid, tracker=tracker, test=False)
        except Exception as e:
            tracker.mark_failed(qid, e)
            print(f"Error processing {qid}: {e}")


if __name__ == "__main__":
    main()
