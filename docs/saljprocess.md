# Säljprocess & kundfunnel

Målet: köpet ska kännas löjligt smidigt. Kunden ska aldrig behöva skapa konto,
förstå teknik eller vänta på svar. Tre mejl = en affär.

> **OBS:** Detta dokument är generiskt säljmaterial och ligger i publika repot.
> Verkliga leads, samtalsanteckningar, offerter och kunddata får ALDRIG committas här —
> de ligger lokalt eller i privat repo (`tender-scan-ops`).

## Idealkund (ICP)

- Svensk leverantör, 5–50 anställda
- Säljer elektronik/teknisk materiel (batterier, strömförsörjning, komponenter, instrument)
- Har lagt anbud i offentlig upphandling senaste 24 månaderna — helst förlorat minst ett
- Ägaren/säljchefen svarar själv i telefon

## Leadkälla

Tilldelningsbeslut i vertikalen. Förlorande anbudsgivare namnges — de har bevisat
att de (a) vill sälja till offentlig sektor och (b) saknar underlag som vinner.
Scannern listar dem; varje beslut = 2–5 varma leads.

## Funnel — steg för steg

### 1. Första kontakt (kall men träffsäker)

**Telefon (primärt).** Manus:

> "Hej, [namn]? Oscar heter jag. Jag såg att ni lade anbud på [upphandling] hos
> [myndighet]. Snabb fråga bara — vet ni hur mycket [myndighet] faktiskt avropade
> på det förra avtalet, jämfört med takvolymen de annonserade?"

Svaret är nästan alltid nej. Fortsättning:

> "Det är offentlig data, men ingen tittar på den. Jag tar fram det som en rapport —
> historiska avrop, vilka som vunnit, prisbilder. Fyra sidor, fast pris, 48 timmar.
> Vill du att jag mejlar ett exempel?"

**Mejl (uppföljning eller när telefon inte går fram):** kort, 5 rader, länk till
landningssidan, EN fråga ("Vill du se vad [myndighet] faktiskt avropar?").

### 2. Offert — inom 24 h

Mejl med fast pris. Mall:

> Hej [namn],
>
> Som utlovat — rapport om [myndighet] / [avtalsområde]:
>
> - Historiska avropsvolymer [period]
> - Tidigare vinnare och prisbilder från tilldelningsbeslut
> - Takvolym vs verkligt utfall + enkel prognos
> - Ska-kravslista från senaste upphandlingen
>
> Fast pris: [X] kr ex moms. Leverans som PDF inom 48 h från ditt ja.
> Faktura efteråt, 30 dagar. Inte nöjd = riv fakturan.
>
> Räcker att du svarar "ja" på det här mejlet.

Nyckeln: **"svara ja" är hela köpet.** Ingen orderbekräftelse, inget avtal i v1.

### 3. Leverans — inom 48 h

- Rapport enligt mall (`docs/rapportmall.md` när den finns), PDF via mejl
- Alltid med: källhänvisning (Upphandlingsmyndigheten + TED + datum/period — krav för öppna data)
- Alltid med: EN konkret rekommendation ("nästa avrop väntas Q2 — kontakta X innan dess")

### 4. Fakturering

Egenanställning (Cool Company/Frilans Finans, ~6 % avgift) tills volymen motiverar
eget bolag. Faktura skickas EFTER leverans. Nöjd-garanti = riven faktura; kostar
inget mot vad förtroendet är värt i fas 1.

### 5. Uppföljning → abonnemang (dag 61+)

- 7 dagar efter leverans: "Var rapporten till nytta? Något som saknades?"
- Svaren = produktutveckling gratis
- Efter 2:a köpet från samma kund: erbjud bevakning 500–2 000 kr/mån
  ("samma analys, automatiskt, varje månad + larm när nya annonser matchar")

## Veckorytm

| Dag | Aktivitet |
|---|---|
| Mån | Kör scanner, bygg veckans leadlista ur tilldelningsbeslut |
| Tis–tors | 15–20 samtal. Anteckna pain points ordagrant |
| Fre | Leverera rapporter, automatisera det som nämnts av 2+ kunder, committa |

## Mätpunkter (skriv upp varje vecka)

- Samtal ringda / beslutsfattare nådda / ja till exempel-mejl
- Offerter skickade / accepterade
- Levererade rapporter / rivna fakturor
- Tid per rapport (mål: under 3 h → sedan under 1 h med automation)
