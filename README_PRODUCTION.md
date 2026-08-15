Production deployment notes

1) Prepare system (recommended: Ubuntu/Debian)

  - Install Python 3.9+ and venv: `apt install python3 python3-venv python3-pip`
  - Install nginx if using a reverse proxy: `apt install nginx`

2) Run the setup script

  - For a system-wide install (creates venv under `/opt/hmbot`):

```bash
sudo ./scripts/setup_prod.sh
```

  - For a user-local install (venv in repository):

```bash
./scripts/setup_prod.sh
```

3) Edit configuration

- Update `config/settings.json` from `config/settings.dist.json` to configure `dry_run`, `mt5` and other options.
- Put secrets either in `/etc/default/hmbot` (system-wide) or in `.env` in the repo (user install).

4) Systemd service (system-wide)

  - Copy the template to systemd and start it (requires root):

```bash
sudo cp deploy/hmbot.service /etc/systemd/system/hmbot.service
sudo systemctl daemon-reload
sudo systemctl enable --now hmbot.service
sudo journalctl -u hmbot -f
```

5) Nginx (optional reverse proxy, then add SSL via certbot)

  - Copy `deploy/nginx_hmbot.conf` to `/etc/nginx/sites-available/hmbot` then enable and reload nginx.

6) Email self-service for the admin URL (optional)

Send a mail from the owner address to itself and the bot replies with a
dashboard-styled email containing the owner control URL:

- First email: anything works — you get your link and a random *access word*.
- Later emails: the subject must contain the current access word to generate a
  NEW link (the old one is burned immediately). Emails without it get a status
  reply with your current link and word.
- The bot's replies are never reprocessed (marked `X-HM-Bot-Auto: 1`).
- Forgot the word? Run `python -m utils.admin status` to see it.

Configuration (env vars, see `mailadmin/watcher.py` for defaults):

- `HMBOT_MAIL_DIR`      — Maildir for the owner (default `/home/hm/mail/headmaster.fun/hm`)
- `HMBOT_OWNER_MAIL`    — owner address (default `hm@headmaster.fun`)
- `HMBOT_PUBLIC_BASE`   — public base URL used in replies (default `https://tradebot.headmaster.fun`)
- `HMBOT_SENDMAIL`      — MTA binary (default `/usr/sbin/sendmail`)
- `HMBOT_MAIL_POLL_SECONDS` — polling interval (default `5`)

Requires the service to run as a user with read/write access to the Maildir
and permission to pipe into `sendmail`.

6b) MT5 remote bridge (Linux server + Windows desktop)

The server runs Linux, so the official MetaTrader5 package (Windows-only) can
never run there. Instead, the server bot talks to MetaTrader 5 running on your
Windows desktop through the **HM Bridge**:

```
Desktop (Windows)  <--wss/https-->  tradebot.headmaster.fun/bridge/ws  <-->  server bot
   MT5 terminal + bridge_agent.py                                        (RemoteMT5 proxy)
```

- The desktop agent (`bridge_agent.py`, included in the repo/zip) starts next
  to MetaTrader 5, logs into your account and connects **out** to the bridge
  endpoint — no port forwarding or public IP needed.
- The server bot keeps running in the browser exactly as before; MT5 calls are
  proxied to the desktop agent over the authenticated WebSocket.

Server side:

- Set `HM_BRIDGE_TOKEN` in `/etc/default/hmbot` (a long random token; the
  server refuses to start a bridge session without it).
- In `config/settings.json` add:

```json
"mt5_bridge": {
  "enabled": true,
  "url": "wss://tradebot.headmaster.fun/bridge/ws",
  "token": ""
}
```

  (`token` can stay empty — the env var is used. Leaving `enabled: false`
  keeps the usual simulation feed.)

Desktop side (Windows) — easy path (no Python for users):

1. Run `HMBotBridgeAgent-Setup.exe` (built once with `build_win.bat`, or
   downloaded from the GitHub Actions artifact).
2. The installer shows a branded welcome screen, installs to
   `%LOCALAPPDATA%\Programs\HM Bridge Agent` (no admin rights needed) and can
   register the agent to start automatically with Windows.
3. The app opens with a splash screen, then **auto-detects** the installed
   MetaTrader 5 terminal (running process, registry, common folders) and
   shows it in the MT5 field.
4. Press **Start agent** — that's all. The token and server URL are already
   pre-filled (baked in at build time). The green dot confirms the link.

Building the installer (seller's PC, once):

```bat
build_win.bat
```

This one command installs Python + Inno Setup automatically (winget), builds
`HM_Bridge_Agent.exe` with PyInstaller and compiles
`dist\HMBotBridgeAgent-Setup.exe`. Set `HM_BRIDGE_URL` / `HM_BRIDGE_TOKEN`
first to bake a different server link into the exe. A GitHub Actions workflow
(`.github/workflows/build_windows.yml`) builds the same installer in the
cloud without any Windows machine.

Manual/development path:

1. Install MetaTrader 5 and log into your account.
2. `pip install websocket-client MetaTrader5 numpy`
3. `python bridge_agent.py --token <token>` (or run `python agent_app.py` for the GUI).

Only one desktop agent may be attached at a time — a second connection is
rejected with a "busy" error. With no agent attached the bot fails fast and
reports "bridge not connected" instead of stalling.

7) Security & notes

- Keep your `_SIGNING_KEY` from `utils/license.py` secret.
- Keep `HM_WEB3_API_KEY`, `HM_TELEGRAM_BOT_TOKEN`, and `HM_MT5_PASSWORD` in environment variables, not in `settings.json`.
- Rotating the admin URL (via the mail feature) burns the old link — good hygiene if a link ever leaks.
- Test thoroughly in `dry_run` on a demo MT5 account before switching to live trading.
