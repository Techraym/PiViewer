# Development workflow

## SSH-bouwversie

Werkmap op de Pi:

```text
/opt/piviewer-dev
```

Service:

```text
piviewer-dev.service
```

## Aanpassen

```bash
sudo nano /opt/piviewer-dev/app/main.py
sudo systemctl restart piviewer-dev
journalctl -u piviewer-dev -f
```

## Healthcheck

```bash
sudo /opt/piviewer-dev/scripts/healthcheck.sh
```

## Release-preview bouwen

```bash
cd /opt/piviewer-dev
bash scripts/package_release_preview.sh
```

Output:

```text
/opt/piviewer-dev/dist/latest.zip
/opt/piviewer-dev/dist/latest.json
```
