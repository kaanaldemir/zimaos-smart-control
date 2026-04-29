# ZimaOS Smart Control

Tiny standalone web UI for:

- WiZ light at `192.168.1.149`
- Xiaomi Smart Plug 2 at `192.168.1.207`

It is meant to run as a small ZimaOS/CasaOS app and be exposed through Nginx Proxy Manager at:

```text
https://kaanaldemir.com/devices
```

The container stays idle until the page is opened. There is no database, scheduler, or background polling loop.

When the page is open, it polls devices separately instead of in one burst:

- Xiaomi plug: every 3 seconds
- WiZ light: every 7 seconds, offset from the plug polling

The WiZ local UDP API can become flaky if it is polled too aggressively, so the bulb is intentionally queried more gently than the plug.

## Install On ZimaOS

Use the compose YAML in this repo as the app package:

```text
https://raw.githubusercontent.com/kaanaldemir/zimaos-smart-control/main/docker-compose.yml
```

App icon:

```text
https://raw.githubusercontent.com/kaanaldemir/zimaos-smart-control/main/assets/icon.png
```

Set these environment variables in ZimaOS:

```sh
XIAOMI_TOKEN=your_32_character_token
UI_USERNAME=
UI_PASSWORD=
```

`XIAOMI_TOKEN` is only read by the server. It is not rendered into HTML, JavaScript, or API responses.

## Nginx Proxy Manager

Add a custom location on your existing `kaanaldemir.com` proxy host:

```text
Location: /devices
Scheme: http
Forward Hostname / IP: 192.168.1.219
Forward Port: 8099
```

Recommended:

```text
Block Common Exploits: on
Access List: enabled
```

If you use app-level auth instead of an NPM access list, set `UI_USERNAME` and `UI_PASSWORD`.

## Local Direct Access

The app also works directly:

```text
http://192.168.1.219:8099/
http://192.168.1.219:8099/devices
```

## API

```text
GET  /devices/api/state
GET  /devices/api/device/wiz-light/state
POST /devices/api/device/wiz-light/on
POST /devices/api/device/wiz-light/off
POST /devices/api/device/wiz-light/toggle
GET  /devices/api/device/xiaomi-plug/state
POST /devices/api/device/xiaomi-plug/on
POST /devices/api/device/xiaomi-plug/off
POST /devices/api/device/xiaomi-plug/toggle
```

Direct `/api/...` endpoints also work on port `8099`.

## Build

Images are published to:

```text
ghcr.io/kaanaldemir/zimaos-smart-control:latest
```

The repo includes a GitHub Actions workflow that builds and pushes this image on every push to `main`.

## Xiaomi Model Mapping

The detected plug is:

```text
Name: Xiaomi Akilli Fis
Model: cuco.plug.v2eur
IP: 192.168.1.207
```

Power state:

```text
siid=2, piid=1
```

Energy and power draw:

```text
energy_kwh: siid=11, piid=1
power_w:    siid=11, piid=2
```

Override if needed:

```yaml
XIAOMI_POWER_PROPS: '[["energy_kwh",11,1],["power_w",11,2]]'
```
