# Vad som krävs för att räkna, och vad som går att bevisa

_Skriven 2026-09-02 mot koden i `utilization.py`, `payments/base.py` och
`storage.py`, och mot de svar som kommit in på batch 1._

Frågan är: exakt vilka filer behövs för att köra de tunga beräkningarna, och
vad går att säga till en säljchef utan att ljuga. Svaret är inte "alla filer vi
kan få". Kedjan har fyra länkar och tre av dem är redan hela.

## 1. Vad joinen faktiskt kräver

`utilization`-vyn i `utilization.py` beräknar allt genom en enda join:

```
supplier_payments p
  JOIN award_winners   w  ON p.supplier_orgnr = w.supplier_orgnr
  JOIN framework_buyers b  ON p.payer_orgnr   = b.buyer_orgnr
                          AND b.notice_id     = w.notice_id
  WHERE betalningens period ligger inom [f.start_date, f.end_date]
```

Fyra villkor måste hålla samtidigt för att en krona ska räknas som avrop:

| Villkor | Var det kommer ifrån | Har vi det? |
| --- | --- | --- |
| Takvolym med källa och konfidens | TED eForms, M1 | **Ja**, 137 notiser |
| Vinnare med organisationsnummer | TED eForms, M2 | **Ja** |
| Namngivna köpare med orgnr | TED eForms → `framework_buyers` | **Ja** |
| Betalning med leverantörsorgnr, datum och belopp | Köparens reskontra | **Nej, nästan aldrig** |

Tre av fyra länkar är alltså klara för alla 137 avtalen. Det som saknas är
uteslutande den fjärde.

### Vad en reskontrafil måste innehålla, rad för rad

Ur `payments/base.py`:

- **Bokförings- eller fakturadatum.** `to_payments` kastar varje rad där
  `booking_date is None` — utan datum går raden inte att placera i en
  avtalsperiod. Detta är hårt: en fil utan datumkolumn är värdelös för
  utnyttjandegrad, oavsett hur många belopp den innehåller.
- **Belopp.**
- **Leverantörens organisationsnummer**, eller ett leverantörsnamn som
  normaliseras till en vinnares namn. `WinnerIndex.resolve` faller tillbaka på
  namnmatchning och lånar vinnarens orgnr — så namn duger, men orgnr är
  säkrare.
- **Köparens orgnr** kommer *inte* ur filen utan ur loadern, som en konstant
  (`GoteborgLoader.payer_orgnr = "212000-1355"`).

Och en sak till, som avgör hur mycket varje fil är värd: `to_payments` slänger
alla rader vars leverantör inte är vinnare på något ramavtal i korpusen. En
kommuns reskontra bidrar bara i den mån dess leverantörer råkar vara vinnare i
de 137 notiserna.

## 2. Den viktigaste upptäckten: 5,9 % är självförvållat

STATE.md säger att Göteborg mäts på **en månad av sjutton** och att
periodtäckningen därför är 5,9 %. Det beskrivs som den bindande begränsningen.

Men `GoteborgLoader.covers` säger `"monthly CSV, 2016 onwards"`, och
`payments load goteborg` utan `--year`/`--month` hämtar **varje daterad
distribution katalogen listar**. Loadern finns. Filerna är publika. Ingen
begäran behövs.

De 5,9 % är alltså inte ett tak i verkligheten — det är en månad som någon
laddade in för att testa. Att köra

```
tender-scan payments load goteborg
```

är den enskilt högst avkastande åtgärden i hela projektet: noll nya filer, noll
ny kod, noll kronor, och periodtäckningen på notis 109559-2026 går från 1/17
till potentiellt 17/17. **Gör detta innan något annat.**

Göteborgs diarium bekräftade dessutom oombett samma sak i mejl 2026-09-01:
hela stadens leverantörsreskontra ligger årsvis på stadens öppna data.

## 3. De nio filerna i inkorgen — vad de faktiskt är

Fyra av nio matar avropsberäkningen. Fem gör det inte.

### Reskontra (matar beräkningen)

| Fil | Kommun | Värde |
| --- | --- | --- |
| `Öppna data 2023.xlsx` | Borås | **Högst värde av allt som kommit in.** 36 månader sammanhängande, +8 till 2026-09-09 |
| `Öppna data 2024.xlsx` | Borås | ” |
| `Öppna data 2025.xlsx` | Borås | ” |
| `Leverantörsreskontraöversikt.xlsx` | Bjurholm | Osäkert. "Översikt" antyder aggregat; utan fakturadatum per rad är den obrukbar för utnyttjandegrad |

Borås är det enda FOIA-svaret som kan flytta *periodtäckningen*, alltså den
siffra som binder analysen. Att den kommer från en enda kommun är en
begränsning att vara ärlig om.

### Avtalskatalog (matar inte beräkningen)

`Avtal 20230101-20260901.xlsx` (Göteborg), `Avtalskatalogen.xlsx` (Huddinge),
`SH ContractExport 26091.pdf` (Jönköping), `Avtalsdatabasen 20260616.xlsx`
(Grästorp), `Avtalsstatistik_09011048.xls` (Bjurholm).

Dessa går **inte** in i utnyttjandegraden — takvolymen kommer ur TED, inte ur
kommunens register. De är värdefulla av två andra skäl:

1. **Validering av takextraktionen.** Stämmer kommunens eget avtalsregister med
   vad M1 läste ut ur notisen? Det är enda sättet att kontrollera
   `cap_confidence` mot verkligheten.
2. **Marknadsstorlek.** Grästorp skriver rakt ut att deras avtalsdatabas saknar
   entreprenad, direktupphandling och delar av Adda och Sinfra. Skillnaden
   mellan kommunens register och TED är ett mått på hur mycket inköp som aldrig
   syns i TED alls.

### Blockeraren ingen har nämnt

`LOADERS` innehåller `vgr`, `goteborg`, `vasteras` — alla tre för öppna
data-kataloger. Schemat tillåter `source='foia'`, men **ingenting i koden
producerar en sådan rad.** Ingen av de nio filerna kan läsas in av någon
befintlig kodväg. Innan Borås tre år kan räknas måste någon skriva en adapter
som tar ett kalkylark, låter användaren peka ut kolumnerna, och deklarerar
köparens orgnr.

Det är dagens största kodhål, och det är litet: en `Loader`-subklass som läser
xlsx i stället för att hämta från en katalog.

## 4. Vad som går att bevisa, i tre nivåer

### Nivå 1 — bevisbart i dag, noll ny data, n=137

Detta kräver ingen reskontra alls och vilar på hela korpusen:

- Hur många ramavtalsnotiser som **inte publicerar någon takvolym**.
- Hur många som **inte publicerar rangordning** mellan vinnande leverantörer.
  Rapporten räknar redan detta per notis (`ranked` i `render_markdown`).
- Antal leverantörer per ramavtal.

Detta är de starkaste påståendena du har, därför att n är 137 och för att inget
av dem behöver en enda faktura. Det är också exakt det STATE.md pekar ut som
säljargumentet: *fördelningen mellan vinnande leverantörer finns inte
publicerad någonstans*. Till en säljchef:

> "Ni är rangordnad tvåa på det här avtalet. I hundratrettiosju ramavtal jag
> gått igenom publiceras rangordningen i [X] av dem, och i inget av dem
> publiceras vad varje leverantör faktiskt fick betalt. Varken ni eller er
> konkurrent kan se det. Jag kan räkna ut det."

Kör siffran för [X] innan du säger den.

### Nivå 2 — bevisbart inom en dag, filerna är redan publika

Full inläsning av Göteborg. Efter det:

- Utnyttjandegrad på 109559-2026 med hög periodtäckning i stället för 5,9 %.
- Leverantörsfördelning inom Göteborgs ramavtal — vem av vinnarna som faktiskt
  fick pengarna, månad för månad.

Detta är n=1 på köparsidan men n=många på månadssidan, och det är den första
siffra i projektet som klarar `confidence_band = "high"` om
`cap_confidence ≥ 0,9` och köpartäckningen räcker.

### Nivå 3 — kräver ny kod plus Borås

Med FOIA-adaptern skriven och Borås inläst får du en andra köpare med 36–44
månader. Först då finns en jämförelse *mellan* kommuner, och först då blir det
meningsfullt att prata om mönster snarare än om ett fall.

## 5. Vad du inte ska säga till en säljchef

- **Inte** att avrop landar på en viss andel av takvolymen. Det bygger på n=1
  och pekar dessutom åt fel håll. Kommer den siffran upp: säg att du mäter den
  och att den varierar, inte vad den är.
- **Inte** någon prognos. `_METHOD_LIMITATIONS` säger själv att
  tidsnormaliseringen antar jämn förbrukning och att verkliga avrop är ojämna.
- **Inte** en utnyttjandegrad utan sina två täckningstal. Koden vägrar rendera
  det; säg det inte muntligt heller.

## 6. Prioriterad ordning

1. `tender-scan payments load goteborg` — hela historiken. Ingen ny data, ingen
   ny kod. Detta ensamt avgör om 5,9 % var ett verkligt tak eller ett
   inläsningsglapp.
2. Kör de två frågorna i avsnitt 7 och se **vilka kommuners reskontra som låser
   upp flest avtal**. Jaga dem, inte de som råkar svara snabbast.
3. Räkna nivå 1-siffrorna ur korpusen. De går att sälja på i morgon.
4. Skriv FOIA-adaptern. Läs in Borås.
5. Kontrollera om Bjurholms reskontraöversikt har fakturadatum per rad. Har den
   inte det är den obrukbar för utnyttjandegrad, hur komplett den än ser ut.

## 7. Två frågor som avgör prioriteringen

Vilken köpares reskontra låser upp flest ramavtal:

```sql
SELECT b.buyer_name, b.buyer_orgnr, COUNT(DISTINCT b.notice_id) AS notiser
FROM framework_buyers b
JOIN framework_agreements f ON f.notice_id = b.notice_id AND f.is_framework = 1
GROUP BY b.buyer_orgnr
ORDER BY notiser DESC;
```

Vilka avtal är färdiga att mätas i samma sekund betalningarna finns:

```sql
SELECT f.notice_id, f.buyer_name, f.cap_value_sek, f.cap_confidence,
       COUNT(DISTINCT w.supplier_orgnr) AS vinnare_med_orgnr
FROM framework_agreements f
JOIN award_winners w ON w.notice_id = f.notice_id AND w.supplier_orgnr IS NOT NULL
WHERE f.is_framework = 1 AND f.cap_value_sek IS NOT NULL
GROUP BY f.notice_id
ORDER BY f.cap_value_sek DESC;
```

Den första frågan är den viktigaste i hela dokumentet. Batch 1 valdes inte
utifrån vilka kommuner som förekommer i korpusen — kör frågan innan batch 2
skickas, annars jagas fel kommuner igen.
