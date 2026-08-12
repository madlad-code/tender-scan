# Vecka 1-validering: kan rapporten byggas på öppen data?

Genomförd 2026-08-13. Case: ett verkligt ramavtal, en myndighet, en kategori (batterier)
— exakt enligt affärsplanens valideringskrav.

## Caset: Försvarsmakten, "Standardbatterier"

Tilldelningsannons [TED 214151-2026](https://ted.europa.eu/en/notice/-/detail/214151-2026),
publicerad 2026-03-27. Alla siffror nedan är hämtade ur den offentliga annonsen (eForms-XML).

| Uppgift | Värde | Källa |
|---|---|---|
| Köpare | Försvarsmakten | TED |
| Avtalsområde | Standardbatterier (CPV 314*) | TED |
| **Takvolym (max)** | **64 000 000 SEK** | TED: `OverallMaximumFrameworkContractsAmount` |
| **Myndighetens egen prognos** | **32 000 000 SEK** | TED: `OverallApproximateFrameworkContractsAmount` |
| Uppskattat kontraktsvärde | 50 000 000 SEK | TED: `EstimatedOverallContractAmount` |
| Antal anbudsgivare | 6 | TED: tender-block TEN-0001–0006 |
| Kontrakt tecknat | 2026-03-13 | TED |
| Anbudsgivare (offentliga) | AD Sverige, Ahlsell Sverige, Celltech, Lyreco Sverige, SGA Trading, Antirio | TED: organisationsblock |
| Överprövningsinstans | Förvaltningsrätten i Stockholm | TED |

**Kärninsikten står redan i öppen data:** myndigheten själv räknar med att nyttja
hälften av taket (32 av 64 MSEK). Skillnaden mellan tak, prognos och verkligt utfall
är exakt det beslutsunderlag en anbudsgivare saknar.

## Vad öppna källor täcker — och inte

| Rapportdel | Går att bygga på öppna data? | Källa |
|---|---|---|
| Takvolym & myndighetens prognos | ✅ Ja, direkt | TED (API, verifierat live) |
| Vinnare & antal anbudsgivare | ✅ Ja, direkt | TED |
| Konkurrenstryck & historik per myndighet/CPV | ✅ Ja | UHM:s statistik-API (verifierat live, se nedan) |
| Individuella anbudspriser | ⚠️ Ibland — saknades i detta case | TED / tilldelningsbeslut via begäran |
| **Faktiskt avropat under avtalstiden** | ❌ **Nej — finns inte i någon öppen databas** | Endast offentlighetsprincipen |

UHM:s statistikdatabas har ett oadresserat men fungerande API
(`https://www.upphandlingsmyndigheten.se/api/sv/statisticsservice/bridgeapi/statistics`,
verifierat 2026-08-13; export via `.../statistics/export/csv`). Mätvärden: antal anbud,
antal upphandlingar, kontrakterat värde, uppskattat värde — nedbrytbart per köpare och
CPV. Men allt gäller *annonserade/kontrakterade* upphandlingar. Löpande avrop rapporteras
inte dit.

## Konsekvens för kundlöftet

- **48-timmarsrapporten håller** för: tak vs prognos, vinnare, konkurrenstryck,
  historik, ska-kravslista. Allt automatiserbart.
- **Faktiskt utfall kräver utlämning** enligt offentlighetsprincipen (avropsstatistik/
  leverantörsreskontra per avtal). Svarstid i praktiken dagar–veckor.
- **Rätt paketering:** Basrapport (48 h, öppna data) + Fördjupning med verkligt utfall
  (levereras när utlämningen kommit, ingår i priset). Lova aldrig utfallssiffror på 48 h.

## Leadvolym i vertikalen (TED, tilldelningar SWE, aug 2025–aug 2026)

| CPV | Kategori | Tilldelningar/år |
|---|---|---|
| 314* | Batterier/ackumulatorer | 7 |
| 31* | Elektrisk utrustning/komponenter | 193 |
| 32* | Radio/TV/telekom | 140 |
| 38* | Lab/optik/precision | 307 |
| 30* | Datorer/kontorsmaskiner | 142 |

Slutsats: **batterier ensamt är för smalt** (7 tilldelningar/år över EU-tröskel).
Vertikalen "elektronik & teknisk materiel" (31+32+38, ev. 30) ger ~600–780
tilldelningar/år ≈ 50–65/månad, med i snitt flera namngivna anbudsgivare per
tilldelning — gott om samtalsunderlag. Batterier förblir spjutspetsen i pitchen,
inte hela marknaden.

## Verdikt

Valideringen **godkänd med justering**: rapporten går att bygga och sälja på öppna
data, men "faktiskt avropat" — själva kronjuvelen — kräver offentlighetsprincipen
per myndighet. Nästa steg är att skicka en verklig begäran till Försvarsmakten
(mall: [begaran-mall.md](begaran-mall.md)) och mäta verklig svarstid. Svarstiden
avgör prissättningen på fördjupningen.

---
*Källor: TED (Europeiska unionens publikationsbyrå), Upphandlingsmyndighetens
statistikdatabas (öppna data, hämtat 2026-08-13). Statistiken avser angivna
tidsperioder ovan.*
