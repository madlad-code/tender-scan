# Mallar: påminnelse dag 3 (batch 1)

`tender-scan foia due` listar alla begäranden som passerat dag 3. Den vet inte
vad kommunen har svarat — bara att klockan gått. Listan är alltså vem du ska
titta på, inte vem du ska mejla, och de tjugo faller i fyra grupper med olika
behov. Skicka mall A eller B; för grupp C och D är en generell påminnelse fel
åtgärd och gör mest skada.

Ärendenumren nedan står i `notes` på respektive rad efter att
`scripts/registrera_batch1_svar.py --live` har körts.

Grupperna är 5 + 10 + 4 + 1 = 20, alltså hela batch 1. Går summan inte ihop har
någon kommun fallit mellan grupperna.

## Vem som ska ha vad, 2026-09-03

**A. Helt tysta — 5 st.** Eskilstuna, Katrineholm, Aneby, Bjurholm, Dorotea.
Inget svar alls, inte ens ett autosvar. Här är den troliga förklaringen en
oläst funktionsbrevlåda, och påminnelsen ska vara tydlig med datum och
skyndsamhetskrav. **Mall A.**

**B. Bekräftat, sedan tyst — 10 st.** Helsingborg, Jönköping, Borås, Gävle,
Karlstad, Halmstad, Haninge, Kalmar, Enköping, Grästorp. De har diariefört och
i flera fall vidarebefordrat internt, men inget har hänt sedan dess.
Bekräftelsen är kvittot: den bevisar att begäran kommit fram, så påminnelsen
kan vara kortare och hänvisa till deras eget ärendenummer. **Mall B.**

Haninge hör hit trots att de nämnt avgift — de har flaggat att kopieringstaxan
*kan* bli tillämplig, inte räknat fram ett belopp, och mall B ber ändå om
beloppet i förväg.

**C. Arbete pågår — rör inte med en generell påminnelse — 4 st.**

| Kommun | Vad som faktiskt väntar | Rätt åtgärd |
| --- | --- | --- |
| Hässleholm | Avgiften om 161 kr är accepterad; betalningsinstruktion har inte kommit | Svara i den befintliga tråden till ahmet.baran@hassleholm.se och be om faktura/bankgiro |
| Härnösand | Kostnad utlovad, exakt summa ej meddelad | Svara Ann-Catrine Forsberg och be om beloppet |
| Falun | Sekretessbedömning av leverantörsfakturor pågår, kostnad kan tillkomma | Låt gå till dag 5, be då om tidsuppskattning |
| Huddinge | Avtalskatalogen levererad; ekonomienheten äger reskontran | Mejla ekonomiavdelningen@huddinge.se direkt, inte servicecenter |

En generell påminnelse till någon av de fyra läser som att man inte läst deras
svar, och kostar mer i välvilja än den vinner i dagar.

**D. Göteborg — svarat på båda punkterna.** Avtalssammanställningen kom som
fil, och reskontran hänvisades till stadens öppna data. Ingen påminnelse.
Kontrollera i stället att öppna data-sidan faktiskt täcker 2023–2026; gör den
inte det, återkom till diariet, som erbjudit sig att lämna sammanställningen på
annat sätt.

---

## Mall A — ingen kontakt alls

**Ämne:** Påminnelse: Begäran om utlämnande av allmän handling – avtalskatalog och leverantörsreskontra

Hej,

Jag skickade nedanstående begäran om utlämnande av allmän handling till er den
**31 augusti 2026** och har ännu inte fått något svar eller någon
mottagningsbekräftelse.

Enligt 2 kap. 15–16 §§ tryckfrihetsförordningen ska en begäran om allmän
handling behandlas skyndsamt. Jag ber er därför bekräfta att begäran kommit
fram, ange diarienummer och handläggare, samt lämna besked om när handlingarna
kan lämnas ut.

Om någon del av begäran bedöms omfatta sekretess eller kräva betydande
arbetsinsats tar jag gärna emot övriga delar under tiden, och ber i så fall om
ett skriftligt beslut med motivering och överklagandehänvisning för den del som
inte lämnas ut, i enlighet med 6 kap. 7 § offentlighets- och sekretesslagen.

Ursprunglig begäran följer nedan.

Med vänlig hälsning
Oscar Enghag
oscarenghag@gmail.com

*[klistra in den ursprungliga begäran]*

---

## Mall B — bekräftat men inget hänt

**Ämne:** Påminnelse ärende [ÄRENDENUMMER]: begäran om avtalskatalog och leverantörsreskontra

Hej,

Den 31 augusti 2026 begärde jag ut avtalskatalog och leverantörsreskontra, och
fick samma dag en bekräftelse med ärendenummer **[ÄRENDENUMMER]**. Jag har inte
hört något sedan dess.

Jag ber om besked om när handlingarna kan lämnas ut, och gärna namn på
handläggaren så att jag kan vända mig direkt dit med frågor. Är begäran redan
vidarebefordrad internt är det den mottagande enhetens tidsuppskattning jag är
ute efter.

Blir utlämnandet förenat med avgift önskar jag beloppet i förväg.

Med vänlig hälsning
Oscar Enghag
oscarenghag@gmail.com

---

## Efter utskick

Registrera påminnelsen samma dag, annars fortsätter `foia due` att lista
dag 3 i stället för att gå vidare till dag 5:

```
tender-scan foia did <id> reminder_1 --on 2026-09-03
```

Dag 5 är ett telefonsamtal till registratorn, inte ännu ett mejl — en oläst
funktionsbrevlåda löser sig på en minut i telefon och inte alls per mejl. Dag
10 är begäran om skriftligt avslagsbeslut, som är det som gör saken
överklagbar till kammarrätten.
