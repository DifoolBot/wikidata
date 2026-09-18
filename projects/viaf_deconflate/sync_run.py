"""One-command deconflate runner: git-sync + run + dated commit/push.

Removes the per-run bookkeeping (shard, PYTHONPATH, dated commit message, the
pull-before / commit-pull-push dance). The machine's shard is read ONCE from a
gitignored ``machine.conf`` next to this script, so you never retype it.

One-time setup on each machine (pick the half this machine owns):

    echo 1/2 > projects/viaf_deconflate/machine.conf     # local box
    echo 0/2 > projects/viaf_deconflate/machine.conf      # Toolforge

Daily use:

    python projects/viaf_deconflate/sync_run.py --save            # local, real run
    python projects/viaf_deconflate/sync_run.py --save --job      # Toolforge (submit a job)

Without --save it does a cheap capped preview (--max-items 10, no push). Extra
args after the known flags pass straight through to deconflate.py, e.g.
``--min-day-remaining 0`` or ``--subset long``. ``--dry-run`` prints every command
without running anything. ``--no-git`` skips all git steps.
"""

import argparse
import os
import socket
import subprocess
import sys
from datetime import date
from pathlib import Path

PROJECT = Path(__file__).resolve().parent
REPO_ROOT = PROJECT.parents[1]
CONF = PROJECT / "machine.conf"


def read_shard() -> str | None:
    """Shard 'I/M' from --shard is handled by the caller; here from env or conf."""
    env = os.environ.get("DECONFLATE_SHARD")
    if env:
        return env.strip()
    if CONF.exists():
        for line in CONF.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            return line.split("=", 1)[1].strip() if line.startswith("shard=") else line
    return None


def run(cmd: list[str], *, env: dict | None = None, dry: bool, check: bool = True,
        allow_fail: bool = False) -> int:
    """Run a command from the repo root, or just print it under --dry-run."""
    printable = " ".join(cmd)
    if dry:
        print(f"  [dry-run] {printable}")
        return 0
    print(f"  $ {printable}")
    rc = subprocess.run(cmd, cwd=REPO_ROOT, env=env).returncode
    if rc and check and not allow_fail:
        sys.exit(f"command failed (exit {rc}): {printable}")
    return rc


def git(*args: str, dry: bool, **kw) -> int:
    return run(["git", *args], dry=dry, **kw)


def has_staged_changes() -> bool:
    return subprocess.run(["git", "diff", "--cached", "--quiet"],
                          cwd=REPO_ROOT).returncode != 0


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--save", action="store_true",
                    help="apply and SAVE edits (default: cheap capped preview)")
    ap.add_argument("--subset", choices=["multi", "long"], default="multi",
                    help="redirect-scan subset (default multi)")
    ap.add_argument("--shard", default=None,
                    help="override the machine.conf shard, e.g. 0/2")
    ap.add_argument("--job", action="store_true",
                    help="Toolforge: submit deconflate as a `toolforge jobs run` "
                         "job (heavy part) instead of running it here; git stays local")
    ap.add_argument("--no-git", action="store_true", help="skip all git steps")
    ap.add_argument("--dry-run", action="store_true",
                    help="print every command without executing")
    args, passthrough = ap.parse_known_args()

    shard = args.shard or read_shard()
    if not shard:
        sys.exit(
            "no shard configured. Create it once, e.g.:\n"
            f"    echo 1/2 > {CONF}\n"
            "(use 0/2 on one machine and 1/2 on the other), or pass --shard I/M.")

    today = date.isoformat(date.today())
    host = socket.gethostname()
    dry = args.dry_run

    # deconflate flags: real save, or a cheap capped preview.
    edit_flags = ["--apply", "--save"] if args.save else ["--apply", "--max-items", "10"]
    scan = ["--redirect-scan", args.subset, "--shard", shard, *edit_flags, *passthrough]

    print(f"deconflate {args.subset} shard {shard} on {host} "
          f"({'SAVE' if args.save else 'preview'})")

    # 1. sync in: commit any pending state so the merge is clean, then pull.
    if not args.no_git:
        git("add", "projects/viaf_deconflate/output", dry=dry, allow_fail=True)
        if dry or has_staged_changes():
            git("commit", "-m", f"deconflate state pre-sync {today}",
                dry=dry, allow_fail=True)
        git("pull", "--no-rebase", "--no-edit", dry=dry)

    # 2. run it -- directly here, or as a Toolforge job.
    if args.job:
        jobname = f"deconflate-{args.subset}"
        inner = ("bash $HOME/wikidata/projects/viaf_deconflate/toolforge_run.sh "
                 + " ".join(scan))
        run(["toolforge", "jobs", "delete", jobname], dry=dry, allow_fail=True, check=False)
        run(["toolforge", "jobs", "run", jobname, "--image", "python3.11",
             "--wait", "--command", inner], dry=dry)
    else:
        env = dict(os.environ)
        env["PYTHONPATH"] = os.pathsep.join(
            [str(REPO_ROOT / "projects"), env.get("PYTHONPATH", "")]).rstrip(os.pathsep)
        run([sys.executable, "projects/viaf_deconflate/deconflate.py", *scan],
            env=env, dry=dry)

    # 3. push state -- only when a real save could have changed it.
    if not args.no_git and args.save:
        git("add", "projects/viaf_deconflate/output", dry=dry, allow_fail=True)
        if dry or has_staged_changes():
            git("commit", "-m",
                f"deconflate {args.subset} run {today} (shard {shard})", dry=dry)
        git("pull", "--no-rebase", "--no-edit", dry=dry)
        git("push", dry=dry)

    print("done." if not dry else "dry-run complete (nothing executed).")


if __name__ == "__main__":
    main()
