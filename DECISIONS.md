# DECISIONS – Muffi Rahmen

## 2026-05-16 – V1 bewusst einfach halten
**Entscheidung:** V1 wird minimal und robust gebaut.

**Enthalten in V1:**
- Basisbetrieb lokal im Heimnetz
- Bildverwaltung (Upload/Quelle) + stabile Anzeige
- Basis-UI auch mobil nutzbar
- Grundsteuerung (LED, Motor-Basis falls freigegeben)



**Grund:** Schneller zu einem stabilen, verständlichen Produktzustand mit weniger Risiko.

## 2026-05-17 – Medienquelle für Nutzer klar trennen
**Entscheidung:** Medien-UI trennt explizit zwischen lokalem Speicher und Netzwerkordner; Share-Wechsel ist ein eigener Admin-Flow.

**Warum:** Nutzer (v. a. Windows) sollen Ordner wechseln können, ohne Linux-Mountdetails kennen zu müssen. Gleichzeitig darf ein echter Share-Wechsel nicht still „nur als Unterordner“ interpretiert werden.

**Umsetzung:**
- UI-Kategorien: Lokal / Netzwerkordner
- UNC-Hilfe im UI (`?`)
- Share-Check API + Share-Wechsel-Button mit Passwort
