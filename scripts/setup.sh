#!/usr/bin/env bash
# Make a fresh checkout usable, and say plainly what is missing from it.
#
# Written for a cloud container or a machine that has never run this project:
# `git clone` gives you the code and none of the data, because the database and
# the outreach sheet are gitignored on purpose. A session that does not know
# that spends its first minutes rediscovering it.
set -euo pipefail

cd "$(dirname "$0")/.."

# Find an interpreter that satisfies requires-python. `python3` is not it by
# default: on this project's own machine `python3` is a PyPy 3.11 earlier on
# PATH than CPython, and `pip install -e .` fails with
#   ERROR: Package 'tender-scan' requires a different Python: 3.11 not in '>=3.12'
# after the venv has already been created, which reads like a broken repo
# rather than a shadowed interpreter. So the version is checked up front.
usable() {
    command -v "$1" >/dev/null 2>&1 &&
        "$1" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)' 2>/dev/null
}

BASE=""
for candidate in python3.14 python3.13 python3.12 python3 python; do
    if usable "$candidate"; then BASE="$candidate"; break; fi
done
if [ -z "$BASE" ]; then
    echo "Hittar ingen Python 3.12+. Installera en och kör om." >&2
    echo "Sedd som python3: $(python3 -V 2>&1 || echo 'ingen')" >&2
    exit 1
fi
echo "Använder $BASE ($("$BASE" -V 2>&1))"

# Prefer an existing virtualenv; make one only when there is none, and fall
# back to a plain --user install where venv is unavailable (some containers).
if [ -n "${VIRTUAL_ENV:-}" ]; then
    PY="$BASE"
elif [ -x .venv/bin/python ] && .venv/bin/python -c 'import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)'; then
    PY=".venv/bin/python"
elif "$BASE" -m venv .venv 2>/dev/null; then
    PY=".venv/bin/python"
else
    PY="$BASE"
    PIP_FLAGS="--user"
fi

echo "Installerar tender-scan (${PY})..."
"$PY" -m pip install -q -e ".[dev]" ${PIP_FLAGS:-}
echo "Klart. CLI: $("$PY" -c 'import shutil;print(shutil.which("tender-scan") or "kör via python -m tender_scan.cli")')"

echo
echo "Vad som INTE följde med klonen (gitignorerat, med flit):"

if [ -f data/tender_scan.db ]; then
    echo "  data/tender_scan.db      FINNS"
else
    cat <<'MISSING'
  data/tender_scan.db      SAKNAS — här bor facit för foia_requests,
                           framework_agreements och supplier_payments.
                           Den ligger på användarens egen maskin.
MISSING
fi

if [ -d ~/Desktop/OUTREACH ]; then
    echo "  ~/Desktop/OUTREACH       FINNS"
else
    echo "  ~/Desktop/OUTREACH       SAKNAS — utskickslistan och mallarna, lokalt."
fi

cat <<'NOTE'

Om du kör i en molncontainer är det här väntat, inte ett fel.
Du kan läsa och skriva kod och köra hela testsviten. Du kan INTE läsa eller
ändra det verkliga ärendeläget — det finns bara lokalt.

Behöver du ändra ärenden härifrån: skriv ett skript som kör `tender-scan foia
...`-kommandon, committa och pusha det, och låt den lokala sessionen köra det.
Uppfinn aldrig ett svar du inte har läst i ett faktiskt mejl.

Nästa steg:  python3 scripts/state.py --check   (läget, utan att skriva något)
             pytest                             (ska vara grönt överallt)
NOTE
