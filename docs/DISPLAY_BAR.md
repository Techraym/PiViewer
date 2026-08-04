# PiViewer statusbalk

Vanaf PiViewer 2027 wordt de zwarte statusbalk bovenin als drie vaste zones behandeld:

- links: lokale tijd
- midden: PiViewer by Techraym
- rechts: softwareversie, bijvoorbeeld PiViewer 2027

Voor mpv-streams wordt een monospaced overlay gebruikt zodat de tekst op Raspberry Pi builds niet meer aan elkaar plakt.

Voor de USB Photo Viewer wordt de klok actief elke seconde opnieuw getekend, ook als de foto nog niet wisselt.


## PiViewer 2028

Bij de USB Photo Viewer loopt de klok los van de fotowissel. Alleen de bovenste statusbalk wordt elke seconde opnieuw geschreven.
