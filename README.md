# PiViewer 2028

# PiViewer 2018

# PiViewer 2.0.0 Lite Dev

PiViewer Lite is een lichte headless signage/player voor Raspberry Pi 2.

## Doel

- Hoofdstream HLS draait standaard altijd.
- Geplande streams uit JSON krijgen voorrang.
- USB-slideshow met foto's krijgt voorrang boven hoofdstream, maar niet boven planning.
- Ontwikkeling via SSH in `/opt/piviewer-dev`.
- Later te bouwen als web-release voor `https://raysnijder.nl/rep/piviewer/`.

## Installatie SSH-dev

Kopieer deze map naar de Pi en voer uit:

```bash
cd /tmp/PiViewer_SSH_dev
sudo bash scripts/install_dev.sh
```

Daarna:

```bash
sudo systemctl status piviewer-dev
journalctl -u piviewer-dev -f
```

Webinterface:

```text
http://<ip-van-pi>:8080
```

## Belangrijke paden

```text
/opt/piviewer-dev               Applicatie
/etc/piviewer-dev/piviewer.json Configuratie
/var/log/piviewer-dev           Logs
/var/lib/piviewer-dev           Runtime/status/cache
```


## Pi 2 performanceprofiel

Deze versie gebruikt standaard een lichter mpv-profiel: kleine cache, laagste HLS-variant en audio uit. Zet `audio_enabled` in `/etc/piviewer-dev/piviewer.json` op `true` als HDMI-audio nodig is.


## Playerprofielen

In `/etc/piviewer-dev/piviewer.json` kan `player.quality_profile` worden ingesteld op:

- `quality`: beste beeldkwaliteit, bedoeld voor Pi 3B-test.
- `balanced`: standaard, betere kwaliteit dan minimum met beperkte belasting.
- `pi2_lite`: noodprofiel voor Raspberry Pi 2 als de stream hapert.



## Webbeheer

Vanaf 2.0.6-lite-dev kunnen hoofdstream, geplande streams en WiFi / Network-instellingen via `http://<ip-van-de-pi>:8080/` worden beheerd.


## USB Photo Viewer

Plaats een USB-stick met foto's in een willekeurige USB-poort. Als er geen geplande stream actief is, start PiViewer automatisch de slideshow. Verwijder je de USB-stick, dan gaat PiViewer automatisch terug naar de hoofdstream. Zie `docs/USB_PHOTOVIEWER.md`.


## 2.0.9 USB Photo Viewer fix

Foto's op USB worden nu eerst geconverteerd naar Pi-vriendelijke 1280x720 JPEG-cachebestanden om groene blokken/zwart beeld te voorkomen.


## USB Photo Viewer

Vanaf 2.0.10 gebruikt PiViewer `fbi` voor foto's. Streams blijven via `mpv` lopen.


## 2.0.13 note
USB Photo Viewer schaalt foto’s nu op naar de maximale framebufferhoogte, met behoud van verhouding.


## PiViewer 2018

Vanaf nu gebruiken we oplopende versies zonder toevoegingen: PiViewer 2018, PiViewer 2018, enzovoort.

Nieuw in deze versie:
- WiFi instellen via `WiFi.txt` op USB.
- Automatisch updaten vanaf USB wanneer daar een hogere PiViewer-versie op staat.


## WiFi foutscherm

Vanaf PiViewer 2018 zit `nossid.png` in `/opt/piviewer-dev/assets/nossid.png`. Dit bestand hoort bij de code/installatie, niet op de USB-stick. Het wordt gebruikt wanneer netwerk/internet niet beschikbaar is voor streams en wordt uitgesloten van de normale USB Photo Viewer.


## USB WiFi.txt beveiliging

Vanaf PiViewer 2018 moet `WiFi.txt` expliciet beginnen met een leesregel. Gebruik:

```text
PIVIEWER_WIFI=READ
SSID=NaamVanWifi
PASSWORD=WifiWachtwoord
COUNTRY=NL
```

Of om het bestand bewust te laten negeren:

```text
PIVIEWER_WIFI=SKIP
SSID=NaamVanWifi
PASSWORD=WifiWachtwoord
COUNTRY=NL
```

Zonder `PIVIEWER_WIFI=READ` wijzigt PiViewer de WiFi niet.


## PiViewer 2018

- USB auto-update voert aan het einde een extra service-herstart uit.
- Dit voorkomt dat de update-status of foto-viewer op één afbeelding blijft hangen na een update.


## PiViewer 2028

Deze versie voegt web auto-update toe via raysnijder.nl en toont een dunne zwarte infobalk bovenin het HDMI-beeld met lokale tijd, `PiViewer by Techraym` en de softwareversie. USB auto-update blijft werken en heeft prioriteit boven web-update.

## PiViewer 2028 - Web ZIP Auto Update

Vanaf PiViewer 2028 kan de web-updater direct een losse ZIP op de hosting gebruiken, net als de USB-update.
Plaats bijvoorbeeld dit bestand in de root van de webrepo:

```text
https://raysnijder.nl/rep/piviewer/PiViewer_2024.zip
```

Voor een volgende update plaats je alleen een hogere ZIP, bijvoorbeeld `PiViewer_2024.zip`.
`latest.json` en `latest.zip` zijn niet meer verplicht voor de web-updater.
USB-update blijft prioriteit houden boven web-update.
