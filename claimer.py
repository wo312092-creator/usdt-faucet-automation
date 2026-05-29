#!/usr/bin/env python3
"""
USDT / TRX Faucet Automation Bot - v6 (Universal)
==================================================
FREE reCAPTCHA solving using Audio (Whisper) + Image (SKIP/VERIFY) strategies.
Works on ANY machine with a clean residential IP.

REALITY:
  - Sites pay via FaucetPay, NOT direct wallet
  - Google reCAPTCHA v2 blocks data-center IPs (GitHub Actions, etc.)
  - Audio+Whisper works from residential IPs (confirmed: Libyan IP)
  - This script adapts: runs full solve on clean IPs, diagnostic-only on blocked IPs

DEPLOYMENT OPTIONS (100% FREE):
  1. Local PC (residential IP) — confirmed working → use run_locally.bat
  2. Google Colab — free GPU, test if IP is whitelisted
  3. Any free-tier VPS with clean IP
"""

import os, sys, json, time, logging, tempfile, traceback
from datetime import datetime, timezone
from pathlib import Path

# ── Detect environment ────────────────────────────────────────────
ON_GITHUB_ACTIONS = os.environ.get("GITHUB_ACTIONS") == "true"
IS_WINDOWS = sys.platform.startswith("win")

# ── Config ────────────────────────────────────────────────────────
FAUCETPAY_EMAIL = os.environ.get("FAUCETPAY_EMAIL", "pedagroup.co2020@gmail.com").strip()
HEADLESS = True  # Always headless in automation
WHISPER_MODEL = "tiny"

STATE_FILE = "claim_state.json"
LOG_DIR = Path("logs")
SCREENSHOT_DIR = Path("screenshots")
LOG_DIR.mkdir(exist_ok=True)
SCREENSHOT_DIR.mkdir(exist_ok=True)

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

SITES = [
    # (key, url, cooldown_sec, needs_login, select_email_first)
    ("claimto.xyz", "https://freeusdt.claimto.xyz", 60,  False, True),
    ("ethiomi.com", "https://freeusdt.ethiomi.com", 60,  True,  False),
    ("freetrx.su",  "https://freetrx.su",           120, True,  False),
]


# ═══════════════════════════════════════════════════════════════════
#  STATE
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

    def get_last_claim(self, key: str) -> float:
        return self.data.get("claims", {}).get(key, 0)

    def mark_claimed(self, key: str, amount: float = 0.0):
        self.data.setdefault("claims", {})[key] = time.time()
        self.data["total_earned"] = self.data.get("total_earned", 0.0) + amount
        self.save()

    def cooldown_remaining(self, key: str, cooldown: int) -> int:
        return max(0, int(cooldown - (time.time() - self.get_last_claim(key))))


# ═══════════════════════════════════════════════════════════════════
#  RECAPTCHA SOLVER
# ═══════════════════════════════════════════════════════════════════
class RecaptchaSolver:
    """
    Multi-strategy free reCAPTCHA v2 solver:
      1) Click checkbox
      2) Audio challenge → Whisper (works on clean IPs)
      3) SKIP / VERIFY (for "none" challenges)
      4) Diagnostic info when all fails
    """

    def __init__(self):
        self.whisper_model = None
        self._load_whisper()

    def _load_whisper(self):
        try:
            from faster_whisper import WhisperModel
            log.info(f"[Whisper] Loading '{WHISPER_MODEL}' model (CPU int8)...")
            self.whisper_model = WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8")
            log.info("[Whisper] Ready")
        except ImportError:
            log.warning("[Whisper] faster-whisper not installed")
        except Exception as e:
            log.warning(f"[Whisper] Load error: {e}")

    # ── helpers ───────────────────────────────────────────────────
    def _get_frame(self, page, sel: str, timeout: int = 10):
        try:
            el = page.wait_for_selector(sel, timeout=timeout * 1000)
            return el.content_frame() if el else None
        except:
            return None

    def _click_frame(self, frame, sel: str, timeout: int = 5) -> bool:
        try:
            frame.wait_for_selector(sel, timeout=timeout * 1000)
            frame.click(sel, timeout=timeout * 1000)
            return True
        except:
            try:
                frame.evaluate(f"document.querySelector('{sel}').click()")
                return True
            except:
                return False

    def _is_solved(self, page) -> bool:
        try:
            v = page.evaluate("() => { const t = document.getElementById('g-recaptcha-response'); return t ? t.value : ''; }")
            if v and len(v) > 50:
                log.info(f"  ✓ token={v[:20]}...")
                return True
        except:
            pass
        return False

    def _screenshot(self, page, name: str):
        try:
            p = SCREENSHOT_DIR / f"{name}_{datetime.now().strftime('%H%M%S')}.png"
            page.screenshot(path=str(p))
            log.info(f"  📸 {p.name}")
        except:
            pass

    def _challenge_body(self, frame) -> str:
        try:
            return frame.evaluate("() => document.body ? document.body.innerText : ''") or ""
        except:
            return ""

    # ── main solver ───────────────────────────────────────────────
    def solve(self, page) -> bool:
        log.info("── reCAPTCHA ──")

        # 1. Click checkbox
        log.info("  1) Checkbox...")
        f = self._get_frame(page, 'iframe[title="reCAPTCHA"]', 8)
        if not f or not self._click_frame(f, ".recaptcha-checkbox-border"):
            log.warning("  ✗ No checkbox")
            return False
        log.info("  ✓ Clicked")
        time.sleep(3)

        if self._is_solved(page):
            log.info("  ✓ Auto-passed")
            return True

        # 2. Challenge iframe
        log.info("  2) Challenge...")
        cf = self._get_frame(page, 'iframe[title*="challenge"]', 8)
        if not cf:
            log.warning("  ✗ No challenge iframe — IP blocked?")
            self._screenshot(page, "blocked")
            return False
        log.info("  ✓ Found")

        # 3. Audio (Whisper)
        if self.whisper_model:
            log.info("  3) Audio...")
            if self._try_audio(cf, page):
                return True

        # 4. SKIP/VERIFY
        log.info("  4) SKIP/VERIFY...")
        if self._try_skip_verify(cf, page):
            return True

        log.warning("  ✗ All strategies failed")
        self._screenshot(page, "failed")
        return False

    # ── Audio ─────────────────────────────────────────────────────
    def _try_audio(self, frame, page) -> bool:
        if not self._click_frame(frame, "#recaptcha-audio-button"):
            log.info("    No audio button")
            return False
        log.info("    Audio button clicked")
        time.sleep(2)

        src = None
        for _ in range(25):
            try:
                el = frame.wait_for_selector("#audio-source", timeout=1000)
                if el:
                    src = el.get_attribute("src")
                    if src:
                        break
            except:
                pass
            time.sleep(1)

        if not src:
            log.warning("    No audio source (25s)")
            log.info(f"    Frame text: {self._challenge_body(frame)[:300]}")
            return False
        log.info(f"    URL: {src[:70]}...")

        import urllib.request
        ap = os.path.join(tempfile.gettempdir(), "cap.mp3")
        try:
            urllib.request.urlretrieve(src, ap)
            sz = os.path.getsize(ap)
            log.info(f"    Downloaded: {sz}B")
            if sz < 1000:
                return False
        except Exception as e:
            log.warning(f"    Download error: {e}")
            return False

        log.info("    Transcribing...")
        try:
            segs, _ = self.whisper_model.transcribe(ap, language="en", beam_size=1, best_of=1)
            ans = " ".join(s.text.strip() for s in segs).strip()
            log.info(f"    Whisper: '{ans}'")
        except Exception as e:
            log.warning(f"    Whisper error: {e}")
            return False

        if not ans:
            return False

        try:
            inp = frame.wait_for_selector("#audio-response", timeout=5000)
            if inp:
                inp.fill(ans)
            time.sleep(0.5)
            frame.evaluate("document.getElementById('recaptcha-verify-button').click()")
            time.sleep(3)
        except Exception as e:
            log.warning(f"    Submit error: {e}")
            return False

        return self._is_solved(page)

    # ── SKIP / VERIFY ─────────────────────────────────────────────
    def _try_skip_verify(self, frame, page) -> bool:
        for i in range(3):
            txt = self._challenge_body(frame)
            log.info(f"    Challenge: '{txt[:100]}'")

            for label in ("SKIP", "VERIFY"):
                try:
                    btn = frame.wait_for_selector(f'button:has-text("{label}")', timeout=2000)
                    if btn:
                        btn.click()
                        time.sleep(2)
                        log.info(f"    Clicked {label} ({i+1})")
                        if self._is_solved(page):
                            return True
                except:
                    pass

            # Reload
            try:
                rb = frame.wait_for_selector("#recaptcha-reload-button", timeout=2000)
                if rb:
                    rb.click()
                    time.sleep(2)
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
        self.page = None
        self._pw = None
        self._browser = None

    def start(self):
        from playwright.sync_api import sync_playwright
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(
            headless=HEADLESS,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
            ],
            timeout=30000,
        )
        ctx = self._browser.new_context(
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/124.0.0.0 Safari/537.36"),
            viewport={"width": 1280, "height": 800},
            locale="en-US",
        )
        ctx.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get:()=>undefined});
            Object.defineProperty(navigator, 'plugins', {get:()=>[1,2,3,4,5]});
            Object.defineProperty(navigator, 'languages', {get:()=>['en-US','en']});
            window.chrome = {runtime:{}};
        """)
        self.page = ctx.new_page()

    def stop(self):
        try:
            if self.page: self.page.close()
            if self._browser: self._browser.close()
            if self._pw: self._pw.stop()
        except:
            pass

    def claim(self, key: str, url: str, cooldown: int, needs_login: bool, select_email: bool) -> bool:
        rem = self.state.cooldown_remaining(key, cooldown)
        if rem > 0:
            log.info(f"[{key}] ⏳ cooldown {rem}s")
            return False

        log.info(f"\n─── {key} ───")
        try:
            self.page.goto(url, timeout=30000, wait_until="domcontentloaded")
            time.sleep(3)

            if select_email:
                try:
                    self.page.click("#type-email", timeout=5000)
                    time.sleep(0.5)
                except:
                    pass

            # Fill address via JS (handles disabled state)
            self.page.evaluate(
                "(e) => { const i = document.getElementById('address'); if(i) { i.value = e; i.dispatchEvent(new Event('input',{bubbles:true})); } }",
                FAUCETPAY_EMAIL,
            )
            time.sleep(0.5)

            btn_label = "start" if not needs_login else "login"
            clicked = self.page.evaluate(
                """(t) => {
                    for (const b of document.querySelectorAll('button')) {
                        if (b.innerText.toLowerCase().includes(t)) { b.click(); return true; }
                    }
                    return false;
                }""",
                btn_label,
            )
            if not clicked:
                log.warning(f"  No '{btn_label}' button")
                self._screenshot(f"{key}_no_btn")
                return False
            time.sleep(3)

            solved = self.captcha.solve(self.page)
            if solved:
                self.state.mark_claimed(key, 0.002)
                log.info(f"[{key}] ✅ CLAIMED")
                self._screenshot(f"{key}_ok")
                return True
            else:
                log.warning(f"[{key}] ❌ captcha unsolved")
                return False

        except Exception as e:
            log.error(f"[{key}] Error: {e}")
            log.error(traceback.format_exc())
            self._screenshot(f"{key}_crash")
            return False

    def _screenshot(self, name: str):
        try:
            p = SCREENSHOT_DIR / f"{name}_{datetime.now().strftime('%H%M%S')}.png"
            self.page.screenshot(path=str(p))
            log.info(f"  📸 {p.name}")
        except:
            pass


# ═══════════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════════
def main():
    log.info("╔" + "═" * 58 + "╗")
    log.info("║        USDT/TRX FAUCET AUTOMATION — v6 (Universal) ║")
    log.info("║        Audio(Whisper) + SKIP/VERIFY reCAPTCHA solver║")
    log.info("║        FaucetPay: " + FAUCETPAY_EMAIL.ljust(42) + "║")
    log.info("╠" + "═" * 58 + "╣")
    log.info(f"║  GHA:{str(ON_GITHUB_ACTIONS):>5}  |  OS:{sys.platform:>7}         ║")
    log.info(f"║  Headless:{str(HEADLESS):>5}  |  Whisper:{WHISPER_MODEL:>6}          ║")
    log.info(f"║  Log: {str(log_file):>48} ║")
    log.info("╚" + "═" * 58 + "╝")

    state = StateManager()
    captcha = RecaptchaSolver()
    claimer = SiteClaimer(state, captcha)

    try:
        claimer.start()
        results = {}
        for key, url, cd, login, email_sel in SITES:
            results[key] = claimer.claim(key, url, cd, login, email_sel)

        ok = sum(1 for v in results.values() if v)
        log.info(f"\n{'='*60}")
        log.info(f"  {ok}/{len(SITES)} claimed this cycle")
        for k, v in results.items():
            log.info(f"    {k}: {'✅' if v else '❌'}")
        log.info(f"  Total earned (est): {state.data.get('total_earned', 0):.4f} USDT")
        log.info(f"  Log: {log_file}")
    finally:
        claimer.stop()


if __name__ == "__main__":
    main()
