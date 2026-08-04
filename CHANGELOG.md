# PiViewer 2028

- Fix: USB Photo Viewer klok is volledig losgekoppeld van de fotowissel.
- De klok in de zwarte statusbalk wordt elke seconde bijgewerkt.
- Bij de Photo Viewer wordt voor klokupdates alleen de bovenste statusbalk opnieuw naar de framebuffer geschreven.
- De foto zelf wordt niet elke seconde opnieuw geconverteerd of getekend; dit is lichter voor Raspberry Pi 2.
- Volledig frame wordt periodiek opnieuw geschreven als bescherming tegen console-doorbraak.
- Stream-statusbalk-fix uit PiViewer 2027 blijft behouden.
