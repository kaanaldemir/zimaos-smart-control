import base64
import hmac
import json
import os
import socket
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from miio import Device


HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "8099"))
BASE_PATH = os.environ.get("BASE_PATH", "/devices").rstrip("/")
API_BASE_PATH = os.environ.get("API_BASE_PATH", "/devices-api").rstrip("/")
UI_USERNAME = os.environ.get("UI_USERNAME", "").strip()
UI_PASSWORD = os.environ.get("UI_PASSWORD", "").strip()

# Server-side only. These values are never rendered into HTML or JavaScript.
WIZ_LIGHT_IP = os.environ.get("WIZ_LIGHT_IP", "192.168.1.149")
WIZ_LIGHT_PORT = int(os.environ.get("WIZ_LIGHT_PORT", "38899"))
XIAOMI_PLUG_IP = os.environ.get("XIAOMI_PLUG_IP", "192.168.1.207")
XIAOMI_TOKEN = os.environ.get("XIAOMI_TOKEN", "PUT_32_CHAR_XIAOMI_TOKEN_HERE").strip()
XIAOMI_MODE = os.environ.get("XIAOMI_MODE", "miot").strip().lower()
XIAOMI_TIMEOUT = int(os.environ.get("XIAOMI_TIMEOUT", "2"))

# Common MIOT outlet mapping. Override in compose if your exact model differs.
XIAOMI_SWITCH_SIID = int(os.environ.get("XIAOMI_SWITCH_SIID", "2"))
XIAOMI_SWITCH_PIID = int(os.environ.get("XIAOMI_SWITCH_PIID", "1"))
XIAOMI_POWER_PROPS = json.loads(
    os.environ.get(
        "XIAOMI_POWER_PROPS",
        '[["energy_kwh",11,1],["power_w",11,2]]',
    )
)

DEVICES = {
    "wiz-light": {"id": "wiz-light", "name": "WiZ light", "kind": "light"},
    "xiaomi-plug": {"id": "xiaomi-plug", "name": "Xiaomi Smart Plug 2", "kind": "plug"},
}


def strip_base_path(path):
    if API_BASE_PATH and path == API_BASE_PATH:
        return "/api"
    if API_BASE_PATH and path.startswith(API_BASE_PATH + "/"):
        return "/api" + path[len(API_BASE_PATH) :]
    if BASE_PATH and path == BASE_PATH:
        return "/"
    if BASE_PATH and path.startswith(BASE_PATH + "/"):
        return path[len(BASE_PATH) :]
    return path


def auth_enabled():
    return bool(UI_USERNAME and UI_PASSWORD)


def auth_ok(header):
    if not auth_enabled():
        return True
    if not header or not header.startswith("Basic "):
        return False
    try:
        decoded = base64.b64decode(header[6:], validate=True).decode("utf-8")
        username, password = decoded.split(":", 1)
    except Exception:
        return False
    return hmac.compare_digest(username, UI_USERNAME) and hmac.compare_digest(password, UI_PASSWORD)


def wiz_request(method, params=None, timeout=2.0):
    payload = json.dumps({"method": method, "params": params or {}}, separators=(",", ":")).encode()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(timeout)
    try:
        sock.sendto(payload, (WIZ_LIGHT_IP, WIZ_LIGHT_PORT))
        data, _ = sock.recvfrom(4096)
        return json.loads(data.decode("utf-8"))
    finally:
        sock.close()


def wiz_state():
    result = wiz_request("getPilot").get("result", {})
    return {
        **DEVICES["wiz-light"],
        "online": True,
        "on": bool(result.get("state")),
        "brightness": result.get("dimming"),
        "power_w": None,
        "raw": result,
    }


def wiz_set(enabled):
    result = wiz_request("setPilot", {"state": bool(enabled)})
    return {"ok": True, "device": "wiz-light", "on": bool(enabled), "raw": result}


def require_xiaomi_token():
    if len(XIAOMI_TOKEN) != 32 or "PUT_32_CHAR" in XIAOMI_TOKEN:
        raise RuntimeError("XIAOMI_TOKEN is not configured on the server")


def xiaomi_device():
    require_xiaomi_token()
    return Device(XIAOMI_PLUG_IP, XIAOMI_TOKEN, lazy_discover=True, timeout=XIAOMI_TIMEOUT)


def xiaomi_miot_props(dev):
    props = [{"did": "switch", "siid": XIAOMI_SWITCH_SIID, "piid": XIAOMI_SWITCH_PIID}]
    props.extend({"did": name, "siid": siid, "piid": piid} for name, siid, piid in XIAOMI_POWER_PROPS)
    values = dev.send("get_properties", props)
    by_name = {}
    if isinstance(values, list):
        for item in values:
            if isinstance(item, dict) and item.get("code", 0) == 0:
                by_name[item.get("did")] = item.get("value")
    return values, by_name


def xiaomi_state():
    dev = xiaomi_device()
    if XIAOMI_MODE == "legacy":
        values = dev.send("get_prop", ["power", "temperature"])
        return {
            **DEVICES["xiaomi-plug"],
            "online": True,
            "on": bool(values and values[0] in (True, "on")),
            "temperature_c": values[1] if isinstance(values, list) and len(values) > 1 else None,
            "power_w": None,
            "raw": values,
        }

    raw, props = xiaomi_miot_props(dev)
    return {
        **DEVICES["xiaomi-plug"],
        "online": True,
        "on": bool(props.get("switch")),
        "power_w": props.get("power_w"),
        "current_a": props.get("current_a"),
        "voltage_v": props.get("voltage_v"),
        "energy_kwh": props.get("energy_kwh"),
        "raw": raw,
    }


def xiaomi_set(enabled):
    dev = xiaomi_device()
    if XIAOMI_MODE == "legacy":
        raw = dev.send("set_power", ["on" if enabled else "off"])
    else:
        raw = dev.send(
            "set_properties",
            [{"did": "switch", "siid": XIAOMI_SWITCH_SIID, "piid": XIAOMI_SWITCH_PIID, "value": bool(enabled)}],
        )
    return {"ok": True, "device": "xiaomi-plug", "on": bool(enabled), "raw": raw}


def state_for(device_id):
    if device_id == "wiz-light":
        return wiz_state()
    if device_id == "xiaomi-plug":
        return xiaomi_state()
    raise KeyError(device_id)


def set_device(device_id, enabled):
    if device_id == "wiz-light":
        return wiz_set(enabled)
    if device_id == "xiaomi-plug":
        return xiaomi_set(enabled)
    raise KeyError(device_id)


def safe_state(device_id):
    try:
        return state_for(device_id)
    except Exception as exc:
        return {**DEVICES[device_id], "online": False, "error": str(exc)}


def json_response(handler, status, body):
    encoded = json.dumps(body, indent=2).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Content-Length", str(len(encoded)))
    handler.end_headers()
    handler.wfile.write(encoded)


def html_response(handler, status, body):
    encoded = body.encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "text/html; charset=utf-8")
    handler.send_header("Content-Length", str(len(encoded)))
    handler.end_headers()
    handler.wfile.write(encoded)


def auth_response(handler):
    handler.send_response(401)
    handler.send_header("WWW-Authenticate", 'Basic realm="Smart Control"')
    handler.send_header("Content-Length", "0")
    handler.end_headers()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print("%s - %s" % (self.address_string(), fmt % args), flush=True)

    def do_GET(self):
        self.route()

    def do_POST(self):
        self.route()

    def route(self):
        if not auth_ok(self.headers.get("Authorization")):
            auth_response(self)
            return

        path = strip_base_path(urlparse(self.path).path.rstrip("/") or "/")
        parts = [part for part in path.split("/") if part]
        try:
            if path == "/":
                html_response(self, 200, HTML)
                return
            if path == "/api/state":
                json_response(self, 200, {"devices": [safe_state(device_id) for device_id in DEVICES]})
                return
            if len(parts) == 4 and parts[:2] == ["api", "device"] and parts[2] in DEVICES:
                action = parts[3]
                if action == "state":
                    json_response(self, 200, state_for(parts[2]))
                    return
                if action in ("on", "off", "toggle"):
                    enabled = action == "on"
                    if action == "toggle":
                        enabled = not bool(state_for(parts[2]).get("on"))
                    json_response(self, 200, set_device(parts[2], enabled))
                    return
            json_response(self, 404, {"error": "not found"})
        except Exception as exc:
            json_response(self, 500, {"error": str(exc)})


HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Smart Control</title>
  <style>
    :root { color-scheme: dark; font-family: Inter, ui-sans-serif, system-ui, sans-serif; background: #0f1216; color: #eef2f5; }
    * { box-sizing: border-box; }
    body { margin: 0; min-height: 100vh; background: #0f1216; }
    main { width: min(900px, calc(100vw - 28px)); margin: 0 auto; padding: 28px 0; }
    header { display: flex; justify-content: space-between; gap: 16px; align-items: end; margin-bottom: 18px; }
    h1 { font-size: 24px; line-height: 1.2; margin: 0; letter-spacing: 0; }
    #updated { color: #9aa6b2; font-size: 13px; }
    .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 14px; }
    .device { border: 1px solid #2b3641; border-radius: 8px; background: #171d23; padding: 16px; }
    .top { display: flex; justify-content: space-between; gap: 12px; align-items: center; margin-bottom: 14px; }
    .name { font-size: 18px; font-weight: 650; }
    .badge { min-width: 66px; text-align: center; border-radius: 999px; padding: 5px 9px; font-size: 12px; background: #303942; color: #d9e2ea; }
    .badge.on { background: #1d6f55; color: white; }
    .badge.offline { background: #693132; color: white; }
    .metrics { display: grid; grid-template-columns: repeat(2, 1fr); gap: 8px; margin-bottom: 14px; }
    .metric { border: 1px solid #27313b; border-radius: 6px; padding: 10px; min-height: 62px; }
    .label { display: block; color: #9aa6b2; font-size: 12px; margin-bottom: 5px; }
    .value { font-size: 18px; font-weight: 620; }
    .actions { display: grid; grid-template-columns: repeat(2, 1fr); gap: 8px; }
    button { height: 42px; border: 1px solid #3a4651; border-radius: 7px; background: #222b33; color: inherit; font: inherit; cursor: pointer; }
    button:hover { background: #2d3842; }
    button:disabled { opacity: .45; cursor: default; }
    .error { color: #ffb4a9; font-size: 13px; margin-top: 10px; overflow-wrap: anywhere; }
  </style>
</head>
<body>
  <main>
    <header>
      <h1>Smart Control</h1>
      <div id="updated">Loading</div>
    </header>
    <section class="grid" id="devices"></section>
  </main>
  <script>
    const root = document.getElementById('devices');
    const updated = document.getElementById('updated');

    function text(value, suffix = '') {
      if (value === null || value === undefined || value === '') return 'n/a';
      return `${value}${suffix}`;
    }

    function metric(label, value) {
      return `<div class="metric"><span class="label">${label}</span><span class="value">${value}</span></div>`;
    }

    function metricsFor(device) {
      const state = metric('State', device.online ? (device.on ? 'On' : 'Off') : 'Offline');
      if (device.kind === 'light') {
        return [
          state,
          metric('Brightness', text(device.brightness, '%'))
        ].join('');
      }
      return [
        state,
        metric('Power Draw', text(device.power_w, ' W')),
        metric('Energy', text(device.energy_kwh, ' kWh'))
      ].join('');
    }

    function render(devices) {
      root.innerHTML = devices.map((device) => {
        const status = !device.online ? 'offline' : device.on ? 'on' : 'off';
        const metrics = metricsFor(device);
        return `
          <article class="device">
            <div class="top">
              <div class="name">${device.name}</div>
              <div class="badge ${status}">${status}</div>
            </div>
            <div class="metrics">${metrics}</div>
            <div class="actions">
              <button onclick="act('${device.id}', 'on')" ${device.online ? '' : 'disabled'}>On</button>
              <button onclick="act('${device.id}', 'off')" ${device.online ? '' : 'disabled'}>Off</button>
            </div>
            ${device.error ? `<div class="error">${device.error}</div>` : ''}
          </article>`;
      }).join('');
      updated.textContent = `Updated ${new Date().toLocaleTimeString()}`;
    }

    async function refresh() {
      try {
        const basePath = window.location.pathname.replace(/\\/$/, '');
        const apiPath = basePath && basePath !== '/' ? `${basePath}/api/state` : '/api/state';
        const response = await fetch(apiPath, { cache: 'no-store' });
        render((await response.json()).devices || []);
      } catch (error) {
        updated.textContent = error.message;
      }
    }

    async function act(id, action) {
      const basePath = window.location.pathname.replace(/\\/$/, '');
      const apiPath = basePath && basePath !== '/' ? `${basePath}/api/device/${id}/${action}` : `/api/device/${id}/${action}`;
      await fetch(apiPath, { method: 'POST', cache: 'no-store' });
      await refresh();
    }

    refresh();
    setInterval(refresh, 3000);
  </script>
</body>
</html>
"""


if __name__ == "__main__":
    print(f"Listening on http://{HOST}:{PORT}", flush=True)
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
