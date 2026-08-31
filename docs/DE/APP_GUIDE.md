# Anleitung MSL Image Downloader (DE)

Diese Anleitung richtet sich an jemanden, der das Projekt von GitHub herunterlädt und Folgendes tun möchte:
1) die App installieren, 2) sie starten, 3) verstehen, was auf dem Bildschirm zu sehen ist, 4) sie zum Filtern und Herunterladen/Verarbeiten von Bildern nutzen.

> **Wichtiger Hinweis**
> - Dieses Projekt wurde hauptsächlich mit **Anaconda/Conda** entwickelt und genutzt.
> - Das Verfahren mit `python -m venv` + `pip` ist als Alternative enthalten, wurde aber **möglicherweise noch nicht gründlich auf allen Maschinen getestet**.

## 1) Was ist MSL Image Downloader
MSL Image Downloader ist eine App zum Suchen, Herunterladen und Organisieren von Bildern der NASA-Mission Mars Science Laboratory (Curiosity). Beim Öffnen gelangt man zunächst auf einen Bildschirm, auf dem der eigene Name eingegeben wird, danach in die eigentliche App, die in zwei Bereiche unterteilt ist, zwischen denen oben jederzeit gewechselt werden kann:

- **Downloader**: Bilder suchen, filtern und herunterladen.
- **Kataloge (Catalog Manager)**: verwaltet den lokalen Katalog, auf dem die Suche des Downloaders basiert (Status, Updates von der NASA, Überprüfung usw.).

Der Katalog wird beim ersten Start automatisch heruntergeladen, kein manueller Schritt nötig.

## 2) Voraussetzungen
- **Python**: empfohlen **3.11 oder 3.12**
- **Conda**: empfohlen (reduziert Probleme mit "binären" Bibliotheken wie `pyarrow`)
- Internetverbindung: nötig für Katalog-Download/-Updates und um einige externe Dateien herunterzuladen (falls vorgesehen)

> **Technischer Hinweis**: `numpy` ist auf `<2` festgelegt, für die Kompatibilität mit `pyarrow` in manchen Umgebungen.

## 3) Installation (Schritt für Schritt) — Windows

> Dieser Abschnitt behandelt die Installation **unter Windows**.

### 3.1 Projekt herunterladen
Option A (Git):
```bash
mkdir ORDNERNAME
cd ORDNERNAME
git clone <REPO_URL> .
```

Option B (ZIP von GitHub):
- ZIP herunterladen
- in einen Ordner entpacken (z. B. `C:\Users\...\dwnapp`)
- ein Terminal im entpackten Ordner öffnen

### 3.2 Umgebung erstellen (empfohlen: Conda)
Vom Repo-Root aus:
```bash
conda env create -f environment.yml
conda activate dwnapp
```

Hinweis zu `environment.yml`:
- `environment.yml` erstellt die Umgebung (Python + pip) und installiert dann die Bibliotheken über `pip -r requirements.txt`.
- Anders gesagt: **die Liste der Abhängigkeiten steht in `requirements.txt`**, während die YAML-Datei eine saubere, konsistente Umgebung erzeugt.

Alternative (venv + pip):
```bash
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

## 4) App starten
Um den Start zu vereinfachen, wurde eine einzige Datei erstellt: einfach öffnen (Doppelklick, unter Windows), und die Anwendung startet von selbst.

Doppelklick auf `launchers/Avvia_MSL_App.bat`: öffnet den Browser unter `http://localhost:5173`, sobald alles bereit ist.

## 5) Was man in der Oberfläche sieht (kurzer Rundgang)
Nach dem Login öffnet sich zuerst der Bereich **Kataloge**, um den lokalen Katalog herunterzuladen und optional anzupassen. Sobald die geführte Installation abgeschlossen ist, wechselt man über den Auswahlschalter oben zum **Downloader**.

Im Downloader ist die Oberfläche in Bereiche unterteilt:
- **Seitenleiste** (links): Filter, aktuelle Auswahl, Steuerungsschaltflächen
- **Mittlerer Bereich**: Suchergebnisse
- **Vorschau/Metadaten**: Bildvorschau und zugehörige Metadaten
- **Live-Protokoll**: zeigt Fortschritt und Meldungen während des Downloads

Der Ausgabeordner lässt sich oben rechts über die Einstellungen festlegen.

## 6) Die App nutzen (typischer Ablauf)
Ein typischer Ablauf:
1) Ausgabe-/Download-Ordner festlegen
2) Filter anwenden (Sol, Kamera usw.)
3) Auswahl prüfen (wie viele Bilder, was sie enthält)
4) **Download** oder **Verarbeitung** ausführen

### 6.1 Ausgabeordner festlegen
Wenn die App meldet, dass der Ausgabeordner fehlt:
- die Option zur Ordnerauswahl nutzen (Dialog) oder einen manuellen Pfad festlegen (siehe Beispiele unten)
- danach Download/Verarbeitung erneut versuchen

### 6.2 Katalog filtern
Filterbar nach:
- **Sol** (Bereich oder einzeln)
- **Kamera**
- (optional) Mindestgröße, Varianten, Tokens und weitere verfügbare Filter

### 6.3 Herunterladen oder verarbeiten
Allgemeines Verhalten:
- **Download**: speichert die Rohdateien (üblicherweise `.IMG` + `.LBL`) im Ausgabeordner
- **Verarbeitung/Konvertierung**: erzeugt die finale Ausgabe (üblicherweise `.jpg` + `.meta.json`) im Ausgabeordner
