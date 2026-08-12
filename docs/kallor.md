# Datakällor för svensk offentlig upphandling

Ärlig karta över var upphandlingsdata finns, vad som är gratis, och vad tender-scan
kan (och inte kan) integrera. Uppdaterad 2026-08-12.

## Hur landskapet hänger ihop

Svenska upphandlingar annonseras på två nivåer:

1. **Över EU:s tröskelvärden** (ca 1,5 MSEK för varor/tjänster åt statliga myndigheter,
   högre för regioner/kommuner och byggentreprenader): annonseras **obligatoriskt i TED**,
   EU:s officiella databas. Här ligger de stora ramavtalen.
2. **Under tröskelvärdena**: annonseras i en **registrerad annonsdatabas**
   (Mercell/Opic, e-Avrop, Kommers m.fl. — [Konkurrensverkets register](https://www.konkurrensverket.se/upphandling/registrerade-annonsdatabaser/)).
   Dessa är kommersiella plattformar.
3. **All statistik i efterhand** (både över och under tröskel) samlas i
   **Upphandlingsmyndighetens nationella statistikdatabas** — öppna data.

## Källa för källa

| Källa | Vad | API | Kostnad | Status i tender-scan |
|---|---|---|---|---|
| [TED](https://ted.europa.eu/) | Annonser över EU-tröskel, hela EU | ✅ Öppet REST-API, ingen nyckel | Gratis | **Integrerad** (`ted_client.py`) |
| [Upphandlingsmyndighetens statistikdatabas](https://www.upphandlingsmyndigheten.se/statistik/statistikdatabasen/) | Historik/statistik för ~17 000 svenska upphandlingar/år | ⚠️ Export CSV/Excel via webbgränssnitt; inget dokumenterat publikt API | Gratis (öppna data, ange källa) | **Manuell CSV-export** — grund för rapportmotorn |
| [dataportal.se](https://www.dataportal.se/) (DIGG) | Samma statistikdatasets, samlade | ⚠️ Nedladdningslänkar, CSV/Excel | Gratis | Samma som ovan |
| [Mercell / Opic](https://get.mercell.com/sv-se/upphandlingsbevakning) | Bevakning av ALLA svenska annonser (aggregerar TendSign, e-Avrop, Kommers …) | 🔒 API-plattform finns men kräver betalt avtal | Betald | Ej integrerad — medveten avgränsning |
| [e-Avrop](https://info.e-avrop.com/) | Annonsdatabas + anbudsverktyg | ❌ Inget publikt API; gratis konto för sök/anbud | Gratis konto | Ej integrerad |
| Kommers Annons, TendSign m.fl. | Annonsdatabaser | ❌ Inget publikt API | — | Ej integrerad |
| Offentlighetsprincipen | Avropsstatistik, fakturaunderlag, avtalsuppföljning per myndighet | ✉️ Begäran per mejl till registrator | Gratis (ev. kopieringsavgift) | Manuell process — kärnan i rapportprodukten |

## Vad detta betyder för produkten

- **Live-bevakning över tröskel**: löst, gratis, automatiserad (TED-API:t).
  De stora ramavtalen — där takvolym vs avrop-analysen är värd mest — annonseras här.
- **Live-bevakning under tröskel**: kräver antingen betalt Mercell-API eller manuell
  bevakning via gratis e-Avrop-konto. Medvetet bortvalt i v1 — börja där datan är fri.
- **Rapportmotorn (takvolym vs utfall)**: behöver *historik*, inte live-data.
  Statistikdatabasens CSV-exporter + TED:s arkiv + offentlighetsprincipen räcker.
  Ingen betald källa behövs för att leverera betalda rapporter.
- **Attribution**: Upphandlingsmyndighetens öppna data får användas fritt men källa,
  datum och tidsperiod ska anges — gör det i varje rapport.

## Arkitekturprincip

`ted_client.py` är första källadaptern. Varje ny källa blir en egen modul med samma
kontrakt: hämta → normalisera till `Notice` → `storage.upsert`. Statistikdatabasens
CSV-import blir nästa adapter när rapportmallen är validerad mot en riktig kund.

**Regel: inga påhittade endpoints.** En källa integreras först när dess API/format
verifierats mot verkliga svar (inspelade som testfixturer, aldrig live-anrop i tester).
