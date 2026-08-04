# PiViewer 2024 - Web ZIP Auto Update

Vanaf PiViewer 2024 werkt de web-update hetzelfde principe als de USB-update:
plaats gewoon een update-ZIP op de hosting.

Voorbeeld:

```text
https://raysnijder.nl/rep/piviewer/PiViewer_2024.zip
https://raysnijder.nl/rep/piviewer/PiViewer_2024.zip
```

PiViewer controleert maximaal 1x per 24 uur of er een hogere ZIP-versie klaarstaat.
De USB-update blijft altijd prioriteit houden. Als er op USB een hogere versie staat,
wordt de web-update overgeslagen.

## Config

```json
"updates": {
  "usb_update": {
    "enabled": true,
    "auto_install": true
  },
  "web_update": {
    "enabled": true,
    "auto_install": true,
    "base_url": "https://raysnijder.nl/rep/piviewer/",
    "file_pattern": "PiViewer_{version}.zip",
    "direct_zip_scan": true,
    "manifest_fallback": false,
    "lookahead_versions": 20,
    "interval_hours": 24
  }
}
```

## Handmatig testen

Reset de 24-uurs teller:

```bash
sudo rm -f /var/lib/piviewer-dev/web-update-last-check.json
sudo systemctl restart piviewer-dev
journalctl -u piviewer-dev -f -o cat
```

Controleer op de Pi of het ZIP-bestand online zichtbaar is:

```bash
curl -I "https://raysnijder.nl/rep/piviewer/PiViewer_2024.zip?t=$(date +%s)"
```

## Logregels

```text
Web-ZIP update controle gestart
Web-ZIP controle: https://raysnijder.nl/rep/piviewer/PiViewer_2024.zip
Online PiViewer ZIP gevonden
Hogere PiViewer-versie gevonden op web
Web Auto Update gestart
```

## Bestanden

```text
/var/lib/piviewer-dev/web-update-last-check.json
/var/lib/piviewer-dev/web-update-in-progress
/var/log/piviewer-dev/web-update.log
```
