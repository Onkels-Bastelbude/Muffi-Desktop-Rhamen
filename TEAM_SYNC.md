# TEAM_SYNC – Muffi Rahmen

Ziel: Maika, Uwe und Büro haben immer denselben Wissensstand.

## Single Source of Truth
- **Muffirahmen.md** = aktueller Stand (nur diese Datei ist "jetzt" verbindlich)
- **DECISIONS.md** = Entscheidungen mit Begründung
- **ARBEITSPROTOKOLL.md** = Chronik (was gemacht wurde)

## GitHub-Quelle (gemeinsamer Stand)
- Repo: `git@github.com:Onkels-Bastelbude/Muffi-Desktop-Rhamen.git`
- Web: `https://github.com/Onkels-Bastelbude/Muffi-Desktop-Rhamen`

## Pflicht-Ablauf bei jeder Arbeit
0. **Vor Start syncen:** `git pull --rebase`
1. **Vor Start lesen:** `Muffirahmen.md`, `DECISIONS.md`, `ARBEITSPROTOKOLL.md`
2. Arbeit durchführen
3. **Nach Ende aktualisieren:**
   - `Muffirahmen.md` (Heute erledigt / Nächster Schritt / Blocker)
   - `DECISIONS.md` (nur wenn Entscheidung gefallen ist)
   - `ARBEITSPROTOKOLL.md` (kurzer Logeintrag)
4. **Sync zurück ins Repo:** `git add -A && git commit -m "..." && git push`

## Update-Regeln
- Kurz, konkret, kein Roman
- Eine Wahrheit: kein doppelter Stand in zig Dateien
- Wenn unklar: in `Muffirahmen.md` unter "Offene Fragen" eintragen

## Trigger (ab sofort)
- **"Muffi Start"**
  - Projektstand laden aus `Muffirahmen.md` + `DECISIONS.md`
  - Antwort enthält: aktueller Stand, nächster Schritt, direkter Startpunkt

- **"Muffi Notiz: ..."**
  - Notiz in `Muffirahmen.md` eintragen und sauber einsortieren

- **"Muffi Büro: ..."** oder **"kläre es im Büro ab ..."**
  - Büro-Analyse (Uwe + Contrarian + Maika)
  - Input immer aus `Muffirahmen.md` + `DECISIONS.md`
  - Ergebnis als Fazit in `Muffirahmen.md` eintragen
