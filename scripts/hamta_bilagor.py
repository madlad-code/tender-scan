#!/usr/bin/env python3
"""Hämta batch 1:s bifogade handlingar ur Gmail till disk.

Kommunerna svarar med filer, och filerna är hela poängen: en avtalskatalog
eller en leverantörsreskontra är det som faktiskt går att räkna på. De ligger
i inkorgen och ska ner på disk, en gång, med namn som säger vilken kommun de
kom från.

## Varför IMAP och inte Gmail-API:t

Sessionerna som läst inkorgen kör i en molnbehållare och kan läsa mejlens
*text*, men har inget verktyg för att hämta en bilaga — och även med ett sådant
vore det fel väg: Borås tre filer väger 27–29 MB styck, och den vägen går
genom en språkmodells kontext. IMAP hämtar dem direkt till disk med samma
app-lösenord som `~/Desktop/OUTREACH/send_batch.py` redan använder för SMTP.
Inget nytt konto, ingen ny behörighet, ingen OAuth-dans.

## Vad som sparas och vad som inte gör det

Bara filer som kan bära data: xlsx, xls, csv, ods, pdf, zip. En kommuns
mejlsignatur innehåller nästan alltid en `image001.png`, och en katalog full
av logotyper gör materialet svårare att överblicka utan att tillföra något.
PDF:er sparas för att Jönköping skickade sin avtalslista som PDF, och
Haninge sin avgiftsinformation.

Filerna hamnar i `data/foia-svar/` som är gitignorerad — de innehåller
kommunernas leverantörsuppgifter och hör inte hemma i ett publikt repo.

## Körning

    export GMAIL_USER=oscarenghag@gmail.com
    export GMAIL_APP_PASSWORD='<app-lösenordet>'
    python3 scripts/hamta_bilagor.py            # visar vad som skulle hämtas
    python3 scripts/hamta_bilagor.py --live     # hämtar

Säker att köra om: en fil som redan finns med samma storlek hämtas inte igen.
"""

from __future__ import annotations

import argparse
import contextlib
import email
import imaplib
import os
import sys
from email.message import Message
from pathlib import Path

IMAP_HOST = "imap.gmail.com"

# The subject every batch-1 request and reply carries. Kommunerna prefixar med
# Sv:/SV:/Re:/VB: och några klistrar in ärendenummer mitt i, så sökningen görs
# på en delsträng snarare än på hela ämnesraden.
SUBJECT = "avtalskatalog och leverantörsreskontra"

# Extra ämnesrader från kommuner vars system skrev om ämnet helt.
EXTRA_SUBJECTS = ("Avtalskatalogen",)

# Filändelser som kan bära data. Allt annat är signaturgrafik.
KEEP = {".xlsx", ".xls", ".csv", ".ods", ".pdf", ".zip"}

# Avsändardomän -> kommun, så filnamnen säger var materialet kom ifrån.
# Södertörn upphandlar åt Haninge och svarar från sin egen domän.
DOMAN = {
    "boras.se": "boras",
    "bjurholm.se": "bjurholm",
    "grastorp.se": "grastorp",
    "huddinge.se": "huddinge",
    "jonkoping.se": "jonkoping",
    "stadshuset.goteborg.se": "goteborg",
    "goteborg.se": "goteborg",
    "upphandlingsodertorn.se": "haninge-sodertorn",
    "haninge.se": "haninge",
    "hassleholm.se": "hassleholm",
    "harnosand.se": "harnosand",
    "katrineholm.se": "katrineholm",
    "falun.se": "falun",
    "gavle.se": "gavle",
    "karlstad.se": "karlstad",
    "enkoping.se": "enkoping",
    "helsingborg.se": "helsingborg",
    "kalmar.se": "kalmar",
    "halmstad.se": "halmstad",
}


def kommun_av(avsandare: str) -> str:
    """Kommunens kortnamn ur avsändaradressen, annars domänen som den är."""
    _, adress = email.utils.parseaddr(avsandare)
    doman = adress.rpartition("@")[2].lower()
    for kand, namn in DOMAN.items():
        if doman == kand or doman.endswith("." + kand):
            return namn
    return doman.replace(".", "-") or "okand"


def sanera(namn: str) -> str:
    """Ett filnamn som överlever alla filsystem, med tecknen kvar där det går."""
    trygg = [c if (c.isalnum() or c in " .-_åäöÅÄÖ") else "_" for c in namn]
    return "".join(trygg).strip().replace(" ", "_") or "bilaga"


def bilagor(meddelande: Message):
    """(filnamn, innehåll) för varje bilaga som kan bära data."""
    for del_ in meddelande.walk():
        if del_.get_content_maintype() == "multipart":
            continue
        namn = del_.get_filename()
        if not namn:
            continue
        # Ett obegripligt kodat namn är fortfarande ett namn, så avkodningen
        # får misslyckas utan att bilagan tappas.
        with contextlib.suppress(UnicodeDecodeError, LookupError, ValueError):
            namn = str(email.header.make_header(email.header.decode_header(namn)))
        if Path(namn).suffix.lower() not in KEEP:
            continue
        innehall = del_.get_payload(decode=True)
        if innehall:
            yield namn, innehall


def sok(klient: imaplib.IMAP4_SSL, fras: str) -> list[bytes]:
    """Meddelande-id för varje mejl vars ämne innehåller frasen."""
    # IMAP SEARCH med icke-ASCII kräver att laddningen skickas som literal;
    # UTF-8-charset gör att "leverantörsreskontra" matchar med sina prickar.
    _, svar = klient.search("UTF-8", "SUBJECT", f'"{fras}"'.encode())
    return svar[0].split() if svar and svar[0] else []


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Spara filerna")
    parser.add_argument("--ut", default="data/foia-svar", help="Katalog att spara i")
    args = parser.parse_args()

    anvandare = os.environ.get("GMAIL_USER")
    losen = os.environ.get("GMAIL_APP_PASSWORD")
    if not anvandare or not losen:
        sys.exit(
            "Sätt GMAIL_USER och GMAIL_APP_PASSWORD först.\n"
            "App-lösenordet är samma som send_batch.py använder för SMTP; "
            "ett nytt skapas på https://myaccount.google.com/apppasswords"
        )

    ut = Path(args.ut)
    if args.live:
        ut.mkdir(parents=True, exist_ok=True)

    klient = imaplib.IMAP4_SSL(IMAP_HOST)
    try:
        klient.login(anvandare, losen)
        # "[Gmail]/All Mail" på ett engelskt konto; svenska konton kallar den
        # "[Gmail]/Alla mejl". Inkorgen räcker för svar och är alltid samma
        # namn, så den är förstahandsvalet.
        klient.select("INBOX", readonly=True)

        sedda: set[bytes] = set()
        traffar: list[bytes] = []
        for fras in (SUBJECT, *EXTRA_SUBJECTS):
            for mid in sok(klient, fras):
                if mid not in sedda:
                    sedda.add(mid)
                    traffar.append(mid)

        if not traffar:
            print("Inga mejl matchade. Är rätt konto inloggat?")
            return 1

        hamtade = hoppade = 0
        for mid in traffar:
            _, data = klient.fetch(mid, "(RFC822)")
            if not data or not isinstance(data[0], tuple):
                continue
            meddelande = email.message_from_bytes(data[0][1])
            kommun = kommun_av(meddelande.get("From", ""))

            for namn, innehall in bilagor(meddelande):
                mal = ut / f"{kommun}__{sanera(namn)}"
                if mal.exists() and mal.stat().st_size == len(innehall):
                    print(f"=  {mal.name} ({len(innehall) / 1e6:.1f} MB) finns redan")
                    hoppade += 1
                    continue
                print(f"+  {mal.name} ({len(innehall) / 1e6:.1f} MB)")
                if args.live:
                    mal.write_bytes(innehall)
                hamtade += 1

        print()
        if args.live:
            print(f"{hamtade} hämtade, {hoppade} fanns redan, i {ut}/")
            print("Registrera dem sedan med `tender-scan foia ingest <id> <fil> --partial`.")
        else:
            print(f"{hamtade} skulle hämtas, {hoppade} finns redan. Kör om med --live.")
        return 0
    finally:
        with contextlib.suppress(OSError):
            klient.logout()


if __name__ == "__main__":
    raise SystemExit(main())
