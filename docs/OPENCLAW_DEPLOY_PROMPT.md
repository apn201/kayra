# Prompt for OpenClaw: deploy the Käyrä panel on helppox

Copy everything below the line into OpenClaw. Replace the two values in angle brackets before sending, or give them to OpenClaw separately. Never paste the Home Assistant token into a chat log you keep.

---

Deploy the Käyrä panel on this machine (helppox) as a read-only web service with a public HTTPS URL.

Rules for this job:
- Paste the raw output of every command you run: `ls -la`, `git log -1`, `systemctl status`, `curl` responses. No summaries in place of output. If a command fails, paste the error and stop. Do not report a step as done without its output.
- Never print the Home Assistant token. `.env` gets `chmod 600`.
- Read-only: nothing here writes to Home Assistant.
- Do not touch other services on this machine. If port 8201 is taken, stop and tell me.
- The panel is public. It must never expose Home Assistant itself: it only reads six sensor states server-side and serves JSON.

Steps:

1. Prerequisites. Show `python3 --version`, `git --version`. Python must be 3.10 or newer. Install `git`, `python3-venv` if missing (apt), and show the versions again.

2. Clone and set up, as a normal user, not root:
   ```
   cd ~ && git clone https://github.com/apn201/kayra.git && cd kayra && git log -1 --oneline
   python3 -m venv .venv
   .venv/bin/pip install numpy certifi
   .venv/bin/python -c "import numpy, certifi; print(numpy.__version__)"
   ```
   Do not install torch. The deploy box only serves results.

3. Create `~/kayra/.env` with exactly these two lines, then `chmod 600 .env` and show `ls -la .env` (not its contents). This machine is not on the Home Assistant LAN, so it uses the external (Nabu Casa custom domain) URL:
   ```
   HA_URL_EXT=https://ha.juhalilja.com
   HA_TOKEN=<a long-lived token made for Käyrä only>
   ```
   No language-model key goes on this machine. The server only serves results and reads Home Assistant.

4. Test live mode once and paste the output:
   ```
   .venv/bin/python -m kayra.live
   ```
   Expected: `"data": "LIVE"` with three rooms that have `measured_c` values. `"LIVE OUTDOOR"` means Home Assistant was not reachable or the token is wrong; fix that before going on.

5. systemd service `/etc/systemd/system/kayra-panel.service`:
   ```
   [Unit]
   Description=Käyrä panel (read-only)
   After=network-online.target
   Wants=network-online.target

   [Service]
   User=<the user that owns ~/kayra>
   WorkingDirectory=/home/<that user>/kayra
   ExecStart=/home/<that user>/kayra/.venv/bin/python tools/dev_server.py 8201 --host 127.0.0.1
   Restart=always
   RestartSec=5
   Nice=10

   [Install]
   WantedBy=multi-user.target
   ```
   Then `sudo systemctl daemon-reload && sudo systemctl enable --now kayra-panel` and paste `systemctl status kayra-panel --no-pager` and `curl -s localhost:8201/api/state | head -c 400`.

6. Public URL with a Cloudflare tunnel. Install `cloudflared` from Cloudflare's own package repository. First a quick test:
   ```
   cloudflared tunnel --url http://127.0.0.1:8201
   ```
   Paste the `https://...trycloudflare.com` line and `curl -s <that URL>/api/state | head -c 200` from the machine. A quick tunnel URL changes on restart, so after the test make it permanent: if I have a Cloudflare account and domain, create a named tunnel to `kayra.<my domain>` and run it as a service (`cloudflared service install`). If I have no account, run the quick tunnel as a systemd service and tell me the URL after every restart. Ask me which before doing it.

7. Report: the public URL, `systemctl status` of both services, and the output of `curl -s <public URL>/api/state | head -c 400` showing `"data": "LIVE"`.

Updating later: `cd ~/kayra && git pull && sudo systemctl restart kayra-panel`, paste `git log -1 --oneline`.
