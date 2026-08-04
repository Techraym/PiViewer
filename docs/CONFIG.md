# Configuratie

Hoofdconfiguratie:

```text
/etc/piviewer-dev/piviewer.json
```

## Bronvolgorde

PiViewer kiest steeds deze volgorde:

1. Actieve geplande stream.
2. USB-slideshow als foto's gevonden zijn.
3. Hoofdstream HLS.

## Hoofdstream

```json
"main_stream": {
  "name": "RTV Meppel",
  "type": "hls",
  "url": "https://d2eanln3bsfb0d.cloudfront.net/nlpo/clr-nlpo/rtvmeppel/index.m3u8",
  "enabled": true
}
```

## Twitch planning

```json
{
  "id": "twitch_richard_dinsdag_weekly",
  "name": "Twitch Richard841116 dinsdagavond",
  "enabled": true,
  "stream": {
    "type": "twitch",
    "url": "twitch://richard841116",
    "channel": "richard841116",
    "quality": "480p,360p,best"
  },
  "months": [1,2,3,4,5,6,7,8,9,10,11,12],
  "days": ["tuesday"],
  "time": {"start": "19:00", "end": "22:00"},
  "repeat": {"type": "weekly", "interval": 1},
  "priority": 10
}
```
