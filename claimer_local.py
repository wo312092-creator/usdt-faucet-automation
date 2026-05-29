#!/usr/bin/env python3
"""
USDT / TRX Faucet Automation Bot — LOCAL EXECUTION VERSION
==========================================================
For running on a machine with a CLEAN (residential) IP address.
Tested working from Libyan IP.

Key differences from GHA version:
  - Longer/adaptive timeouts (local PC is stable)
  - Rich console output with timing
  - Screenshot debug logs to local folder
  - File-based logging
  - Better retry logic
  - Handles #address disabled state (claimto.xyz needs email radio clicked first)
  - Saves claim history locally

REQUIREMENTS:
  pip install playwright faster-whisper requests
  python -m playwright install chromium
"""

import os, sys, json, time, logging, tempfile, traceback
from datetime import datetime, timezone
from pathlib import Path

# ── Setup logging ─────────────────────────────────────────────────
LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)
log_file = LOG_DIR / f"claimer_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.FileHandler(str(log_file), encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────
FAUCETPAY_EMAIL = "pedagroup.co2020@gmail.com"
STATE_FILE = Path(__file__).parent / "claim_state.json"
SCREENSHOT_DIR = Path(__file__).parent / "screenshots"
SCREENSHOT_DIR.mkdir(exist_ok=True)
HEADLESS = False  # Set to True once everything is stable
WHISPER_MODEL = "tiny"  # "tiny" (fast) or "base" (more accurate)

SITES = [
    # (key, url, cooldown_sec, needs_login, select_email_first)
    ("claimto.xyz", "https://freeusdt.claimto.xyz", 60, False, True),
    ("ethiomi.com", "https://freeusdt.ethiomi.com", 60, True, False),
    ("freetrx.su",  "https://freetrx.su",           120, True, False),
]


# ═══════════════════════════════════════════════════════════════════
#  STATE MANAGER
# ═══════════════════════════════════════════════════════════════════
class StateManager:
    def __init__(self, path=STATE_FILE):
        self.path = Path(path)
        self.data = {}
        self._load()

    def _load(self):
        try:
            with open(self.path) as f:
                self.data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            self.data = {"claims": {}, "total_earned": 0.0}

    def save(self):
        with open(self.path, "w") as f:
            json.dump(self.data, f, indent=2)

    def get_last_claim(self, site_key: str) -> float:
        return self.data.get("claims", {}).get(site_key, 0)

    def mark_claimed(self, site_key: str, amount: float = 0.0):
        self.data.setdefault("claims", {})[site_key] = time.time()
        self.data["total_earned"] = self.data.get("total_earned", 0.0) + amount
        self.save()

    def cooldown_remaining(self, site_key: str, cooldown: int) -> int:
        elapsed = time.time() - self.get_last_claim(site_key)
        return max(0, int(cooldown - elapsed))


# ═══════════════════════════════════════════════════════════════════
#  RECAPTCHA SOLVER — Audio (Whisper) + Image (SKIP/VERIFY)
# ═══════════════════════════════════════════════════════════════════
class RecaptchaSolver:
    """
    Free reCAPTCHA v2 solving:
    1. Click checkbox → check if auto-solved
    2. If challenge appears → try audio (Whisper) — BEST for clean IPs
    3. If audio fails → try SKIP/VERIFY (some challenges are empty)
    4. If all fails → screenshot for debug
    """

    def __init__(self):
        self.whisper_model = None
        self._load_whisper()

    def _load_whisper(self):
        try:
            from faster_whisper import WhisperModel
            log.info(f"[Whisper] Loading '{WHISPER_MODEL}' model (CPU, int8)...")
            self.whisper_model = WhisperModel(
                WHISPER_MODEL, device="cpu", compute_type="int8"
            )
            log.info("[Whisper] Model loaded ✓")
        except ImportError:
            log.warning("[Whisper] faster-whisper not installed — audio solving disabled")
        except Exception as e:
            log.warning(f"[Whisper] Load failed: {e}")

    # ── helpers ───────────────────────────────────────────────────
    def _get_frame(self, page, selector: str, timeout: int = 10):
        try:
            el = page.wait_for_selector(selector, timeout=timeout * 1000)
            if el:
                frame = el.content_frame()
                return frame
        except:
            pass
        return None

    def _click_in_frame(self, frame, selector: str, timeout: int = 5) -> bool:
        try:
            frame.wait_for_selector(selector, timeout=timeout * 1000)
            frame.click(selector, timeout=timeout * 1000)
            return True
        except:
            try:
                frame.evaluate(f"document.querySelector('{selector}').click()")
                return True
            except:
                return False

    def _check_solved(self, page) -> bool:
        try:
            val = page.evaluate(
                "() => { const t = document.getElementById('g-recaptcha-response'); return t ? t.value : ''; }"
            )
            if val and len(val) > 50:
                log.info(f"  ✓ reCAPTCHA solved! token={val[:20]}...")
                return True
        except:
            pass
        return False

    def _debug_screenshot(self, page, name: str):
        try:
            path = SCREENSHOT_DIR / f"{name}_{datetime.now().strftime('%H%M%S')}.png"
            page.screenshot(path=str(path))
            log.info(f"  📸 Screenshot saved: {path.name}")
        except:
            pass

    # ── main entry ────────────────────────────────────────────────
    def solve(self, page, site_key: str) -> bool:
        log.info("── reCAPTCHA solving ──")

        # 1. Find & click checkbox
        log.info("  Step 1: Click checkbox...")
        anchor_frame = self._get_frame(page, 'iframe[title="reCAPTCHA"]', timeout=8)
        if not anchor_frame:
            log.warning("  ✗ No reCAPTCHA iframe found")
            self._debug_screenshot(page, "no_recaptcha")
            return False
        if not self._click_in_frame(anchor_frame, ".recaptcha-checkbox-border"):
            log.warning("  ✗ Could not click checkbox")
            return False
        log.info("  ✓ Checkbox clicked")
        time.sleep(3)

        # 2. Check if already solved
        if self._check_solved(page):
            log.info("  ✓ Auto-solved (no challenge needed)")
            return True

        # 3. Wait for challenge iframe
        log.info("  Step 2: Looking for challenge...")
        challenge_frame = self._get_frame(page, 'iframe[title*="challenge"]', timeout=8)
        if not challenge_frame:
            log.warning("  ✗ Challenge iframe did not appear")
            self._debug_screenshot(page, "no_challenge")
            return False
        log.info("  ✓ Challenge iframe found")

        # 4. Try Audio (Whisper) — PRIMARY for clean IPs
        if self.whisper_model and self._try_audio(challenge_frame, page):
            if self._check_solved(page):
                log.info("  ✓ Solved via Audio+Whisper!")
                return True

        # 5. Try SKIP / VERIFY (for "none" challenges)
        log.info("  Step 4: Trying SKIP/VERIFY...")
        if self._try_skip_verify(challenge_frame, page):
            if self._check_solved(page):
                log.info("  ✓ Solved via SKIP/VERIFY!")
                return True

        log.warning("  ✗ All strategies failed")
        self._debug_screenshot(page, f"failed_{site_key}")
        return False

    # ── Audio strategy (Whisper) ──────────────────────────────────
    def _try_audio(self, frame, page) -> bool:
        log.info("  Step 3: Audio challenge...")

        # Click audio button
        if not self._click_in_frame(frame, "#recaptcha-audio-button"):
            log.warning("  ✗ No audio button — trying image")
            return False
        log.info("  ✓ Audio button clicked")
        time.sleep(2)

        # Wait for audio source (poll 25s)
        log.info("  Waiting for audio source...")
        audio_el = None
        for _ in range(25):
            try:
                audio_el = frame.wait_for_selector("#audio-source", timeout=1000)
                if audio_el:
                    break
            except:
                pass
            time.sleep(1)

        if not audio_el:
            log.warning("  ✗ Audio source not found in 25s")
            try:
                html = frame.evaluate("() => document.body.innerHTML")
                log.warning(f"  Frame body: {html[:400]}")
            except:
                pass
            return False

        src = audio_el.get_attribute("src")
        if not src:
            log.warning("  ✗ Audio source has no src")
            return False
        log.info(f"  Audio URL: {src[:70]}...")

        # Download MP3
        import urllib.request
        audio_path = os.path.join(tempfile.gettempdir(), "captcha.mp3")
        try:
            urllib.request.urlretrieve(src, audio_path)
            size = os.path.getsize(audio_path)
            log.info(f"  Downloaded: {size} bytes")
            if size < 1000:
                log.warning("  Audio too small")
                return False
        except Exception as e:
            log.warning(f"  Download failed: {e}")
            return False

        # Transcribe
        log.info("  Transcribing with Whisper...")
        try:
            segments, info = self.whisper_model.transcribe(
                audio_path, language="en", beam_size=1, best_of=1
            )
            answer = " ".join(s.text.strip() for s in segments).strip()
            log.info(f"  Whisper says: '{answer}'")
        except Exception as e:
            log.warning(f"  Transcription failed: {e}")
            return False

        if not answer:
            log.warning("  Empty transcription")
            return False

        # Submit
        log.info("  Submitting answer...")
        try:
            inp = frame.wait_for_selector("#audio-response", timeout=5000)
            if inp:
                inp.fill(answer)
            time.sleep(0.5)
            frame.evaluate("document.getElementById('recaptcha-verify-button').click()")
            time.sleep(3)
        except Exception as e:
            log.warning(f"  Submit error: {e}")
            return False

        log.info("  ✓ Audio submitted")
        return True

    # ── SKIP / VERIFY strategy ────────────────────────────────────
    def _try_skip_verify(self, frame, page) -> bool:
        for attempt in range(3):
            try:
                body = frame.evaluate("() => document.body ? document.body.innerText : ''")
                log.info(f"  Challenge text: '{body[:120]}'")
            except:
                body = ""

            # SKIP
            try:
                btn = frame.wait_for_selector("button:has-text('SKIP')", timeout=2000)
                if btn:
                    btn.click()
                    time.sleep(2)
                    log.info(f"  Clicked SKIP ({attempt+1})")
                    if self._check_solved(page):
                        return True
                    continue
            except:
                pass

            # VERIFY (without selecting tiles)
            try:
                btn = frame.wait_for_selector("button:has-text('VERIFY')", timeout=2000)
                if btn:
                    btn.click()
                    time.sleep(2)
                    log.info(f"  Clicked VERIFY ({attempt+1})")
                    if self._check_solved(page):
                        return True
                    continue
            except:
                pass

            # Reload & try again
            try:
                reload_btn = frame.wait_for_selector(
                    "#recaptcha-reload-button", timeout=2000
                )
                if reload_btn:
                    reload_btn.click()
                    time.sleep(2)
                    log.info(f"  Reloaded ({attempt+1})")
            except:
                pass

        return False


# ═══════════════════════════════════════════════════════════════════
#  SITE CLAIMER
# ═══════════════════════════════════════════════════════════════════
class SiteClaimer:
    def __init__(self, state: StateManager, captcha: RecaptchaSolver):
        self.state = state
        self.captcha = captcha
        self.browser = None
        self.page = None

    def start(self):
        from playwright.sync_api import sync_playwright

        p = sync_playwright().start()
        self.browser = p.chromium.launch(
            headless=HEADLESS,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
            ],
            timeout=30000,
        )
        ctx = self.browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800},
            locale="en-US",
        )
        ctx.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'plugins', { get: () => [1,2,3,4,5] });
            Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
            window.chrome = { runtime: {} };
        """)
        self.page = ctx.new_page()
        log.info("[Browser] started")

    def stop(self):
        try:
            if self.page:
                self.page.close()
            if self.browser:
                self.browser.close()
        except:
            pass

    def claim(self, key: str, url: str, cooldown: int, needs_login: bool, select_email: bool) -> bool:
        remaining = self.state.cooldown_remaining(key, cooldown)
        if remaining > 0:
            log.info(f"[{key}] ⏳ Cooldown {remaining}s — skipping")
            return False

        log.info(f"\n{'='*60}")
        log.info(f"[{key}] Opening {url}")
        log.info(f"{'='*60}")

        try:
            self.page.goto(url, timeout=30000, wait_until="domcontentloaded")
            time.sleep(3)

            # ── Site-specific setup ──
            if select_email:
                log.info("  Selecting 'Email' radio...")
                try:
                    self.page.click("#type-email", timeout=5000)
                    time.sleep(0.5)
                except:
                    log.warning("  Could not click email radio")

            # Fill address — use JS for reliability
            log.info(f"  Filling FaucetPay email...")
            self.page.evaluate(
                "(e) => { const i = document.getElementById('address'); if(i) { i.value = e; i.dispatchEvent(new Event('input',{bubbles:true})); } }",
                FAUCETPAY_EMAIL,
            )
            time.sleep(0.5)

            # Click start / login
            btn = "start" if not needs_login else "login"
            log.info(f"  Clicking '{btn}'...")
            clicked = self.page.evaluate(
                """(t) => {
                    for (const b of document.querySelectorAll('button')) {
                        if (b.innerText.toLowerCase().includes(t)) { b.click(); return true; }
                    }
                    return false;
                }""",
                btn,
            )
            if not clicked:
                log.warning(f"  Could not find '{btn}' button")
                self._screenshot(f"{key}_no_button")
                return False
            time.sleep(3)

            # ── Solve captcha ──
            log.info(f"  Solving captcha...")
            solved = self.captcha.solve(self.page, key)
            if solved:
                self.state.mark_claimed(key, 0.002)
                log.info(f"[{key}] ✅ CLAIM SUCCESSFUL!")
                self._screenshot(f"{key}_success")
                return True
            else:
                log.warning(f"[{key}] ❌ Captcha failed")
                return False

        except Exception as e:
            log.error(f"[{key}] Error: {e}")
            log.error(traceback.format_exc())
            self._screenshot(f"{key}_error")
            return False

    def _screenshot(self, name: str):
        try:
            path = SCREENSHOT_DIR / f"{name}_{datetime.now().strftime('%H%M%S')}.png"
            self.page.screenshot(path=str(path))
            log.info(f"  📸 {path.name}")
        except:
            pass


# ═══════════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════════
def main():
    print()
    log.info("╔" + "═" * 58 + "╗")
    log.info("║       USDT/TRX FAUCET AUTOMATION — LOCAL EDITION       ║")
    log.info("║       Audio (Whisper) + SKIP/VERIFY reCAPTCHA solver  ║")
    log.info("║       FaucetPay: " + FAUCETPAY_EMAIL.ljust(44) + "║")
    log.info("╚" + "═" * 58 + "╝")
    log.info(f"  Time: {datetime.now(timezone.utc).isoformat()}")
    log.info(f"  Headless: {HEADLESS}")
    log.info(f"  Log file: {log_file.name}")
    log.info(f"  Screenshots: {SCREENSHOT_DIR}")
    log.info(f"  State: {STATE_FILE}")

    state = StateManager()
    captcha = RecaptchaSolver()
    claimer = SiteClaimer(state, captcha)

    try:
        claimer.start()

        results = {}
        for key, url, cd, login, email_sel in SITES:
            results[key] = claimer.claim(key, url, cd, login, email_sel)

        # ── Summary ──
        succeeded = sum(1 for v in results.values() if v)
        log.info(f"\n{'='*60}")
        log.info(f"  RESULTS: {succeeded}/{len(SITES)} claimed this run")
        for k, v in results.items():
            log.info(f"    {k}: {'✅ OK' if v else '❌ FAIL'}")
        log.info(f"  Total earned (est): {state.data.get('total_earned', 0):.4f} USDT")
        log.info(f"  Log: {log_file}")
        log.info("  Done")

    finally:
        claimer.stop()


if __name__ == "__main__":
    main()
