# USB Photo Viewer

Vanaf 2.0.12 gebruikt PiViewer voor USB-foto's een eigen framebuffer-renderer.

Waarom:
- mpv gaf groene blokken/zwart beeld bij foto's op de Pi.
- fbi toonde foto's goed, maar liet tussen beelden zwart/login zien.
- De framebuffer-renderer schrijft direct naar `/dev/fb0` en houdt het beeld vast.

Gedrag:
- USB-stick in willekeurige USB-poort: foto's worden automatisch gevonden.
- Foto's worden gecachet naar Pi-vriendelijke JPEG's.
- Slideshow wisselt volgens `duration_seconds`.
- USB verwijderen: hoofdstream start automatisch opnieuw.
