# USB WiFi.txt

Vanaf PiViewer 2016 wordt een WiFi.txt alleen verwerkt als de eerste niet-lege regel expliciet aangeeft dat PiViewer het bestand mag lezen.

## WiFi instellen

Plaats in de hoofdmap van de USB-stick:

```text
PIVIEWER_WIFI=READ
SSID=NaamVanWifi
PASSWORD=WifiWachtwoord
COUNTRY=NL
```

## WiFi.txt bewust overslaan

```text
PIVIEWER_WIFI=SKIP
SSID=NaamVanWifi
PASSWORD=WifiWachtwoord
COUNTRY=NL
```

## Waarom deze regel?

Zo voorkomt PiViewer dat voorbeeldbestanden of oude WiFi.txt-bestanden automatisch de netwerkconfiguratie wijzigen.

Het wachtwoord wordt niet in de logs weergegeven.
