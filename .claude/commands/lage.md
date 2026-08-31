---
description: Uppdatera STATE.md och visa var projektet står
---

Kör `python3 scripts/state.py --print` och läs resultatet.

Sammanfatta sedan för användaren, kort och på svenska:

- Vad som ändrats sedan förra gången, om något är uppenbart nytt.
- Allt som ser fel ut och är värt att åtgärda: opushade commits, en container
  vars image är äldre än senaste commit, en tom tabell som borde ha rader,
  en utlämnandebegäran vars deadline passerat.
- Ingenting annat. Upprepa inte hela filen tillbaka — den står redan i kontexten.

Om användaren gett dig ny information som hör hemma i planen — ett beslut, ett
skickat mejl, något de väntar på — skriv in den mellan `<!-- MANUELLT:START -->`
och `<!-- MANUELLT:SLUT -->` i `STATE.md` innan du kör om skriptet. Det är den
enda delen av filen som inte skrivs över, och den enda del du får redigera för
hand.
