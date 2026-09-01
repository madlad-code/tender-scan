#!/usr/bin/env python3
"""Registrera batch 1:s Gmail-svar i `foia_requests`.

Svaren lästes i Gmail 2026-08-31 22:50 UTC och igen 2026-09-01 09:19 UTC, av
sessioner som körde i en molnbehållare — utan databasen, som bor på Oscars
maskin. Fynden kan därför inte skrivas där de hör hemma i samma andetag som de
görs. Den här filen är bryggan: den bär avläsningen i versionshanterad form
tills någon kör den på maskinen som har databasen.

## Bara det som stod i ett mejl

Varje anteckning nedan är hämtad ur ett faktiskt mejl, med avsändare, klockslag
(UTC) och diarienummer där sådant angavs. Där en kommun inte angav diarienummer
står det uttryckligen — hellre det än ett påhittat nummer. De åtta kommuner som
inte svarat alls får ingen anteckning: tystnad är inte en händelse att
registrera, den syns redan i `foia due`.

## Ingen status ändras här

Inget av svaren är ett avslag, och inget är en fullständig leverans. Skriptet
skriver därför bara `notes`, via `tender-scan foia note`, och rör aldrig något
statusfält.

Två kommuner har ändå skickat handlingar: Huddinge avtalskatalogen, Göteborg
sin avtalssammanställning. Båda gäller punkt 1 av två, och båda filerna ska in
med `tender-scan foia ingest <id> <fil> --partial` — `--partial` för att den
andra halvan fortfarande fattas och klockan måste gå vidare. Det görs för hand,
när filerna ligger sparade på disk, och inte härifrån: skriptet vet inte var de
hamnade.

## Körning

    python3 scripts/registrera_batch1_svar.py            # visar vad som skulle skrivas
    python3 scripts/registrera_batch1_svar.py --live     # skriver

Skriptet är säkert att köra om: varje anteckning bär en markör med kommunens
nyckel, [batch1-gmail:huddinge] och så vidare, och en begäran som redan har sin
markör hoppas över i stället för att få texten en gång till.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

# The marker that makes a re-run a no-op. `foia note` appends, so without it a
# second run would write every note a second time. It carries a per-note id
# rather than being one shared string, so the check tests "has *this* note been
# written" instead of the much weaker "has this script ever run here" — and so
# a kommun that turns up twice, as Gävle did with a second ärendenummer, can be
# annotated twice without the first note blocking the second.
MARKER = "[batch1-gmail:{markor}]"

# (nyckel, markör, text). The key is the distinctive first word of the
# authority's name, because the sheet these rows were imported from spells the
# rest inconsistently ("Borås stad" / "Borås Stad", "Falu kommun" / "Falun").
# Matching on the whole name would miss; matching on a prefix this specific
# cannot collide inside batch 1. The marker is normally the key, and differs
# only where one kommun needs a second, separately-skippable note.
NOTERINGAR: list[tuple[str, str, str]] = [
    (
        "huddinge",
        "huddinge",
        "svar 2026-08-31 12:19 UTC — avtalskatalogen levererad som bilagan Avtalskatalogen.xlsx av "
        "Katarina Svärdgren, inköpssamordnare på upphandlingssektionen. "
        "Leverantörsreskontran återstår — ekonomienheten svarar separat på den. "
        "Ärendenummer 2026SC66301. Status står kvar som partial: halva begäran är "
        "obesvarad, och klockan ska fortsätta gå.",
    ),
    (
        "hässleholm",
        "hässleholm",
        "svar 2026-08-31 12:07 UTC — Ahmet Baran, ekonom på kommunledningsförvaltningen: "
        "uppgifterna lämnas ut digitalt, uppdelade på cirka 19 filer, mot en avgift om "
        "161 kr enligt kommunens taxa för kopior. Oscar svarade 22:16 UTC att han "
        "accepterar kostnaden och bad om betalningsinstruktion. Ingen betalning är gjord. "
        "Inget diarienummer angivet.",
    ),
    (
        "haninge",
        "haninge",
        "svar 2026-08-31 — mottagningsbekräftelse, ärende 2026HAN19344 (autosvar 09:18 UTC, "
        "registrator 10:31 UTC). Registratorn upplyser att avgift kan tas ut enligt "
        "kopieringstaxan, och att handlingarna alternativt kan läsas kostnadsfritt på "
        "plats. Inga handlingar ännu.",
    ),
    (
        "falu",
        "falu",
        "svar 2026-08-31 — mottagningsbekräftelse, ärende FK-2608-11504 (kontaktcenter "
        "09:23 UTC). Fakturaenheten på ekonomikontoret (11:40 UTC): återkommer med "
        "handlingarna snarast, men en sekretessbedömning ska göras vid utlämnande av "
        "leverantörsfakturor, vilket kan påverka handläggningstiden, och kostnad kan "
        "tillkomma beroende på mängden information. Inga handlingar ännu.",
    ),
    (
        "enköping",
        "enköping",
        "svar 2026-08-31 — mottagningsbekräftelse, ärende KC202639332 (09:20 UTC). "
        "Kontaktcenter återkopplade 13:51 UTC att begäran skickats vidare till "
        "kommunledningsförvaltningen. Inga handlingar ännu.",
    ),
    (
        "helsingborg",
        "helsingborg",
        "svar 2026-08-31 — mottagningsbekräftelse, ärende KC-#254868 (09:16 UTC). "
        "Kontaktcenter 10:14 UTC: ärendet vidarebefordrat till berörd förvaltning, "
        "som återkommer. Inga handlingar ännu.",
    ),
    (
        "gävle",
        "gävle",
        "svar 2026-08-31 — mottagningsbekräftelse, ärende KC2026136671, registrerat "
        "2026-08-31 (09:18 UTC). Inga handlingar ännu.",
    ),
    (
        "borås",
        "borås",
        "svar 2026-08-31 — mottagningsbekräftelse från Anna Möller, registrator (12:13 UTC): "
        "begäran vidarebefordrad till koncerninköp och leverantörsreskontra för "
        "besvarande. Inget diarienummer angivet. Inga handlingar ännu.",
    ),
    (
        "kalmar",
        "kalmar",
        "svar 2026-08-31 — mottagningsbekräftelse från kommunvägledare (09:24 UTC): ärendet "
        "vidarebefordrat för handläggning. Inget diarienummer angivet. Inga handlingar ännu.",
    ),
    (
        "jönköping",
        "jönköping",
        "svar 2026-08-31 — automatisk mottagningsbekräftelse (09:16 UTC). Inget diarienummer "
        "angivet. Inga handlingar ännu.",
    ),
    (
        "halmstad",
        "halmstad",
        "svar 2026-08-31 — automatiskt svar från kommunstyrelsens diarium (09:16 UTC). "
        "Inget diarienummer angivet. Inga handlingar ännu.",
    ),
    # --- svar som kom under natten till 2026-09-01 --------------------------
    (
        "göteborg",
        "göteborg",
        "svar 2026-09-01 07:49 UTC — diariet på stadsledningskontoret bifogade "
        "sammanställningen till punkt 1 som filen 'Avtal 20230101-20260901.xlsx', "
        "framtagen av stadens förvaltning för inköp och upphandling. Punkt 2 besvarades "
        "med en hänvisning i stället för en handling: hela stadens leverantörsreskontra "
        "ligger årsvis på stadens sida för öppna data, "
        "https://goteborg.se/wps/portal?uri=gbglnk%3a2015816171319546#esc_term="
        "leverantörsfakturor . Diariet erbjöd sig att lämna sammanställningen på annat "
        "sätt om det behövs. Halv leverans: filen ska in med `foia ingest --partial`.",
    ),
    (
        "härnösand",
        "härnösand",
        "svar 2026-09-01 08:35 UTC — Ann-Catrine Forsberg, inköps- och avtalscontroller "
        "på upphandlingsenheten: begäran mottagen och ska hanteras skyndsamt, men "
        "utlämnandet kommer att kosta och exakt summa meddelas senare. Centraldiariet "
        "vidarebefordrade ärendet internt 2026-08-31 12:54. Inget belopp och inget "
        "diarienummer ännu, inga handlingar ännu.",
    ),
    (
        "karlstad",
        "karlstad",
        "svar 2026-09-01 06:49 UTC — automatisk bekräftelse, ärende K202699134, "
        "registrerat 2026-09-01 08:47:35 lokal tid. Mejlet går inte att svara på. "
        "Inga handlingar ännu.",
    ),
    (
        "gävle",
        "gävle-2",
        "andra bekräftelsen 2026-09-01 06:32 UTC — ärende KC2026137233, registrerat "
        "2026-08-31 11:17:26 lokal tid, status 'Mottaget ärende'. Gävle har därmed gett "
        "två ärendenummer för samma begäran (det första var KC2026136671). Båda gäller "
        "utskicket 2026-08-31; ingen förklaring till dubbleringen har lämnats.",
    ),
    (
        "grästorp",
        "grästorp",
        "svar 2026-08-31 — autosvar (09:18 UTC), mejlet mottaget, kan komma att "
        "vidarebefordras till berörd handläggare. Inget diarienummer angivet. "
        "Inga handlingar ännu.",
    ),
]

# Searched in Gmail on 2026-08-31 22:50 UTC and again on 2026-09-01 09:19 UTC,
# and found to have sent nothing at all — not even an autoreply. Listed so the
# reader can see that the notes above are fifteen of twenty, and that the
# absence was checked rather than assumed. Göteborg, Härnösand and Karlstad
# were on this list yesterday and answered overnight, which is the argument for
# re-reading the inbox before sending a reminder rather than after.
TYSTA = (
    "Eskilstuna kommun",
    "Katrineholms kommun",
    "Aneby kommun",
    "Bjurholms kommun",
    "Dorotea kommun",
)


def hitta_databasen(angiven: str | None) -> Path:
    path = Path(angiven or os.environ.get("TENDER_SCAN_DB") or "data/tender_scan.db")
    if not path.exists():
        sys.exit(
            f"Ingen databas på {path}. Ange den med --db eller sätt TENDER_SCAN_DB.\n"
            "Skriptet måste köras på maskinen som har foia_requests."
        )
    return path


def las_begaranden(db: Path) -> list[tuple[int, str, str, str | None]]:
    """id, org, status och notes för varje loggad begäran — skrivskyddat."""
    with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as conn:
        conn.row_factory = sqlite3.Row
        return [
            (row["id"], row["target_org"], row["status"], row["notes"])
            for row in conn.execute("SELECT id, target_org, status, notes FROM foia_requests")
        ]


def matcha(
    nyckel: str, rader: list[tuple[int, str, str, str | None]]
) -> tuple[int, str, str, str | None] | None:
    """Den enda raden vars namn börjar på nyckeln, annars ingen.

    Två träffar är inte ett val att göra automatiskt: en anteckning på fel
    kommun är svårare att upptäcka än en som aldrig skrevs. Tvetydighet
    rapporteras och hoppas över.
    """
    traffar = [rad for rad in rader if rad[1].strip().casefold().startswith(nyckel)]
    if len(traffar) != 1:
        return None
    return traffar[0]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Skriv till databasen")
    parser.add_argument("--db", help="Sökväg till databasen (annars $TENDER_SCAN_DB)")
    args = parser.parse_args()

    db = hitta_databasen(args.db)
    rader = las_begaranden(db)
    if not rader:
        sys.exit(f"{db} innehåller inga begäranden. Kör `tender-scan foia import` först.")

    skrivna = hoppade = saknade = 0
    for nyckel, markor_id, text in NOTERINGAR:
        rad = matcha(nyckel, rader)
        if rad is None:
            print(f"?  {nyckel}: ingen entydig rad i foia_requests — hoppar över")
            saknade += 1
            continue

        request_id, org, status, notes = rad
        markor = MARKER.format(markor=markor_id)
        if notes and markor in notes:
            print(f"=  #{request_id} {org}: redan antecknad")
            hoppade += 1
            continue

        print(f"+  #{request_id} {org} ({status})")
        if not args.live:
            print(f"   {text} {markor}")
            continue

        resultat = subprocess.run(
            ["tender-scan", "foia", "note", str(request_id), f"{text} {markor}", "--db", str(db)],
            capture_output=True,
            text=True,
        )
        if resultat.returncode != 0:
            print(f"   MISSLYCKADES: {resultat.stderr.strip()}", file=sys.stderr)
            saknade += 1
            continue
        skrivna += 1

    print(f"\nUtan svar i inkorgen, inget att registrera: {', '.join(TYSTA)}.")
    if args.live:
        print(f"{skrivna} antecknade, {hoppade} redan gjorda, {saknade} misslyckades.")
        print("Ingen status ändrad. Kör `tender-scan foia due` för att se vad som förfallit.")
    else:
        print(f"{len(NOTERINGAR) - hoppade - saknade} skulle antecknas. Kör om med --live.")
    print(
        "\nTvå kommuner har skickat handlingar. Spara filerna och registrera dem med\n"
        "--partial, så att den halva som fattas fortsätter jagas:\n"
        "  tender-scan foia ingest <id> Avtalskatalogen.xlsx --partial           # Huddinge\n"
        "  tender-scan foia ingest <id> 'Avtal 20230101-20260901.xlsx' --partial # Göteborg\n"
        "Utan --partial sätts status till received och `foia due` slutar lista dem."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
