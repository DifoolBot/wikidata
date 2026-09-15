"""Build a redirect-scan selection cache from a plain QID list.

The selection caches (output/selection_cache/redirect_<subset>.json) are
gitignored -- machine-local and re-derivable -- so they do NOT travel between
the Toolforge and local checkouts via git. The matching input/only_<subset>_*.txt
lists (the same QID set) DO travel via git. This turns such a list back into the
cache deconflate.py reads, so a second machine gets the primed selection without
re-running the dump extraction or copying the big JSON:

    # after `git pull` brings input/only_multi_20260914.txt
    python projects/viaf_deconflate/cache_from_list.py \
        projects/viaf_deconflate/input/only_multi_20260914.txt multi

Then `deconflate.py --redirect-scan multi` reuses it with no query.
"""

import argparse
import json
import re
from datetime import datetime
from pathlib import Path

CACHE_DIR = Path(__file__).resolve().parent / "output" / "selection_cache"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("list", type=Path, help="a text file of one QID per line")
    ap.add_argument("subset", choices=["multi", "long"],
                    help="which redirect-scan cache to write (redirect_<subset>.json)")
    args = ap.parse_args()

    # Tolerate one-per-line (the dump extractor), comma-separated (the GUI-CSV
    # stopgap), and CRLF -- split on any run of whitespace or commas.
    tokens = re.split(r"[\s,]+", args.list.read_text(encoding="utf-8"))
    qids = list(dict.fromkeys(
        t for t in tokens if t.startswith("Q") and t[1:].isdigit()))
    if not qids:
        raise SystemExit(f"no QIDs found in {args.list}")

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "fetched": datetime.now().astimezone().isoformat(timespec="seconds"),
        "source": f"list:{args.list.name}",
        "count": len(qids),
        "bindings": [
            {"item": {"type": "uri",
                      "value": f"http://www.wikidata.org/entity/{q}"}}
            for q in qids
        ],
    }
    out = CACHE_DIR / f"redirect_{args.subset}.json"
    out.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    print(f"{len(qids)} QID(s) -> {out}")
    print(f"deconflate.py --redirect-scan {args.subset} will reuse this with no query.")


if __name__ == "__main__":
    main()
