# Web-release notities

De web-release wordt later opgebouwd uit dezelfde projectstructuur.

Online doel:

```text
https://raysnijder.nl/rep/piviewer/
```

Vaste bestanden:

```text
install.sh
update.sh
latest.zip
latest.json
VERSION
CHANGELOG.md
releases/piviewer-<versie>.zip
```

Belangrijk:

- `/etc/piviewer/piviewer.json` mag bij updates niet overschreven worden.
- De release bevat alleen `config/piviewer.example.json`.
- `latest.zip` is altijd de nieuwste stabiele release.
