# Deploying the live panel

Two options. The first is the real one.

## A. On helppox (LIVE), public through a Cloudflare tunnel

The panel is one Python process: `tools/dev_server.py` serves `web/` and `artifacts/` and answers `/api/state`. It reads the rooms now from Home Assistant (LIVE): `HA_URL` on the LAN first, then `HA_URL_EXT` (the Nabu Casa custom domain), so the box does not need to be in the house. Without either it reads only outdoor now (LIVE OUTDOOR). A Cloudflare tunnel gives a public HTTPS URL without opening a port on the router. Home Assistant itself is never exposed: the server only reads it.

Needs: Python 3.10+, numpy, certifi, git, cloudflared. No torch on the deploy box; the fits are in `artifacts/` already.

The prompt for OpenClaw is in [OPENCLAW_DEPLOY_PROMPT.md](OPENCLAW_DEPLOY_PROMPT.md).

To update after a new run on the PC: commit and push `artifacts/` and `web/`, then on the box `git pull` and `sudo systemctl restart kayra-panel`.

## B. Vercel (REPLAY only, optional mirror)

It serves the static panel and `api/state.py` replays the recorded history, labelled REPLAY. (It could read Home Assistant through `HA_URL_EXT` too, but that puts the HA token on a third-party host; option A keeps it on your own machine.)

1. `python tools/build_web.py` (copies artifacts into `web/artifacts/`), commit, push.
2. vercel.com, sign in with GitHub, Import `apn201/kayra`, framework "Other", no build command, output directory `web`. Deploy.

`vercel.json` already sets this.
