# USDT/TRX Faucet Automation Bot

**100% FREE** — No paid APIs, no captcha services, no proxies.

Automatically claims USDT (Tether) and TRX from free faucets using Playwright + **faster-whisper** audio captcha solver.

## How It Works

1. Visits faucet sites (claimto.xyz, ethiomi.com, freetrx.su)
2. Fills your FaucetPay email as payout address
3. Clicks the reCAPTCHA checkbox
4. Solves the audio challenge using **Whisper AI** (free, offline, 39MB model)
5. Submits the claim
6. Repeats every 5 minutes

### reCAPTCHA Solving Strategy (ALL FREE)

| Strategy | Method | Works Where |
|----------|--------|------------|
| Audio → Whisper | Download MP3, transcribe with faster-whisper | ✅ **Residential IPs** (confirmed: Libyan IP) |
| Image SKIP | For "If there are none, click skip" challenges | ✅ Most sites |
| Image VERIFY | For "Click verify once there are none left" | ✅ Most sites |

**⚠️ Important**: Google reCAPTCHA blocks data-center IPs (GitHub Actions, AWS, Google Cloud). The captcha challenge shows "Try again later" and never loads. This is NOT a bug in the script — it's Google's anti-abuse system.

**✅ Solution**: Run from a residential IP (home internet) — confirmed working from Libyan IP.

## Sites Supported

| Site | Coin | Payout | Cooldown | Login Needed? | Select Email? |
|------|------|--------|----------|---------------|---------------|
| [freeusdt.claimto.xyz](https://freeusdt.claimto.xyz) | USDT TRC20 | FaucetPay | 60s | No | Yes |
| [freeusdt.ethiomi.com](https://freeusdt.ethiomi.com) | USDT TRC20 | FaucetPay | 60s | Yes | No |
| [freetrx.su](https://freetrx.su) | TRX | FaucetPay | 120s | Yes | No |

**Estimated daily income**: ~$6.50 (all 3 sites, 24/7 operation)

## Setup & Running

### Option 1: Local PC (RECOMMENDED — confirmed working)

Your home internet has a residential IP that Google doesn't block.

**Windows:**
```batch
# One-click:
run_locally.bat
```

Or manually:
```batch
python -m venv venv
venv\Scripts\activate
pip install playwright faster-whisper requests
python -m playwright install chromium
python claimer_local.py
```

**Linux/Mac:**
```bash
python3 -m venv venv
source venv/bin/activate
pip install playwright faster-whisper requests
python -m playwright install chromium
python claimer_local.py
```

### Option 2: GitHub Actions (24/7, but IP BLOCKED by Google)

The bot runs for free on GitHub's servers every 5 minutes — but Google's reCAPTCHA **will not load** on data-center IPs. The script will fail gracefully and log diagnostics.

To set up:
1. Fork this repo
2. Add repository secrets:
   - `FAUCETPAY_EMAIL` — your FaucetPay account email
   - `FAUCETPAY_PASS` — your FaucetPay password (for ethiomi.com, freetrx.su)
3. The workflow runs automatically every 5 minutes

### Option 3: Google Colab (FREE, may work)

Google Colab provides free CPU/GPU runtimes — test if their IP range is whitelisted by Google.

1. Open the notebook in `colab/` directory
2. Run all cells
3. The bot will claim continuously for ~12 hours (session limit)

## Windows Task Scheduler Setup (24/7 Local)

For true 24/7 operation from your local PC:

1. Open **Task Scheduler**
2. Create Basic Task → name "USDT Faucet Bot"
3. Trigger: **When the computer starts** (or daily, repeating every 5 minutes)
4. Action: **Start a program**
   - Program: `C:\path\to\usdt-faucet-automation\run_locally.bat`
   - Start in: `C:\path\to\usdt-faucet-automation\`
5. Check "Run whether user is logged on or not"
6. Finish

**Keep your PC on 24/7** — the bot needs the browser to run.

## Project Structure

```
usdt-faucet-automation/
├── claimer.py           # Universal version (GHA + local)
├── claimer_local.py     # Optimized for local Windows execution
├── run_locally.bat      # One-click local runner
├── claim_state.json     # Cooldown & earnings tracker
├── logs/                # Per-run log files
├── screenshots/         # Debug screenshots
├── colab/
│   └── faucet_bot.ipynb # Google Colab notebook
└── .github/workflows/
    └── claim.yml        # GitHub Actions workflow
```

## Version History

| Version | Date | Method | Result |
|---------|------|--------|--------|
| v1 | May 2026 | curl_cffi + ddddocr | ❌ Sites use reCAPTCHA, not text captchas |
| v2 | May 2026 | Playwright (no solver) | ❌ reCAPTCHA unsolved |
| v3 | May 2026 | Playwright + Whisper audio | ❌ FrameLocator.count() bug |
| v4 | May 2026 | Fixed frame locator | ❌ Audio never loads on GHA IPs |
| v5 | May 2026 | Multi-strategy audio+SKIP+VERIFY | ❌ "Try again later" on GHA IPs |
| **v6** | **May 2026** | **Unified local/GHA + diagnostics** | **✅ Works from residential IP** |

## Debugging

If claims fail, check the `screenshots/` and `logs/` folders for clues.

Common issues:
- **"Try again later"** → Your IP is blocked by Google. Run from a residential IP.
- **"No audio source found"** → Audio challenge not served (happens on blocked IPs)
- **"Whisper transcription empty"** → Audio file corrupted or too short
- **FaucetPay email field disabled** → Click the "Email" radio button first (handled automatically in v6)

## Important Notes

- **All 3 sites pay via FaucetPay**, not direct wallet addresses
- FaucetPay email used: `pedagroup.co2020@gmail.com`
- Earnings are tiny per claim ($0.001–$0.005) but add up over 24/7 operation
- Estimated ~$6.50/day with all 3 sites running 24/7

## License

MIT
