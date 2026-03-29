import os
import re
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pywikibot
import requests
from database_handler import DatabaseHandler
from dotenv import load_dotenv

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
# Qualifier helpers
# ---------------------------------------------------------------------------


def qualifier_already_exists(claim, qualifier_pid):
    return qualifier_pid in claim.qualifiers


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

    # ── Step 4: Apply qualifiers ─────────────────────────────────────────────
    for video_id, claims_list in video_to_claims.items():
        meta = metadata.get(video_id)
        if not meta:
            raise ValueError(f"No metadata for video {video_id}")

        handle = channel_handles.get(meta.get("channel_id"))
        pywikibot.output(f"  Video {video_id}: '{meta['title']}' / handle: {handle}")

        for prop_id, claim in claims_list:

            # P1476 title (monolingual text)
            if meta["title"] and not qualifier_already_exists(claim, wd.PID_TITLE):
                lang = (meta["audio_language"] or "en").split("-")[0]
                page.add_qualifier(
                    prop_id,
                    claim,
                    cwd.MonolingualTextQualifier(wd.PID_TITLE, meta["title"], lang),
                )

            # P577 publication date
            if meta["published_at"] and not qualifier_already_exists(
                claim, wd.PID_PUBLICATION_DATE
            ):
                date_str = meta["published_at"][
                    :10
                ]  # "2021-08-15T12:34:56Z" -> "2021-08-15"
                y, m, d = map(int, date_str.split("-"))
                page.add_qualifier(
                    prop_id,
                    claim,
                    cwd.DateQualifier(
                        wd.PID_PUBLICATION_DATE, date_value.Date(y, m, d)
                    ),
                )

            # P2047 duration in seconds
            if meta["duration_seconds"] and not qualifier_already_exists(
                claim, wd.PID_DURATION
            ):
                amount, unit_qid = get_duration_for_wikidata(meta["duration_seconds"])
                page.add_qualifier(
                    prop_id,
                    claim,
                    cwd.QuantityQualifier(wd.PID_DURATION, amount, unit_qid),
                )

            # P11245 YouTube handle
            if handle and not qualifier_already_exists(
                claim, wd.PID_YOUTUBE_CHANNEL_ID
            ):
                page.add_qualifier(
                    prop_id,
                    claim,
                    cwd.StringQualifier(wd.PID_YOUTUBE_CHANNEL_ID, handle),
                )

            # P407 language of work
            if meta["audio_language"] and not qualifier_already_exists(
                claim, wd.PID_LANGUAGE_OF_WORK_OR_NAME
            ):
                lang_qid = language_code_to_qid(meta["audio_language"])
                page.add_qualifier(
                    prop_id,
                    claim,
                    cwd.ItemQualifier(wd.PID_LANGUAGE_OF_WORK_OR_NAME, lang_qid),
                )

    page.summary = "Add YouTube metadata qualifiers"
    page.apply()


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------


def load_items_from_file(filename):
    with open(filename, "r", encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip()]


def main():
    tracker = ChannelHandleTracker()  # shared across all items
    items = [wd.QID_WIKIDATASANDBOX3]
    # items = load_items_from_file("items.csv")
    for qid in items:
        pywikibot.output(f"Processing {qid}...")
        process_item(qid, tracker=tracker, test=False)


if __name__ == "__main__":
    main()
