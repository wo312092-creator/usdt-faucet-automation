# USDT Faucet Automation Bot

Automatically claims from USDT/Tether faucet sites every hour.
Runs on GitHub Actions (free, unlimited minutes since repo is PUBLIC).

## Supported Sites

| Site | Earnings/Day | Status |
|------|-------------|--------|
| freeusdt.claimto.xyz | $2.88 | Active |
| freeusdt.ethiomi.com | $7.20 | Active |
| **Total** | **$10.08/day** | |

## How It Works

1. curl_cffi fetches the faucet page (Chrome TLS fingerprint)
2. ddddocr solves any text captcha (FREE, 95%+ accuracy)
3. Script submits your USDT (TRC20) wallet address
4. GitHub Actions runs every hour via cron

## Secrets Required

| Secret | Value |
|--------|-------|
| USDT_WALLET | Your TRC20 USDT wallet address |

## Run Frequency

- Automatic: Every hour (`0 * * * *`)
- Manual: Via GitHub Actions → "Run workflow" button

## Wallet

`TDhd6w3QmshBtkW3899zM3QpqVSbwMsAPt`
