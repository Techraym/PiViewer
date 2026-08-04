# PiViewer Auto Update

PiViewer ondersteunt twee updatepaden:

1. USB-update met `PiViewer_XXXX.zip`
2. GitHub-update via `updates/index.json`

De GitHub-updater draait via systemd:

- `piviewer-github-update.service`
- `piviewer-github-update.timer`

Controle:

- bij opstarten na ongeveer 2 minuten
- daarna elke 24 uur

Elke GitHub-update wordt alleen geïnstalleerd als de SHA256 van de gedownloade ZIP exact overeenkomt met de waarde in `updates/index.json`.

USB-update blijft apart bestaan en behoudt prioriteit binnen PiViewer zelf.
