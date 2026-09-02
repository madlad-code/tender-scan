#!/usr/bin/env python3
"""Registrera batch 1:s Gmail-svar i `foia_requests`.

Svaren lästes i Gmail 2026-08-31 22:50, 2026-09-01 09:19 och 2026-09-02 09:12
UTC, av sessioner som körde i en molnbehållare — utan databasen, som bor på Oscars
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

Sex kommuner har ändå skickat handlingar — nio filer, drygt 100 MB. Hämta dem
med `scripts/hamta_bilagor.py` och registrera dem sedan med
`tender-scan foia ingest <id> <fil> --partial`. `--partial` för alla utom
Bjurholm, som är den enda som besvarat båda punkterna; för de övriga fattas en
halva och klockan måste gå vidare. Det görs för hand, när filerna ligger på
disk, och inte härifrån: skriptet vet inte var de hamnade.

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
    # --- svar 2026-09-01 eftermiddag och 2026-09-02 -------------------------
    (
        "bjurholm",
        "bjurholm",
        "svar 2026-09-01 09:36 UTC — Maria Egelby, ekonomichef, vidarebefordrade begäran "
        "med två filer bifogade: 'Avtalsstatistik_09011048.xls' och "
        "'Leverantörsreskontraöversikt.xlsx'. Det är den enda kommun i batch 1 som "
        "besvarat båda punkterna i ett svep. Inget följebrev, så vilken period "
        "reskontrafilen täcker går inte att se utan att öppna den — kontrollera det "
        "innan begäran räknas som helt besvarad.",
    ),
    (
        "borås",
        "borås-2",
        "svar 2026-09-01 14:36, 14:37 och 14:39 UTC — Helena Hurdén, ekonom på "
        "redovisningsenheten, besvarar punkt 2 och skickar leverantörsreskontran som "
        "öppna data, ett år per mejl för att inte spränga storleksgränsen: "
        "'Öppna data 2023.xlsx', 'Öppna data 2024.xlsx', 'Öppna data 2025.xlsx' "
        "(27–29 MB styck). Perioden 2026-01-01–2026-08-31 kan levereras först "
        "2026-09-09, då filen tas fram av en datumstyrd automatisk händelse. "
        "Punkt 1, avtalskatalogen, ligger kvar hos koncerninköp och är obesvarad.",
    ),
    (
        "jönköping",
        "jönköping-2",
        "svar 2026-09-01 10:18 UTC — Roger Svensson, sekretesshandläggare på "
        "stadskontoret, bifogar 'SH ContractExport 26091.pdf' med avtal för den "
        "efterfrågade tiden. Kommunen inför just nu en ny avtalsdatabas, så filen är "
        "vad ett automatiserat registerutdrag kan ge i dagsläget. Ekonomiavdelningen "
        "besvarar leverantörsreskontran separat. Halv leverans, och i PDF i stället "
        "för det maskinläsbara format som begärdes.",
    ),
    (
        "grästorp",
        "grästorp-2",
        "svar 2026-09-01 11:34 UTC — kansli- och serviceenheten bifogar "
        "'Avtalsdatabasen 20260616.xlsx' som en nulägesbild, och skriver att det inte "
        "finns några upprättade handlingar som motsvarar punkt 1. Avtalsdatabasen "
        "omfattar inte kommunens samtliga avtal: entreprenadupphandlingar, "
        "direktupphandlingar, vissa Adda- och Sinfra-avtal samt engångsinköp saknas. "
        "Punkt 2 är inte besvarad. Filen är alltså ett svar med en uttalad "
        "täckningsbegränsning, inte en fullständig avtalskatalog.",
    ),
    (
        "katrineholm",
        "katrineholm",
        "svar 2026-09-01 12:46 UTC — Ann-Kristin Löfstig Panzar, upphandlingskoordinator: "
        "begäran mottagen och sekretessprövning pågår. Katrineholm var tyst vid de två "
        "första genomgångarna av inkorgen.",
    ),
    (
        "katrineholm",
        "katrineholm-2",
        "svar 2026-09-02 08:46 UTC — Katrineholm tar ut avgift enligt avgiftsförordningen "
        "för elektroniska dokument och uppskattar 10–16 stora filer. Taxan skickades som "
        "en bild i mejlet, så beloppet går inte att läsa ur texten. Kommunen ber om "
        "fakturaadress innan de går vidare. Ingen faktura är begärd och inget är betalt.",
    ),
    (
        "gävle",
        "gävle-3",
        "svar 2026-09-01 09:28 UTC — Åsa Lindberg, ärende KC2026137233: uttagen är "
        "'ett gigantiskt jobb', delårsbokslutet har prio 1 och materialet måste "
        "sekretessgranskas. Återkommer efter delårsbokslutet. Ingen tidpunkt utlovad "
        "och ingen avgift nämnd.",
    ),
    (
        "haninge",
        "haninge-2",
        "svar 2026-09-02 08:47 UTC — Upphandling Södertörn, som upphandlar åt Haninge, "
        "från inkop@upphandlingsodertorn.se med Request ID RE-700008093 och ärende "
        "2026HAN19344: begäran bekräftad som omfattande, handläggningen tar tid, och "
        "utlämnandet är förenat med kostnad. Avgiftsinformationen bifogades som "
        "'Information till dig som önskar ta del av handlingar v 3.0.pdf'. "
        "Registraturen har delat begäran: upphandling tar avtalsdatabasen, "
        "leverantörsfaktura tar reskontran. Inget belopp ännu.",
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

# Searched in Gmail on 2026-08-31 22:50, 2026-09-01 09:19 and 2026-09-02 09:12
# UTC, and found to have sent nothing at all — not even an autoreply. Listed so
# the reader can see that the notes above are seventeen of twenty, and that the
# absence was checked rather than assumed. The list has shrunk from eight to
# five to three as kommuner answered between readings, which is the argument for
# re-reading the inbox before sending a reminder rather than after.
TYSTA = (
    "Eskilstuna kommun",
    "Aneby kommun",
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
        "\nSex kommuner har skickat handlingar. Hämta filerna först:\n"
        "  python3 scripts/hamta_bilagor.py --live\n"
        "Registrera dem sedan. Bjurholm har besvarat båda punkterna och kan stängas;\n"
        "övriga behöver --partial, annars slutar `foia due` jaga den halva som fattas:\n"
        "  tender-scan foia ingest <id> data/foia-svar/bjurholm__*.xlsx\n"
        "  tender-scan foia ingest <id> data/foia-svar/<fil> --partial   # övriga fem"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
