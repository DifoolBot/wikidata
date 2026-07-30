#!/usr/bin/env python3
"""Retrospective detector for the "warm-up gnome + promo payload" account
signature (the Johnpacklamber1 pattern).

Idea: an operator warms up an account with lots of cheap, formulaic term edits
(mostly "Added missing description" on established notable items) to build a
non-single-purpose history, then drops a small self-referential promo cluster
(a founder + their company, interlinked, no editorial identifier). The warm-up
defeats a naive single-purpose-account filter, so we score the *conjunction*:
warm-up history AND a payload creation.

READ-ONLY. It fetches from the public API and prints a ranked review list.
It makes no edits and nominates nothing. Output is decision support for a human.

Usage (from repo root):
    python projects/detect_promo/detect_promo_accounts.py --hours 24
    python projects/detect_promo/detect_promo_accounts.py --hours 72 --max-accounts 80
    python projects/detect_promo/detect_promo_accounts.py --user Johnpacklamber1   # score one account

Notes:
- The property/class sets below are a STARTER list to be tuned on real output.
- "Warm-up alone" is NOT flagged: legitimate gnomes add missing descriptions.
  Only warm-up + a payload item (or, later, a shared fingerprint across
  accounts) is suspicious.
"""

import argparse
import datetime as dt
import io
import re
import sys
import time
from collections import defaultdict

import requests

API = "https://www.wikidata.org/w/api.php"
HEADERS = {
    # Identify the tool via the bot's user page
    "User-Agent": (
        "DifoolBot promo-account detector "
        "(https://www.wikidata.org/wiki/User:DifoolBot)"
    )
}
SESSION = requests.Session()
SLEEP = 0.1  # courtesy delay between calls

# Wikidata autoconfirmed thresholds (per Wikidata:Autoconfirmed_users): >= 50
# edits AND FIRST EDIT >= 4 days old (age is measured from the first edit, not
# registration). Payoff of reaching it: edits are patrolled automatically
# (escape the patrol queue), mass-editing tools unlock, and the CAPTCHA drops --
# i.e. reduced scrutiny + smoother automation.
AUTOCONFIRM_DAYS = 4
AUTOCONFIRM_EDITS = 50

# --- Starter property / class sets (tune these) ----------------------------

# Term edits (label/description/aliases) via the Wikibase API carry these
# structured auto-comment prefixes; used to recognise the warm-up edits.
TERM_COMMENT_RE = re.compile(
    r"/\*\s*wbset(label|description|aliases|labeldescriptionaliases)", re.I
)
# The custom appended summary that fingerprints this operation.
BOILERPLATE_RE = re.compile(r"added (missing )?(\[?\w{2,3}\]?\s*)?descriptions?", re.I)

# Third-party, editorially-assigned authority identifiers. Deliberately global;
# ISNI is left out on purpose (self-registerable / weak, per the VIAF/ISNI
# discussion), and a VIAF ideally needs cluster-composition checking.
EDITORIAL_ID_PROPS = {
    "P214",  # VIAF (weak alone; here as a coarse signal)
    "P227",  # GND
    "P244",  # Library of Congress authority ID
    "P268",  # BnF
    "P269",  # IdRef (SUDOC)
    "P245",  # ULAN
    "P349",  # NDL (Japan)
    "P409",  # Libraries Australia
    "P906",  # SELIBR (Sweden)
    "P950",  # Biblioteca Nacional de Espana
    "P1006",  # Nationale Thesaurus (NL)
    "P1015",  # NORAF (Norway)
}
# Self-issued / social / weak identifiers -- presence does NOT reduce suspicion.
SELF_ISSUED_ID_PROPS = {
    "P2088",  # Crunchbase person
    "P496",  # ORCID
    "P2003",  # Instagram
    "P2013",  # Facebook
    "P2397",  # YouTube channel
    "P4264",  # LinkedIn company
    "P6634",  # LinkedIn personal
}
# Relationship properties linking two items the same account created. Tiered,
# because the shapes are not equally suspicious:
#
# STRONG -- person <-> the organisation they own/run. When the company is
# effectively a one-person operation, the two items are one subject counted
# twice, each bootstrapping the other's existence. This is the vanity archetype
# (founder <-> their own company).
CLUSTER_PROPS_STRONG = {
    "P108",  # employer
    "P112",  # founded by
    "P169",  # chief executive officer
    "P127",  # owned by
    "P1830",  # owner of
    "P3320",  # board member
}
# WEAK -- a thing <-> its maker/creator. This is NORMAL modelling (Apple <->
# iPhone, author <-> book), so on its own it means little; it only matters in
# combination with the other payload signals.
CLUSTER_PROPS_WEAK = {
    "P178",  # developer  (app <-> developer company)
    "P176",  # manufacturer
    "P123",  # publisher
    "P170",  # creator
    "P50",  # author
    "P800",  # notable work
}
# instance of (P31) values that mark a person / company / org payload.
PAYLOAD_P31 = {
    "Q5",  # human
    "Q4830453",  # business
    "Q783794",  # company
    "Q6881511",  # enterprise
    "Q891723",  # public company
    "Q43229",  # organization
    "Q167037",  # corporation
    "Q431289",  # brand
}


def api_get(params: dict) -> dict:
    params = {**params, "format": "json", "formatversion": "2"}
    r = SESSION.get(API, params=params, headers=HEADERS, timeout=60)
    r.raise_for_status()
    time.sleep(SLEEP)
    return r.json()


def paginate(params: dict, listname: str):
    """Yield entries from a list= query, following continuation."""
    while True:
        data = api_get(params)
        for entry in data.get("query", {}).get(listname, []):
            yield entry
        cont = data.get("continue")
        if not cont:
            return
        params = {**params, **cont}


def get_new_items(hours: int, limit: int) -> list[dict]:
    """New items (ns0 page creations) by registered users within the window."""
    cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=hours)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    params = {
        "action": "query",
        "list": "recentchanges",
        "rcnamespace": "0",
        "rctype": "new",
        "rcshow": "!anon",
        "rcprop": "title|ids|user|timestamp|comment|sizes|tags",
        "rclimit": "500",
        "rcend": cutoff,
    }
    out = []
    for e in paginate(params, "recentchanges"):
        out.append(
            {
                "qid": e.get("title"),
                "user": e.get("user"),
                "timestamp": e.get("timestamp"),
                "newlen": e.get("newlen", 0),
                "comment": e.get("comment", ""),
                "tags": e.get("tags", []),
            }
        )
        if len(out) >= limit:
            break
    return out


def get_contribs(user: str, limit: int = 500) -> list[dict]:
    params = {
        "action": "query",
        "list": "usercontribs",
        "ucuser": user,
        "ucnamespace": "0",
        "ucprop": "title|timestamp|comment|sizediff|flags|tags|ids",
        "uclimit": "500",
    }
    out = []
    for e in paginate(params, "usercontribs"):
        out.append(e)
        if len(out) >= limit:
            break
    return out


def parse_ts(ts: str) -> dt.datetime:
    return dt.datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=dt.timezone.utc
    )


def get_registration(user: str) -> tuple[str | None, int | None]:
    data = api_get(
        {
            "action": "query",
            "list": "users",
            "ususers": user,
            "usprop": "registration|editcount",
        }
    )
    users = data.get("query", {}).get("users", [])
    if users:
        return users[0].get("registration"), users[0].get("editcount")
    return None, None


def get_first_edits(user: str, n: int = AUTOCONFIRM_EDITS) -> list[dict]:
    """The account's OLDEST n edits (all namespaces -- autoconfirmed counts all),
    to see how it opened."""
    params = {
        "action": "query",
        "list": "usercontribs",
        "ucuser": user,
        "ucprop": "timestamp|comment|flags",
        "uclimit": str(n),
        "ucdir": "newer",  # oldest first
    }
    out = []
    for e in paginate(params, "usercontribs"):
        out.append(e)
        if len(out) >= n:
            break
    return out


def score_farming(reg: str | None, first_edits: list[dict]) -> dict:
    """Autoconfirmed-farming signal: a front-loaded, boilerplate-heavy opening
    burst that trips autoconfirmed at ~the minimum. The age gate is measured
    from the FIRST EDIT, so the span of the first 50 edits is measured there too
    -- which also catches 'sleeper' accounts (registered long ago, activated
    recently). A genuine gnome accumulates gradually; a farmer burns the first
    50 edits inside the 4-day age window."""
    n = len(first_edits)
    boiler = sum(
        1 for e in first_edits if BOILERPLATE_RE.search(e.get("comment", "") or "")
    )
    boiler_frac = boiler / n if n else 0.0
    days_span_50 = None
    if n >= AUTOCONFIRM_EDITS:
        try:
            days_span_50 = (
                parse_ts(first_edits[AUTOCONFIRM_EDITS - 1]["timestamp"])
                - parse_ts(first_edits[0]["timestamp"])
            ).total_seconds() / 86400
        except (ValueError, KeyError):
            days_span_50 = None
    farmed = (
        boiler_frac >= 0.5
        and days_span_50 is not None
        and (days_span_50 <= AUTOCONFIRM_DAYS + 1)
    )
    return {
        "registration": reg,
        "first_n": n,
        "first_boiler_frac": boiler_frac,
        "days_to_50_edits": (
            round(days_span_50, 2) if days_span_50 is not None else None
        ),
        "farmed": farmed,
    }


def add_farming(user: str, acct: dict) -> None:
    reg, _ = get_registration(user)
    acct.update(score_farming(reg, get_first_edits(user)))


def score_account(contribs: list[dict]) -> dict:
    """Warm-up fingerprint metrics from a contribution sample."""
    total = len(contribs)
    term = boiler = small = reverted = ui = untagged = 0
    created_qids = set()
    minute_buckets = defaultdict(int)
    for e in contribs:
        comment = e.get("comment", "") or ""
        if TERM_COMMENT_RE.search(comment):
            term += 1
        if BOILERPLATE_RE.search(comment):
            boiler += 1
        if abs(e.get("sizediff", 0) or 0) < 150:
            small += 1
        tags = e.get("tags", []) or []
        if "mw-reverted" in tags:
            reverted += 1
        if "wikidata-ui" in tags:
            ui += 1
        if not tags:
            untagged += 1  # no UI tag, no tool tag -> raw API
        if e.get("new"):
            created_qids.add(e.get("title"))
        ts = (e.get("timestamp", "") or "")[:16]  # minute resolution
        if ts:
            minute_buckets[ts] += 1
    max_burst = max(minute_buckets.values()) if minute_buckets else 0
    return {
        "total": total,
        "boilerplate_frac": boiler / total if total else 0.0,
        "term_frac": term / total if total else 0.0,
        "small_frac": small / total if total else 0.0,
        "reverted": reverted,
        "max_burst_per_min": max_burst,
        "ui_frac": ui / total if total else 0.0,
        "raw_api_frac": untagged / total if total else 0.0,
        "created_qids": created_qids,
    }


def get_entities(qids: list[str]) -> dict:
    """Batch wbgetentities claims + sitelinks (50 ids per call).

    Sitelinks matter because a valid one satisfies WD:N criterion 1 on its own.
    """
    result = {}
    for i in range(0, len(qids), 50):
        batch = qids[i : i + 50]
        data = api_get(
            {
                "action": "wbgetentities",
                "ids": "|".join(batch),
                "props": "claims|sitelinks|labels|descriptions",
            }
        )
        result.update(data.get("entities", {}))
    return result


# A linked item with fewer statements than this, no sitelink and no editorial
# identifier is treated as a shell rather than a substantive entity.
THIN_CLAIM_LIMIT = 10


def _is_thin(entity: dict) -> bool:
    """Is this linked item a shell rather than a substantive entity?

    Apple is not thin (thousands of claims, sitelinks, authority ids); a
    month-old one-person Ltd whose website is its own product's domain is.
    Used to promote a 'weak' thing<->maker link to the vanity tier.
    """
    if not entity:
        return False  # unknown -> never promote on missing data
    if entity.get("sitelinks"):
        return False
    claims = entity.get("claims", {}) or {}
    if any(p in claims for p in EDITORIAL_ID_PROPS):
        return False
    return sum(len(v) for v in claims.values()) < THIN_CLAIM_LIMIT


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def _site_domain(claims: dict) -> str:
    """Registrable-ish domain from P856, e.g. https://www.logitot.com/x -> logitot."""
    for c in claims.get("P856", []):
        url = c.get("mainsnak", {}).get("datavalue", {}).get("value", "")
        if isinstance(url, str) and url:
            host = re.sub(r"^https?://(www\.)?", "", url).split("/")[0]
            return host.rsplit(".", 1)[0] if "." in host else host
    return ""


def username_match(creator: str, entity: dict) -> str | None:
    """Does the creator's username match the item's label or its website domain?

    The classic COI tell: 'Andacyesilyurt' creating an item whose site is
    andacyesilyurt.com, or 'FinalCorners' creating 'Final Corners Record'.
    Requires >=5 normalised chars so short names don't collide by accident.
    """
    u = _norm(creator)
    if len(u) < 5:
        return None

    def close(a: str, b: str) -> bool:
        return bool(a) and bool(b) and (a == b or a.startswith(b) or b.startswith(a))

    for lab in (entity.get("labels") or {}).values():
        if close(_norm(lab.get("value", "")), u):
            return "label"
    if close(_norm(_site_domain(entity.get("claims") or {})), u):
        return "domain"
    return None


def _claim_targets(claims: dict, pid: str) -> list[str]:
    out = []
    for c in claims.get(pid, []):
        val = c.get("mainsnak", {}).get("datavalue", {}).get("value")
        if isinstance(val, dict) and "id" in val:
            out.append(val["id"])
    return out


def score_payload(
    qid: str,
    entity: dict,
    own_created: set[str],
    ent_map: dict | None = None,
    creator: str | None = None,
) -> dict:
    """Payload signals for one created item (pass the whole wbgetentities entity).

    ent_map (all fetched entities) lets a weak thing<->maker link be promoted to
    the vanity tier when the linked item turns out to be a shell.
    """
    claims = entity.get("claims", {}) or {}
    sitelinks = entity.get("sitelinks", {}) or {}
    p31 = set(_claim_targets(claims, "P31"))
    is_payload_type = bool(p31 & PAYLOAD_P31)
    has_promo_site = "P856" in claims
    has_editorial_id = any(p in claims for p in EDITORIAL_ID_PROPS)
    has_self_id = any(p in claims for p in SELF_ISSUED_ID_PROPS)
    # Non-circular check: does it link (via cluster props) to ANOTHER item the
    # same account created?  That is the self-bootstrapped founder<->company loop.
    def _circular(props: set[str]) -> set[str]:
        found = set()
        for pid in props:
            for target in _claim_targets(claims, pid):
                if target != qid and target in own_created:
                    found.add(target)
        return found

    circular_strong = _circular(CLUSTER_PROPS_STRONG)
    circular_weak = _circular(CLUSTER_PROPS_WEAK)
    # A circular link only means anything when the LINKED item is itself an
    # unattested shell. P108 (employer) etc. are ordinary biographical
    # properties: a French journalist linked to the BnF-catalogued newspapers he
    # wrote for is normal scholarly modelling, not a vanity pair. What made
    # Melkon<->Direlli suspicious was not the link but that Direlli was a shell
    # invented the same day. So filter BOTH tiers by the linked item's substance.
    if ent_map is not None:
        circular_strong = {
            t for t in circular_strong if _is_thin(ent_map.get(t, {}))
        }
        circular_weak = {t for t in circular_weak if _is_thin(ent_map.get(t, {}))}
    circular = circular_strong | circular_weak
    return {
        "is_payload_type": is_payload_type,
        "has_promo_site": has_promo_site,
        "has_editorial_id": has_editorial_id,
        "has_self_id": has_self_id,
        "circular_links": sorted(circular),
        "circular_strong": sorted(circular_strong),
        "circular_weak": sorted(circular_weak),
        "sitelinks": sorted(sitelinks),
        "has_sitelink": bool(sitelinks),
        "username_match": username_match(creator, entity) if creator else None,
        # Kept for the human-readable table
        "label": next(
            (v.get("value") for v in (entity.get("labels") or {}).values()), ""
        ),
        "description": next(
            (v.get("value") for v in (entity.get("descriptions") or {}).values()), ""
        ),
        "domain": _site_domain(claims),
        "n_claims": sum(len(v) for v in claims.values()),
    }


def payload_points(p: dict) -> int:
    """Payload suspicion. 'No editorial id' is deliberately NOT scored: at
    creation time almost every new item lacks one (identifiers lag creation),
    so it does not discriminate. The real tells are a self-referential cluster
    link, a promo website on a fresh person/org, and self-issued-only ids."""
    # A valid sitelink satisfies WD:N criterion 1 outright, so the item is
    # notable on Wikidata regardless of its content and is NOT actionable here --
    # any concern belongs at the linked wiki. Score 0 so the review list stops
    # pointing at items that cannot be acted on. (The flag is kept in the dict
    # so the report can still show it: a brand-new account creating both an item
    # and its sole-authored sitelinked article is notability laundering, but the
    # venue for that is the wiki, not Wikidata.)
    if p.get("has_sitelink"):
        return 0
    pts = 0
    if p.get("username_match"):
        pts += 3  # creator's username == the subject / its domain: the COI tell
    # An editorial authority identifier means the subject is externally
    # catalogued, so two linked items are almost certainly legitimate related
    # creations (an established editor adding a person + their work) rather than
    # a bootstrapped vanity pair. Don't score circularity in that case.
    # Both tiers are already filtered to links whose TARGET is an unattested
    # shell, so reaching here means "linked to something this account invented".
    if not p["has_editorial_id"]:
        if p.get("circular_strong"):
            pts += 3  # person <-> their own shell company: the vanity archetype
        elif p.get("circular_weak"):
            pts += 2  # product <-> its shell maker: same structure, person absent
    if p["has_promo_site"]:
        pts += 2  # P856 on a brand-new person/org is the SEO tell
    if p["is_payload_type"]:
        pts += 1
    if p["has_self_id"] and not p["has_editorial_id"]:
        pts += 1
    return pts


def warmup_points(a: dict) -> int:
    """The warm-up fingerprint is the boilerplate description operation itself;
    generic 'many small fast edits' describes every legit gnome/bot, so it must
    not drive the score. Boilerplate gates it; timing and reverts only corroborate."""
    frac = a["boilerplate_frac"]
    if frac >= 0.8:
        pts = 4
    elif frac >= 0.5:
        pts = 3
    elif frac >= 0.3:
        pts = 2
    else:
        pts = 0
    if pts:
        if a["max_burst_per_min"] >= 6:
            pts += 1  # tool-speed corroboration
        if a["reverted"] >= 3:
            pts += 1  # AI-description error pattern
        if a.get("ui_frac", 1.0) == 0:
            pts += 1  # never touched the web UI -> raw-API/scripted from day one
    # Front-loaded autoconfirmed farming scores even when the *recent* sample
    # is no longer boilerplate-heavy (an account that farmed then went quiet).
    if a.get("farmed"):
        pts += 2
    return pts


def analyse(users_items: dict, max_accounts: int) -> list[dict]:
    rows = []
    for i, (user, items) in enumerate(users_items.items()):
        if i >= max_accounts:
            break
        contribs = get_contribs(user)
        acct = score_account(contribs)
        add_farming(user, acct)
        own = acct["created_qids"] | {it["qid"] for it in items}
        ent_map = get_entities([it["qid"] for it in items])
        best = None
        payloads = []
        for it in items:
            pay = score_payload(
                it["qid"], ent_map.get(it["qid"], {}), own, ent_map, user
            )
            pay["qid"] = it["qid"]
            pay["newlen"] = it["newlen"]
            pay["via_ui"] = "wikidata-ui" in it["tags"]
            payloads.append(pay)
            if best is None or payload_points(pay) > payload_points(best):
                best = pay
        rows.append(
            {
                "user": user,
                "n_new_items": len(items),
                "warmup": acct,
                "warmup_pts": warmup_points(acct),
                "payload": best,
                "payloads": payloads,
                "payload_pts": payload_points(best) if best else 0,
            }
        )
    rows.sort(key=lambda r: (r["warmup_pts"] + r["payload_pts"]), reverse=True)
    return rows


def describe(p: dict, user: str, acct: dict) -> tuple[str, str]:
    """Human-readable ('what it is', 'tell') for the triage table.

    Only mechanical signals go in the tell -- judgement calls like "this reads
    like marketing copy" are left to the reader, which is why the label and
    description are shown verbatim.
    """
    label, desc = p.get("label") or "", p.get("description") or ""
    if label and desc:
        what = f'"{label}" — {desc}'
    elif label:
        what = f'"{label}"'
    elif p.get("domain"):
        what = f"(no label) — {p['domain']}"
    else:
        what = "(no label, no description)"

    tells = []
    if p.get("has_sitelink"):
        tells.append(f"SHIELDED: WD:N crit.1 via {','.join(p['sitelinks'])}")
    if p.get("username_match") == "domain":
        tells.append(f"username = site domain ({user} / {p.get('domain')})")
    elif p.get("username_match") == "label":
        tells.append(f"username = subject ({user})")
    for key, tier in (("circular_strong", "strong"), ("circular_weak", "weak")):
        if p.get(key):
            tells.append(f"links to own shell {','.join(p[key])} [{tier}]")
    if p.get("has_promo_site"):
        tells.append(f"promo site ({p.get('domain')})")
    if p.get("has_self_id") and not p.get("has_editorial_id"):
        tells.append("self-issued IDs only")
    if p.get("has_editorial_id"):
        tells.append("has editorial ID")
    if acct.get("farmed"):
        tells.append("FARMED autoconfirmed")
    if (reg := acct.get("registration")) and reg[:10] >= (
        dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=14)
    ).strftime("%Y-%m-%d"):
        tells.append(f"new account ({reg[:10]}, {acct.get('total', '?')} edits)")
    if (p.get("n_claims") or 0) < THIN_CLAIM_LIMIT:
        tells.append(f"thin ({p.get('n_claims')} claims)")
    return what, "; ".join(tells) or "-"


def print_table(rows: list[dict], min_score: int = 2) -> None:
    """Item-centric triage table: scan 'what it is' + 'tell', open what matters.

    Default floor is 2 deliberately. Score 1 is usually just "it is a person and
    it is thin", which describes most legitimate new biographies -- including the
    under-documented subjects we least want to bother. Shielded items score 0 and
    drop out here too: they are not actionable on Wikidata by definition.
    """
    items = []
    for r in rows:
        for p in r.get("payloads") or []:
            pts = payload_points(p)
            if pts < min_score:
                continue
            what, tell = describe(p, r["user"], r["warmup"])
            items.append((pts, p["qid"], what, tell, r["user"]))
    items.sort(reverse=True)
    print(f"\n| # | Item | What it is | Tell | Creator |")
    print("|---|---|---|---|---|")
    for pts, qid, what, tell, user in items:
        what = what.replace("|", "/")[:90]
        tell = tell.replace("|", "/")
        print(f"| {pts} | {qid} | {what} | {tell} | {user} |")
    print(f"\n{len(items)} item(s) flagged. Open by QID; the tell says why.")


def print_report(rows: list[dict]) -> None:
    print("\n=== promo-account review list (read-only) ===")
    print(
        "suspicion = warmup_pts + payload_pts; PROMO = payload alone (the common\n"
        "case: fresh single-purpose vanity accounts), WARMUP+PAYLOAD = the rare\n"
        "warm-up-then-payload unicorn\n"
    )
    for r in rows:
        total = r["warmup_pts"] + r["payload_pts"]
        a = r["warmup"]
        p = r["payload"] or {}
        # Flag priority: a valid sitelink shields the item (WD:N crit.1) so it is
        # never actionable here, whatever it scores. Otherwise the warm-up+payload
        # conjunction is the high-value catch, but empirically the common hit is
        # PAYLOAD-ONLY -- a fresh account (warmup=0) whose item screams promo: a
        # strong payload score, a username==subject match, or a self-referential
        # founder<->company circular link. The old flag required warmup>=2, so it
        # never fired on exactly these; PROMO fixes that.
        flag = ""
        if p.get("has_sitelink"):
            flag = ""
        elif r["warmup_pts"] >= 2 and r["payload_pts"] >= 3:
            flag = "  <-- WARMUP+PAYLOAD (unicorn)"
        elif (
            r["payload_pts"] >= 4
            or p.get("username_match")
            or p.get("circular_strong")
        ):
            flag = "  <-- PROMO"
        print(
            f"[{total:2d}] {r['user']}{flag}\n"
            f"      warmup pts={r['warmup_pts']} "
            f"(edits={a['total']} boiler={a['boilerplate_frac']:.0%} "
            f"term={a['term_frac']:.0%} small={a['small_frac']:.0%} "
            f"burst/min={a['max_burst_per_min']} reverted={a['reverted']} "
            f"ui={a['ui_frac']:.0%} raw_api={a['raw_api_frac']:.0%})\n"
            f"      farming: farmed={a.get('farmed')} "
            f"first{a.get('first_n')}_boiler={a.get('first_boiler_frac', 0):.0%} "
            f"days_to_50={a.get('days_to_50_edits')} reg={a.get('registration')}\n"
            f"      payload pts={r['payload_pts']} item={p.get('qid')} "
            f"newlen={p.get('newlen')} via_ui={p.get('via_ui')} "
            f"type={p.get('is_payload_type')} promo={p.get('has_promo_site')} "
            f"editorial_id={p.get('has_editorial_id')} "
            f"self_id={p.get('has_self_id')} "
            f"circ_strong={p.get('circular_strong')} "
            f"circ_weak={p.get('circular_weak')}"
            + (
                f"\n      SHIELDED: WD:N criterion 1 via {','.join(p['sitelinks'])}"
                " -> notable on Wikidata regardless of content; raise any"
                " concern at the linked wiki, not here"
                if p.get("has_sitelink")
                else ""
            )
        )


def score_user_row(user: str) -> dict:
    """Full per-account scoring (warm-up + farming + payload from the account's
    own live-created items). Used by the batch check over Quarry candidates."""
    contribs = get_contribs(user)
    acct = score_account(contribs)
    add_farming(user, acct)
    own = acct["created_qids"]
    best = None
    if own:
        ent_map = get_entities(sorted(own))
        for qid in sorted(own):
            pay = score_payload(qid, ent_map.get(qid, {}), own, ent_map)
            pay["qid"] = qid
            pay["newlen"] = None
            pay["via_ui"] = None
            if best is None or payload_points(pay) > payload_points(best):
                best = pay
    return {
        "user": user,
        "warmup": acct,
        "warmup_pts": warmup_points(acct),
        "payload": best,
        "payload_pts": payload_points(best) if best else 0,
    }


def batch_users(path: str) -> None:
    """Score a file of usernames (one per line; Quarry candidate list) and rank
    them. Note: a payload that was already DELETED is invisible here (usercontribs
    omits deleted edits), so a real farmer may show high warm-up + payload 0."""
    with open(path, encoding="utf-8") as fh:
        users = [ln.strip() for ln in fh if ln.strip() and not ln.startswith("#")]
    print(f"Scoring {len(users)} candidate accounts ...")
    rows = []
    for i, user in enumerate(users, 1):
        rows.append(score_user_row(user))
        if i % 20 == 0:
            print(f"  {i}/{len(users)} ...")
    rows.sort(key=lambda r: r["warmup_pts"] + r["payload_pts"], reverse=True)
    print_report(rows)


def single_user(user: str) -> None:
    contribs = get_contribs(user)
    acct = score_account(contribs)
    add_farming(user, acct)
    print(f"\n{user}: warmup_pts={warmup_points(acct)}")
    for k, v in acct.items():
        if k == "created_qids":
            print(f"  created_items={sorted(v)}")
        else:
            print(f"  {k}={v}")
    created = sorted(acct["created_qids"])
    if created:
        ent_map = get_entities(created)
        own = acct["created_qids"]
        for qid in created:
            pay = score_payload(qid, ent_map.get(qid, {}), own, ent_map)
            print(f"  payload {qid}: pts={payload_points(pay)} {pay}")


def main() -> None:
    # Wikidata usernames are international (Turkish dotted I, Armenian, Arabic,
    # CJK, Cyrillic...). Windows consoles and redirected stdout default to the
    # legacy code page (cp1252), which raises UnicodeEncodeError at print time --
    # after all the API work is already done. Force UTF-8 out. (reconfigure is
    # a TextIOWrapper method; isinstance both guards at runtime and narrows the
    # type for the checker, unlike hasattr.)
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--hours", type=int, default=24, help="look-back window")
    ap.add_argument("--limit", type=int, default=500, help="max new items to pull")
    ap.add_argument("--max-accounts", type=int, default=40)
    ap.add_argument("--user", help="score just this account and exit")
    ap.add_argument(
        "--table",
        action="store_true",
        help="print the item-centric triage table (what it is + tell) instead "
        "of the detailed signal dump",
    )
    ap.add_argument(
        "--min-score",
        type=int,
        default=2,
        help="table only: minimum payload score to list (default 2)",
    )
    ap.add_argument(
        "--users-file",
        help="score a file of usernames (one per line; e.g. a Quarry candidate "
        "list) and rank them",
    )
    args = ap.parse_args()

    if args.user:
        single_user(args.user)
        return
    if args.users_file:
        batch_users(args.users_file)
        return

    print(f"Fetching new items from the last {args.hours}h ...")
    new_items = get_new_items(args.hours, args.limit)
    users_items: dict[str, list] = defaultdict(list)
    for it in new_items:
        users_items[it["user"]].append(it)
    print(
        f"{len(new_items)} new items by {len(users_items)} accounts; "
        f"scoring up to {args.max_accounts} ..."
    )
    rows = analyse(users_items, args.max_accounts)
    if args.table:
        print_table(rows, args.min_score)
    else:
        print_report(rows)


if __name__ == "__main__":
    main()
