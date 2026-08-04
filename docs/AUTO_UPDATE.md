# PiViewer Auto Update

PiViewer 2030 ondersteunt:

1. USB-update met `PiViewer_XXXX.zip`
2. GitHub-update via `updates/index.json`

De GitHub-updater draait los van `main.py` via systemd:

- `piviewer-github-update.service`
- `piviewer-github-update.timer`

Controle:

- bij opstarten na ongeveer 2 minuten
- daarna elke 24 uur

Een GitHub-update wordt alleen geïnstalleerd als de SHA256 van de gedownloade ZIP exact overeenkomt met de SHA256 in `updates/index.json`.

USB-update blijft apart bestaan.
