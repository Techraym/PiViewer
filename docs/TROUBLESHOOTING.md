# Troubleshooting

## Service bekijken

```bash
sudo systemctl status piviewer-dev
journalctl -u piviewer-dev -f
```

## Config controleren

```bash
python3 -m json.tool /etc/piviewer-dev/piviewer.json
```

## Stream testen

```bash
mpv "https://d2eanln3bsfb0d.cloudfront.net/nlpo/clr-nlpo/rtvmeppel/index.m3u8"
```

## Twitch testen

```bash
streamlink twitch.tv/richard841116 480p,360p,best
```

## Webinterface niet bereikbaar

```bash
sudo /opt/piviewer-dev/scripts/healthcheck.sh
ss -ltnp | grep 8080
```
