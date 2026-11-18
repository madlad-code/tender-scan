#!/usr/bin/env bash
# Morgonkörningen: hämta från TED, skriv snapshots/ och pusha den till GitHub.
#
# Körs av tender-scan-refresh.service. Bara snapshots/ committas, och bara när
# siffrorna faktiskt ändrats. Snapshoten innehåller enbart publik TED-data.
set -euo pipefail
cd "$(dirname "$0")/../.."

docker compose exec -T app tender-scan refresh --days 3
docker compose exec -T app tender-scan snapshot --out /data/snapshots

git pull --ff-only --quiet
mkdir -p snapshots
cp data/snapshots/ted-daglig.md data/snapshots/historik.csv snapshots/
git add snapshots
if git diff --cached --quiet; then
    echo "Inga ändringar i snapshots/, inget att pusha."
    exit 0
fi
git commit --quiet -m "data: TED-snapshot $(date -u +%F)"
git push --quiet origin HEAD:main
echo "Pushat: $(git log -1 --format='%h %s')"
