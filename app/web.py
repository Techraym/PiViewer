import html
import json
import re
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from typing import Any, Dict, List
from urllib.parse import parse_qs, urlparse

from wifi import connect_wifi, scan_wifi, wifi_status


DAY_OPTIONS = [
    ('monday', 'Maandag'),
    ('tuesday', 'Dinsdag'),
    ('wednesday', 'Woensdag'),
    ('thursday', 'Donderdag'),
    ('friday', 'Vrijdag'),
    ('saturday', 'Zaterdag'),
    ('sunday', 'Zondag'),
]

MONTH_OPTIONS = [
    (1, 'Jan'), (2, 'Feb'), (3, 'Mrt'), (4, 'Apr'), (5, 'Mei'), (6, 'Jun'),
    (7, 'Jul'), (8, 'Aug'), (9, 'Sep'), (10, 'Okt'), (11, 'Nov'), (12, 'Dec'),
]

LOG_FILE = Path('/var/log/piviewer-dev/piviewer-dev.log')
USB_UPDATE_LOG = Path('/var/log/piviewer-dev/usb-update.log')


class PiViewerWeb:
    def __init__(self, host: str, port: int, state, config_path: str, logger):
        self.host = host
        self.port = int(port)
        self.state = state
        self.config_path = Path(config_path)
        self.logger = logger
        self.server = None

    def start(self) -> None:
        state = self.state
        config_path = self.config_path
        logger = self.logger

        def esc(value: Any) -> str:
            return html.escape('' if value is None else str(value), quote=True)

        def load_config() -> Dict[str, Any]:
            with config_path.open('r', encoding='utf-8') as f:
                return json.load(f)

        def save_config(data: Dict[str, Any]) -> None:
            config_path.parent.mkdir(parents=True, exist_ok=True)
            timestamp = time.strftime('%Y%m%d-%H%M%S')
            if config_path.exists():
                backup = config_path.with_name(f'{config_path.name}.webbackup.{timestamp}')
                backup.write_text(config_path.read_text(encoding='utf-8'), encoding='utf-8')
            tmp = config_path.with_suffix('.json.tmp')
            tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
            tmp.replace(config_path)
            logger.info('Configuratie bijgewerkt via webinterface')

        def tail_file(path: Path, max_lines: int = 250) -> List[str]:
            if not path.exists():
                return [f'Logbestand niet gevonden: {path}']
            try:
                # Kleine logbestanden zijn verwacht door RotatingFileHandler.
                lines = path.read_text(encoding='utf-8', errors='replace').splitlines()
                return lines[-max_lines:]
            except Exception as exc:
                return [f'Logbestand kon niet gelezen worden: {path}: {exc}']

        def combined_log_text(max_lines: int = 250) -> str:
            lines = []
            lines.append('===== PiViewer live log =====')
            lines.extend(tail_file(LOG_FILE, max_lines))
            if USB_UPDATE_LOG.exists():
                lines.append('')
                lines.append('===== USB update log =====')
                lines.extend(tail_file(USB_UPDATE_LOG, 120))
            return '\n'.join(lines[-(max_lines + 140):])

        def first(form: Dict[str, List[str]], key: str, default: str = '') -> str:
            return (form.get(key, [default])[0] or '').strip()

        def checked(form: Dict[str, List[str]], key: str) -> bool:
            return first(form, key) in ('1', 'true', 'on', 'yes')

        def parse_int_list(values: List[str], valid_min: int, valid_max: int) -> List[int]:
            result = []
            raw = ','.join(values)
            for part in re.split(r'[,\s]+', raw):
                if part.strip().isdigit():
                    nr = int(part.strip())
                    if valid_min <= nr <= valid_max and nr not in result:
                        result.append(nr)
            return result

        def slug(value: str) -> str:
            value = value.lower().strip()
            value = re.sub(r'[^a-z0-9_-]+', '_', value)
            value = re.sub(r'_+', '_', value).strip('_')
            return value or f'stream_{int(time.time())}'

        def redirect(path: str, message: str = '') -> str:
            if message:
                return path + ('&' if '?' in path else '?') + 'msg=' + message.replace(' ', '+')
            return path

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                return

            def _send(self, code: int, body: str, content_type: str = 'text/html; charset=utf-8'):
                data = body.encode('utf-8')
                self.send_response(code)
                self.send_header('Content-Type', content_type)
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _redirect(self, location: str):
                self.send_response(303)
                self.send_header('Location', location)
                self.end_headers()

            def _form(self) -> Dict[str, List[str]]:
                length = int(self.headers.get('Content-Length', '0'))
                raw = self.rfile.read(length).decode('utf-8')
                return parse_qs(raw, keep_blank_values=True)

            def do_GET(self):
                parsed = urlparse(self.path)
                path = parsed.path
                query = parse_qs(parsed.query)
                if path == '/api/status':
                    self._send(200, json.dumps(state.snapshot(), indent=2, ensure_ascii=False), 'application/json; charset=utf-8')
                    return
                if path == '/api/config':
                    try:
                        self._send(200, config_path.read_text(encoding='utf-8'), 'application/json; charset=utf-8')
                    except Exception as exc:
                        self._send(500, json.dumps({'error': str(exc)}), 'application/json; charset=utf-8')
                    return
                if path == '/api/wifi/status':
                    self._send(200, json.dumps(wifi_status(), indent=2, ensure_ascii=False), 'application/json; charset=utf-8')
                    return
                if path == '/api/wifi/scan':
                    self._send(200, json.dumps({'networks': scan_wifi()}, indent=2, ensure_ascii=False), 'application/json; charset=utf-8')
                    return
                if path == '/api/live-log':
                    self._send(200, combined_log_text(), 'text/plain; charset=utf-8')
                    return
                if path == '/logs':
                    self._send(200, self.render_logs(query))
                    return
                if path == '/streams':
                    self._send(200, self.render_streams(query))
                    return
                if path == '/wifi':
                    self._send(200, self.render_wifi(query))
                    return
                self._send(200, self.render_home(query))

            def do_POST(self):
                path = urlparse(self.path).path
                form = self._form()
                try:
                    if path == '/save-main-stream':
                        cfg = load_config()
                        cfg['main_stream'] = {
                            'name': first(form, 'name', 'Hoofdstream'),
                            'type': first(form, 'type', 'hls'),
                            'url': first(form, 'url'),
                            'enabled': checked(form, 'enabled'),
                        }
                        save_config(cfg)
                        self._redirect('/streams?msg=Hoofdstream+opgeslagen')
                        return

                    if path == '/add-schedule':
                        cfg = load_config()
                        cfg.setdefault('schedule', [])
                        stream_type = first(form, 'stream_type', 'hls')
                        name = first(form, 'name', 'Nieuwe geplande stream')
                        url = first(form, 'url')
                        channel = first(form, 'channel')
                        if stream_type == 'twitch' and channel and not url:
                            url = f'twitch://{channel}'
                        item = {
                            'id': slug(first(form, 'id') or name),
                            'name': name,
                            'enabled': checked(form, 'enabled'),
                            'stream': {
                                'type': stream_type,
                                'url': url,
                            },
                            'months': parse_int_list(form.get('months', []), 1, 12) or list(range(1, 13)),
                            'days': form.get('days', []),
                            'time': {
                                'start': first(form, 'start', '19:00'),
                                'end': first(form, 'end', '22:00'),
                            },
                            'repeat': {
                                'type': first(form, 'repeat_type', 'weekly'),
                                'interval': int(first(form, 'repeat_interval', '1') or '1'),
                            },
                            'priority': int(first(form, 'priority', '10') or '10'),
                        }
                        if stream_type == 'twitch':
                            item['stream']['channel'] = channel or url.replace('twitch://', '')
                            item['stream']['quality'] = first(form, 'quality', '480p,360p,best')
                        if not item['days'] and item['repeat']['type'] in ('weekly', 'daily'):
                            item['days'] = ['tuesday']
                        cfg['schedule'].append(item)
                        save_config(cfg)
                        self._redirect('/streams?msg=Planning+toegevoegd')
                        return

                    if path == '/delete-schedule':
                        cfg = load_config()
                        sid = first(form, 'id')
                        cfg['schedule'] = [x for x in cfg.get('schedule', []) if x.get('id') != sid]
                        save_config(cfg)
                        self._redirect('/streams?msg=Planning+verwijderd')
                        return

                    if path == '/toggle-schedule':
                        cfg = load_config()
                        sid = first(form, 'id')
                        for item in cfg.get('schedule', []):
                            if item.get('id') == sid:
                                item['enabled'] = not bool(item.get('enabled', True))
                        save_config(cfg)
                        self._redirect('/streams?msg=Planning+bijgewerkt')
                        return

                    if path == '/wifi-connect':
                        ssid = first(form, 'ssid_manual') or first(form, 'ssid')
                        result = connect_wifi(ssid, first(form, 'password'), first(form, 'country', 'NL'))
                        logger.info('WiFi-connectie via webinterface: %s', result.get('message'))
                        msg = result.get('message', 'WiFi verwerkt')
                        self._redirect(redirect('/wifi', msg[:120]))
                        return

                    self._send(404, self.layout('Niet gevonden', '<p>Onbekende actie.</p>'))
                except Exception as exc:
                    logger.exception('Webactie mislukt')
                    self._send(500, self.layout('Fout', f'<p class="error">{esc(exc)}</p>'))

            def nav(self) -> str:
                return '<nav class="tabs"><a class="tab" href="/">Status</a><a class="tab" href="/wifi">WiFi / Network</a><a class="tab" href="/streams">Stream</a><a class="tab" href="/logs">Live Log</a><a class="tab muted" href="/api/config">JSON</a></nav>'

            def flash(self, query: Dict[str, List[str]]) -> str:
                msg = query.get('msg', [''])[0]
                return f'<div class="flash">{esc(msg)}</div>' if msg else ''

            def layout(self, title: str, content: str, query: Dict[str, List[str]] = None) -> str:
                query = query or {}
                try:
                    cfg_for_title = load_config()
                    app_title = str(cfg_for_title.get('web', {}).get('title') or 'PiViewer final')
                except Exception:
                    app_title = 'PiViewer final'
                return f'''<!doctype html>
<html lang="nl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)} - {esc(app_title)}</title>
<style>
body {{ font-family: Arial, sans-serif; margin: 0; background:#111; color:#eee; }}
header {{ background:#181818; border-bottom:1px solid #333; padding:16px 20px; position:sticky; top:0; }}
main {{ padding:20px; max-width:1100px; }}
nav.tabs {{ display:flex; gap:8px; flex-wrap:wrap; margin-top:10px; }}
nav.tabs a.tab {{ color:#eee; background:#262626; border:1px solid #444; border-radius:10px; padding:10px 14px; text-decoration:none; font-weight:bold; }}
nav.tabs a.tab:hover {{ background:#333; }}
nav.tabs a.muted {{ color:#aaa; font-weight:normal; }}
.card {{ background:#1c1c1c; border:1px solid #333; border-radius:12px; padding:18px; margin-bottom:18px; }}
h1, h2 {{ margin-top:0; }}
table {{ border-collapse: collapse; width:100%; }}
th, td {{ text-align:left; border-bottom:1px solid #333; padding:8px; vertical-align:top; }}
th {{ width:220px; color:#bbb; }}
input, select, textarea {{ width:100%; box-sizing:border-box; padding:9px; margin-top:4px; background:#101010; color:#eee; border:1px solid #444; border-radius:8px; }}
input[type=checkbox] {{ width:auto; }}
button {{ background:#2d6cdf; color:white; border:0; border-radius:8px; padding:10px 14px; cursor:pointer; margin-top:10px; }}
button.danger {{ background:#933; }}
.grid {{ display:grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap:12px; }}
.small {{ color:#aaa; font-size:0.92em; }}
.flash {{ background:#173b20; border:1px solid #2e7d32; padding:10px; border-radius:8px; margin-bottom:16px; }}
.error {{ background:#4a1616; border:1px solid #933; padding:10px; border-radius:8px; }}
.badge {{ display:inline-block; padding:4px 8px; border-radius:8px; background:#333; }}
.inline-form {{ display:inline; }}
.logbox {{ background:#050505; border:1px solid #333; border-radius:10px; padding:12px; min-height:520px; max-height:70vh; overflow:auto; white-space:pre-wrap; font-family:Consolas, Monaco, monospace; font-size:13px; line-height:1.35; }}
.statusline {{ display:flex; gap:8px; flex-wrap:wrap; align-items:center; }}
</style>
</head>
<body>
<header><h1>{esc(app_title)}</h1>{self.nav()}</header>
<main>{self.flash(query)}{content}</main>
</body>
</html>'''

            def render_home(self, query: Dict[str, List[str]]) -> str:
                s: Dict[str, Any] = state.snapshot()
                rows = ''.join(f'<tr><th>{esc(key)}</th><td>{esc(value)}</td></tr>' for key, value in s.items())
                content = f'''<section class="card"><h2>Status</h2><p><span class="badge">Automatisch vernieuwen via browser-refresh</span></p><table>{rows}</table></section>
<section class="card"><h2>Beheer</h2><p>Gebruik <b>Stream</b> om de hoofdstream en geplande streams te beheren. Gebruik <b>WiFi / Network</b> om een draadloze verbinding en netwerkstatus te beheren.</p></section>'''
                return self.layout('Status', content, query)

            def render_streams(self, query: Dict[str, List[str]]) -> str:
                cfg = load_config()
                main = cfg.get('main_stream', {})
                schedule = cfg.get('schedule', [])
                schedule_rows = ''
                for item in schedule:
                    stream = item.get('stream', {})
                    days = ', '.join(item.get('days', []))
                    months = ','.join(str(x) for x in item.get('months', []))
                    tm = item.get('time', {})
                    rep = item.get('repeat', {})
                    schedule_rows += f'''<tr>
<td><b>{esc(item.get('name'))}</b><br><span class="small">{esc(item.get('id'))}</span></td>
<td>{esc(stream.get('type'))}<br><span class="small">{esc(stream.get('url'))}</span></td>
<td>{esc(days)}<br><span class="small">maanden: {esc(months)}</span></td>
<td>{esc(tm.get('start'))} - {esc(tm.get('end'))}<br><span class="small">{esc(rep.get('type'))} / {esc(rep.get('interval'))}</span></td>
<td>{'aan' if item.get('enabled', True) else 'uit'}</td>
<td>
<form class="inline-form" method="post" action="/toggle-schedule"><input type="hidden" name="id" value="{esc(item.get('id'))}"><button>aan/uit</button></form>
<form class="inline-form" method="post" action="/delete-schedule"><input type="hidden" name="id" value="{esc(item.get('id'))}"><button class="danger">verwijder</button></form>
</td>
</tr>'''
                if not schedule_rows:
                    schedule_rows = '<tr><td colspan="6">Geen geplande streams.</td></tr>'

                day_checks = ''.join(f'<label><input type="checkbox" name="days" value="{value}"> {label}</label><br>' for value, label in DAY_OPTIONS)
                month_checks = ''.join(f'<label><input type="checkbox" name="months" value="{nr}" checked> {label}</label><br>' for nr, label in MONTH_OPTIONS)
                content = f'''<section class="card"><h2>Hoofdstream</h2>
<p class="small">Deze HLS-stream draait altijd, behalve wanneer er een actieve planning is of een USB-slideshow gevonden wordt.</p>
<form method="post" action="/save-main-stream">
<div class="grid"><label>Naam<input name="name" value="{esc(main.get('name', 'RTV Meppel'))}"></label>
<label>Type<select name="type"><option value="hls" {'selected' if main.get('type') == 'hls' else ''}>HLS</option></select></label>
<label>URL<input name="url" value="{esc(main.get('url', ''))}"></label>
<label><input type="checkbox" name="enabled" checked> Ingeschakeld</label></div>
<button>Hoofdstream opslaan</button></form></section>

<section class="card"><h2>Geplande streams</h2>
<table><tr><th>Naam</th><th>Stream</th><th>Dagen/maanden</th><th>Tijd/herhaling</th><th>Status</th><th>Actie</th></tr>{schedule_rows}</table></section>

<section class="card"><h2>Nieuwe planning toevoegen</h2>
<form method="post" action="/add-schedule">
<div class="grid">
<label>Naam<input name="name" value="Twitch Richard841116 dinsdagavond"></label>
<label>ID optioneel<input name="id" placeholder="automatisch"></label>
<label>Streamtype<select name="stream_type"><option value="hls">HLS</option><option value="twitch" selected>Twitch</option></select></label>
<label>URL<input name="url" value="twitch://richard841116"></label>
<label>Twitch kanaal<input name="channel" value="richard841116"></label>
<label>Twitch kwaliteit<input name="quality" value="480p,360p,best"></label>
<label>Starttijd<input name="start" value="19:00"></label>
<label>Eindtijd<input name="end" value="22:00"></label>
<label>Herhaling<select name="repeat_type"><option value="weekly" selected>Wekelijks</option><option value="daily">Dagelijks</option><option value="monthly">Maandelijks</option><option value="once">Eenmalig</option></select></label>
<label>Interval<input name="repeat_interval" value="1"></label>
<label>Prioriteit<input name="priority" value="10"></label>
<label><input type="checkbox" name="enabled" checked> Ingeschakeld</label>
</div>
<h3>Dagen</h3>{day_checks}
<h3>Maanden</h3><div class="grid">{month_checks}</div>
<button>Planning toevoegen</button>
</form></section>'''
                return self.layout('Stream', content, query)

            def render_logs(self, query: Dict[str, List[str]]) -> str:
                current = esc(combined_log_text())
                content = f'''<section class="card"><h2>Live Log</h2>
<div class="statusline"><span class="badge">ververst iedere 5 seconden op de achtergrond</span><a class="badge" href="/api/live-log">open als tekst</a></div>
<p class="small">Hier zie je live wat PiViewer doet: opstart, USB, WiFi, auto-update, bronkeuze, streamstart en fouten.</p>
<pre id="logbox" class="logbox">{current}</pre>
<script>
async function refreshLog() {{
  try {{
    const r = await fetch('/api/live-log?ts=' + Date.now());
    const t = await r.text();
    const box = document.getElementById('logbox');
    const nearBottom = box.scrollTop + box.clientHeight >= box.scrollHeight - 40;
    box.textContent = t;
    if (nearBottom) box.scrollTop = box.scrollHeight;
  }} catch(e) {{}}
}}
setInterval(refreshLog, 5000);
setTimeout(() => {{ const box = document.getElementById('logbox'); box.scrollTop = box.scrollHeight; }}, 100);
</script>
</section>'''
                return self.layout('Live Log', content, query)

            def render_wifi(self, query: Dict[str, List[str]]) -> str:
                status = wifi_status()
                rows = ''.join(f'<tr><th>{esc(k)}</th><td>{esc(v)}</td></tr>' for k, v in status.items())
                networks = scan_wifi()
                options = ''.join(f'<option value="{esc(n)}">{esc(n)}</option>' for n in networks)
                if not options:
                    options = '<option value="">Geen netwerken gevonden of scan niet beschikbaar</option>'
                content = f'''<section class="card"><h2>WiFi / Network-status</h2><table>{rows}</table></section>
<section class="card"><h2>WiFi verbinden</h2>
<p class="small">De PiViewer-service draait als root, zodat de webinterface WiFi kan instellen. Gebruik dit alleen op je eigen lokale netwerk.</p>
<form method="post" action="/wifi-connect">
<div class="grid">
<label>Gevonden netwerk<select name="ssid">{options}</select></label>
<label>Of SSID handmatig<input name="ssid_manual" oninput="document.querySelector('[name=ssid]').value=this.value" placeholder="Netwerknaam"></label>
<label>WiFi-wachtwoord<input type="password" name="password" autocomplete="new-password"></label>
<label>Landcode<input name="country" value="NL"></label>
</div>
<button>Verbinden</button>
</form>
<p class="small">Na verbinden kan het IP-adres wijzigen. Open daarna opnieuw de webinterface op het nieuwe IP-adres.</p>
</section>'''
                return self.layout('WiFi / Network', content, query)

        self.server = ThreadingHTTPServer((self.host, self.port), Handler)
        thread = Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        logger.info('Webinterface gestart op http://%s:%s', self.host, self.port)

    def stop(self) -> None:
        if self.server:
            self.server.shutdown()
