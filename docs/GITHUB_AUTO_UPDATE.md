# GitHub Auto Update

PiViewer controleert automatisch op GitHub-updates via:

- `https://raw.githubusercontent.com/Techraym/PiViewer/main/updates/index.json`
- `https://raw.githubusercontent.com/Techraym/PiViewer/main/releases/PiViewer_XXXX.zip`
- `https://raw.githubusercontent.com/Techraym/PiViewer/main/releases/PiViewer_XXXX.zip.sha256`

Gedrag:

- USB-update blijft altijd eerste prioriteit.
- GitHub-update controleert bij opstarten.
- Tijdens normaal draaien wordt maximaal 1x per 24 uur gecontroleerd.
- SHA256 is verplicht voor iedere update.
- Bij ontbrekende of afwijkende SHA wordt de update geweigerd.
