# HM Bot Trader

Professional MetaTrader 5 automation with a modern dark **web dashboard**
(runs in your browser, localhost only), built around the
**RSI(14) + EMA(48) + EMA(50)** stack.

## Strategy

Indicator window (exact MT5 apply-to chain):

| Layer | Setting | Apply to |
|-------|---------|----------|
| RSI | Period **14**, Close | Price |
| EMA #1 | Period **48**, Exponential, **Yellow** | First indicator (RSI) |
| EMA #2 | Period **50**, Exponential, **Black** | Previous indicator (EMA 48) |

Levels: `0 · 15 · 30 · 39 · 50 · 63 · 70 · 85 · 100`

**BUY** — EMA48 crosses above EMA50 **and** RSI > 50 **and** no open BUY  
**SELL** — EMA48 crosses below EMA50 **and** RSI < 50 **and** no open SELL

Indicators are calculated the MetaTrader way (Wilder RSI + MT5 EMA seed).

## Features

- **Browser dashboard** — modern dark UI with live candlestick + RSI charts,
  illustrations, signal card, positions, history, backtest, settings and logs
- Live / **dry-run (paper)** trading
- Risk gates: daily profit target, loss limit, max trades, cooldown, spread filter, session hours
- Reverse-signal auto close
- SQLite trade history + CSV export
- Confidence score (0–100%)
- Adaptive risk % position sizing (optional)
- Strategy replay / backtest
- Visual entry/exit markers on the price chart
- Plugin-ready strategy base class
- Optional Telegram notifications
- Runs on your local machine only (`127.0.0.1`) — no cloud, no external server

## Activation & one-time license

The bot uses a **one-time $20 activation** model. A new user cannot start the bot
until they activate:

1. First launch opens the dashboard to an **activation screen** showing the price.
2. The user pays the one-time fee (your `PAYMENT_URL` — Stripe, PayPal, Gumroad, …).
3. After payment, you send them a **license key**.
4. They paste the key into the dashboard once — the bot unlocks permanently.

The key is validated **locally** (no internet, no account needed) and stored on the
user's machine in `license.json` under their user-data folder. It never expires, so
reinstallation doesn't require a second payment — they re-enter the same key.

### Developer: generate & check keys

```powershell
python -m utils.license --generate              # print one key
python -m utils.license --generate --count 5    # print several
python -m utils.license --check HM-XXXX-…       # verify a key
```

Issuing keys is manual: collect the $20 via your payment link, then run
`--generate` and email the printed key to the customer.

### Developer: configure pricing / payment link

Edit `utils/license.py`:

- `PRICE` / `CURRENCY` — displayed on the activation screen (default `20.0` / `USD`).
- `PAYMENT_URL` — your payment page. When empty, the screen tells users to contact
  you for a key after paying.
- `_SIGNING_KEY` — the signing secret. **Keep it private and never change it after
  you start selling keys** — changing it invalidates every key you already issued.

Dev convenience: set the environment variable `HM_LICENSE_KEY` to a valid key to
activate without writing a file (e.g. for tests or your own install).

### Developer: accept crypto payments (BTC / USDT-TRC20)

The bot can generate a fresh Bitcoin and USDT (TRC-20) deposit address per buyer
using the [HMPyWeb3Kit](https://hmweb3.simply-web.tech/docs) wallet API:

```powershell
python -m utils.hmweb3 pay            # generate a BTC + USDT (TRC-20) address pair
python -m utils.hmweb3 generate --chain btc
python -m utils.hmweb3 balance --chain btc --address <addr>   # confirm funds arrived
python -m utils.hmweb3 status         # check connectivity / API key
```

Flow: run `pay`, give the buyer one of the two addresses, then poll `balance`
until the transfer lands — after that issue the license key as usual. The
activation screen in the dashboard also shows a deposit-address pair with a
"Check payment" button when the payment API is reachable; it falls back to the
manual flow otherwise.

The API key is read from the `HM_WEB3_API_KEY` environment variable — there is
no key embedded in the code. **Never hard-code a key inside a shared .exe** —
anyone who can open the app could read it and drain derived wallets.

### What is enforced

- The dashboard UI shows the activation gate until a valid key is entered.
- The server also blocks the `start` command until activated (defense in depth).
- Backtest / settings / logs remain usable once the dashboard is open.

## Requirements

- **Windows** (recommended) with **MetaTrader 5** installed for live trading
- Python **3.9+** (3.12/3.13 recommended)
- Packages in `requirements.txt`

## Installation

```powershell
git clone https://github.com/Timikid18/trader-bot.git
cd trader-bot
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Configure

Copy the template and edit your local settings:

```powershell
copy config\settings.dist.json config\settings.json
```

Then edit `config/settings.json`:

```json
{
  "symbol": "Crash 500 Index",
  "lot_size": 0.2,
  "dry_run": true,
  "daily_profit_target": 50,
  "daily_loss_limit": 30,
  "mt5": {
    "path": "",
    "login": 0,
    "password": "",
    "server": ""
  }
}
```

Tips:

1. Keep `"dry_run": true` until you have verified signals on a **demo** account.
2. Live trading requires `"stop_loss_points"` > 0.
3. Set `mt5.path` to your `terminal64.exe` if auto-detect fails.
4. Symbol name must match MT5 Market Watch exactly.

## Connect MT5

1. Open MetaTrader 5 and log in (**demo recommended**).
2. Enable **Algo Trading** (toolbar must be green).
3. Add your symbol to Market Watch.
4. Keep `"dry_run": true` for paper soak-tests; only set `"dry_run": false` after demo fills work.
5. Start the bot from the dashboard.

## Run (web browser)

```powershell
python main.py
```

Your browser opens automatically at `http://127.0.0.1:PORT` with the dashboard:

- Price candlestick chart + entry/exit markers
- RSI window styled like MT5 (blue RSI, yellow EMA48, black EMA50, custom levels)
- Balance / equity / floating / today’s P/L · win rate · confidence
- Start · Pause · Stop · Close All (or close a single position)
- Backtest · Settings · CSV export · live log stream

No internet is required — everything runs on your own machine.

## Project layout

```
HM Bot Trader/
  main.py
  dashboard/
    webapp.py        local web server + engine thread
    web/             browser UI (HTML/CSS/JS, zero dependencies)
  strategy/          indicators, signals, plugin strategy
  execution/         MT5 client, risk, trade executor
  database/          SQLite trades
  config/            settings.json
  backtest/          historical replay
  utils/             logging, notifications, paths
  logs/
```

## Troubleshooting

| Issue | Fix |
|-------|-----|
| MT5 initialize failed | Launch MT5 first; set `mt5.path` to `terminal64.exe` |
| Symbol not found | Copy the exact name from Market Watch |
| No orders in live mode | Enable Algo Trading; check lot size / margin |
| Dashboard shows SIM feed | Bot fell back to a simulated Crash-style feed in dry-run |
| Port already in use | The app auto-picks a free port and prints the URL |
| Signals differ slightly from phone | Ensure enough candle history (`candle_count` ≥ 300) |

## Secrets

Prefer an already-logged-in MetaTrader 5 terminal (`mt5.login = 0`).

Optional environment variables (recommended over saving secrets to disk):

| Variable | Purpose |
|----------|---------|
| `HM_MT5_PASSWORD` | MT5 password if login/server are set in settings |
| `HM_TELEGRAM_BOT_TOKEN` | Telegram bot token |
| `HM_WEB3_API_KEY` | HMPyWeb3Kit payment API key (required; read from environment) |

Passwords/tokens are **not** written to `settings.json` unless you explicitly
enable "Remember …" in Settings (not recommended).

## Run tests

```powershell
pip install -r requirements.txt
pytest -q
```

Money-safety checks live under `tests/test_money_safety.py` (daily halt, paper/live stats split, no paper fallback in live, SL/TP point math, secrets sanitization).

## Disclaimer

Trading involves risk of **loss**, including loss of capital. This software is for
**education and automation research**. It is **not** a guaranteed profit system,
financial advice, or a finished commercial trading product.

- Losses are normal — the bot can and will lose on some trades.
- Use **dry-run** and a **broker demo** account first.
- You are solely responsible for every live order and for complying with your
  local laws and broker terms.
- The price chart shows **market price**, not account equity.
- Do not share this as "ready for real money" until you have completed your own
  soak-testing and understand the risks.
- If you distribute publicly or charge money, get legal advice in your jurisdiction.

## Release status

**Demo / paper candidate** with money-safety gates, secrets hygiene, and automated tests.

## Packaging a Windows `.exe` (for sharing)

```bat
build_exe.bat
```

or

```powershell
powershell -ExecutionPolicy Bypass -File .\build_exe.ps1
```

Output: `dist\HMBotTrader\` (and `dist\HMBotTrader.zip`) — zip that folder to share.

### Your personal data is not inside the shared build

| Data | Where it lives | Shared in the zip? |
|------|----------------|--------------------|
| Balance / account login | Live from **their** MT5 when they connect | No |
| Total profit / win rate / history | `%LOCALAPPDATA%\HMBotTrader\trades.db` | No — empty DB created per user |
| Activation / license key | `%LOCALAPPDATA%\HMBotTrader\license.json` | No — created per user on activation |
| Settings / passwords | `%LOCALAPPDATA%\HMBotTrader\settings.json` | No — first run copies clean `settings.dist.json` only |

The PyInstaller bundle includes **only** `config/settings.dist.json` (`dry_run: true`, empty MT5 credentials).
It does **not** include your developer `config/settings.json` or any `trades.db`.

When someone installs and opens the bot:
1. They see empty/zero trade stats until they trade.
2. Balance shows their MT5 account (or a paper SIM balance if not connected) — never yours.
3. They configure their own symbol / MT5 in Settings.

### Before any public real-money distribution checklist

- [ ] Multi-day demo soak with stable open/close/SL/TP/reconcile behavior
- [ ] Users warned that losses happen; no performance guarantees in marketing
- [ ] Legal review if charging or widely distributing
- [ ] Code signing / installer for Windows downloads (recommended)
- [ ] Support channel for users who lose money / hit broker issues

This is still **not** a finished commercial real-money product by default.
