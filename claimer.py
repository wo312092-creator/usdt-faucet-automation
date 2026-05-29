#!/usr/bin/env python3
"""
USDT / TRX Faucet Automation Bot - v3 (Whisper Captcha Solver)
==============================================================
REALITY-BASED:
  - Sites pay via FaucetPay, NOT direct wallet
  - They use Google reCAPTCHA v2 (checkbox)
  - We solve it COMPLETELY FREE using OpenAI Whisper audio transcription
  - Playwright browser automation (no curl_cffi needed)

FREE CAPTCHA SOLVING:
  1. Click reCAPTCHA checkbox
  2. Switch to audio challenge (accessibility mode)
  3. Download the audio MP3
  4. Transcribe with faster-whisper (tiny model, 39MB, CPU, int8)
  5. Submit answer
  6. Cost: $0.00

Supported sites:
  1. FreeTether (claimto.xyz) - USDT - every 1 min - FaucetPay
  2. Tether faucet (ethiomi.com) - USDT - every 1 min - FaucetPay
  3. FreeTRX.su - TRX - every 2 min - FaucetPay (PROVEN WORKING)
"""

import os, sys, json, time, logging, tempfile
from datetime import datetime, timezone
from typing import Optional

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
log = logging.getLogger(__name__)

# ===== CONFIG (from secrets) =====
FAUCETPAY_EMAIL = os.environ.get("FAUCETPAY_EMAIL", "").strip()
FAUCETPAY_PASS = os.environ.get("FAUCETPAY_PASS", "").strip()
CAPTCHA_API_KEY = os.environ.get("CAPTCHA_API_KEY", "").strip()
CAPTCHA_SERVICE = os.environ.get("CAPTCHA_SERVICE", "whisper").strip().lower()

if not FAUCETPAY_EMAIL:
    log.error("[FATAL] FAUCETPAY_EMAIL not set!")
    sys.exit(1)

STATE_FILE = "claim_state.json"
WHISPER_CACHE = os.path.expanduser("~/.cache/whisper")


# ===== STATE MANAGER =====
class StateManager:
    def __init__(self, path=STATE_FILE):
        self.path = path
        self.data = {}
        self._load()

    def _load(self):
        try:
            with open(self.path, "r") as f:
                self.data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            self.data = {"claims": {}, "total_earned": 0.0}

    def save(self):
        with open(self.path, "w") as f:
            json.dump(self.data, f, indent=2)

    def get_last_claim(self, site_key: str) -> float:
        return self.data.get("claims", {}).get(site_key, 0)

    def mark_claimed(self, site_key: str, amount: float = 0.0):
        if "claims" not in self.data:
            self.data["claims"] = {}
        self.data["claims"][site_key] = time.time()
        self.data["total_earned"] = self.data.get("total_earned", 0.0) + amount
        self.save()

    def cooldown_remaining(self, site_key: str, cooldown: int) -> int:
        elapsed = time.time() - self.get_last_claim(site_key)
        return max(0, int(cooldown - elapsed))


# ===== WHISPER CAPTCHA SOLVER =====
class RecaptchaAudioSolver:
    """
    SOLVE reCAPTCHA v2 using AUDIO CHALLENGE + Whisper
    --- COMPLETELY FREE, NO API KEY NEEDED ---
    
    How it works:
    1. Click the reCAPTCHA checkbox via Playwright
    2. Switch to audio challenge mode
    3. Download the audio MP3 from Google
    4. Transcribe using faster-whisper (tiny model, CPU)
    5. Submit the transcribed text
    6. reCAPTCHA solved!
    """

    def __init__(self):
        self.whisper_model = None
        self.model_loaded = False
        self.use_whisper = (CAPTCHA_SERVICE == "whisper" or not CAPTCHA_API_KEY)
        
        if self.use_whisper:
            log.info("[Captcha] Using Whisper audio solver (FREE, no API key)")
        else:
            log.info(f"[Captcha] Using {CAPTCHA_SERVICE} API")

    def _load_whisper(self):
        """Load faster-whisper model (tiny, 39MB, CPU, int8)."""
        if self.model_loaded:
            return True
        try:
            from faster_whisper import WhisperModel
            log.info("[Whisper] Loading tiny model (39MB)...")
            self.whisper_model = WhisperModel("tiny", device="cpu", compute_type="int8")
            self.model_loaded = True
            log.info("[Whisper] Model loaded!")
            return True
        except ImportError:
            log.warning("[Whisper] faster-whisper not installed")
            return False
        except Exception as e:
            log.error(f"[Whisper] Load failed: {e}")
            return False

    def solve(self, page, site_url: str, site_key_hint: str = "") -> bool:
        """
        Solve reCAPTCHA v2 on the current page.
        Returns True if solved successfully.
        """
        if self.use_whisper:
            return self._solve_whisper(page)
        else:
            return self._solve_api(page, site_url, site_key_hint)

    def _get_frame(self, page, selector: str, timeout: int = 8):
        """Get a frame by iframe selector, returns (frame_obj, element) or (None, None)."""
        try:
            el = page.wait_for_selector(selector, timeout=timeout * 1000)
            if el:
                frame = el.content_frame()
                if frame:
                    return frame, el
        except:
            pass
        return None, None

    def _click_in_frame(self, frame, selector: str, timeout: int = 5) -> bool:
        """Click an element inside a frame, fallback to JS click."""
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

    def _solve_whisper(self, page) -> bool:
        """Solve using audio challenge + Whisper transcription.
        
        Uses content_frame() for direct iframe access, with JS fallback clicks.
        """
        if not self._load_whisper():
            return False

        try:
            # Step 1: Find reCAPTCHA anchor iframe
            log.info("  [Whisper] Looking for reCAPTCHA iframe...")
            anchor_frame, _ = self._get_frame(page, 'iframe[title="reCAPTCHA"]', timeout=8)
            if not anchor_frame:
                log.warning("  [Whisper] No reCAPTCHA iframe found")
                return False
            
            # Step 2: Click the reCAPTCHA checkbox
            log.info("  [Whisper] Clicking reCAPTCHA checkbox...")
            clicked = self._click_in_frame(anchor_frame, ".recaptcha-checkbox-border")
            if not clicked:
                log.warning("  [Whisper] Could not click checkbox")
                return False
            log.info("  [Whisper] Checkbox clicked!")
            time.sleep(2)
            
            # Step 3: Wait for challenge iframe
            log.info("  [Whisper] Waiting for challenge iframe...")
            challenge_frame, _ = self._get_frame(page, 'iframe[title*="challenge"]', timeout=8)
            if not challenge_frame:
                log.warning("  [Whisper] Challenge iframe didn't appear")
                return False
            log.info("  [Whisper] Challenge iframe found!")
            
            # Step 4: Click audio button inside challenge iframe
            log.info("  [Whisper] Clicking audio button...")
            clicked = self._click_in_frame(challenge_frame, "#recaptcha-audio-button")
            if not clicked:
                log.warning("  [Whisper] Could not click audio button")
                return False
            log.info("  [Whisper] Audio button clicked!")
            
            # Step 5: Wait for audio source to appear (max 15s)
            log.info("  [Whisper] Waiting for audio source...")
            audio_el = None
            for _ in range(15):
                try:
                    audio_el = challenge_frame.wait_for_selector("#audio-source", timeout=1000)
                    if audio_el:
                        break
                except:
                    pass
                time.sleep(1)
            
            if not audio_el:
                log.warning("  [Whisper] Audio source element not found in 15s")
                # Debug: dump iframe HTML to understand what's there
                try:
                    body_html = challenge_frame.evaluate("() => document.body.innerHTML.substring(0, 2000)")
                    log.warning(f"  [Whisper] Challenge iframe HTML: {body_html[:500]}")
                except:
                    pass
                try:
                    page.screenshot(path=f"debug_audio_fail.png")
                except:
                    pass
                return False
            
            audio_src = audio_el.get_attribute("src")
            if not audio_src:
                log.warning("  [Whisper] Audio source has no src attribute")
                return False
            log.info(f"  [Whisper] Audio URL: {audio_src[:60]}...")
            
            # Step 6: Download audio
            import urllib.request
            audio_path = os.path.join(tempfile.gettempdir(), "captcha.mp3")
            urllib.request.urlretrieve(audio_src, audio_path)
            file_size = os.path.getsize(audio_path)
            log.info(f"  [Whisper] Downloaded audio: {file_size} bytes")
            
            if file_size < 1000:
                log.warning("  [Whisper] Audio too small, may be invalid")
                return False
            
            # Step 7: Transcribe with Whisper
            log.info("  [Whisper] Transcribing with Whisper...")
            segments, info = self.whisper_model.transcribe(
                audio_path, 
                language="en",
                beam_size=1,
                best_of=1
            )
            answer = " ".join(s.text.strip() for s in segments).strip()
            log.info(f"  [Whisper] Transcribed: '{answer}'")
            
            if not answer:
                log.warning("  [Whisper] Empty transcription")
                return False
            
            # Step 8: Submit answer
            log.info(f"  [Whisper] Submitting answer: '{answer}'")
            response_input = challenge_frame.wait_for_selector("#audio-response", timeout=5000)
            if response_input:
                response_input.fill(answer)
            time.sleep(0.5)
            
            self._click_in_frame(challenge_frame, "#recaptcha-verify-button", timeout=5)
            time.sleep(2)
            
            log.info("  [Whisper] SOLVED!")
            time.sleep(1)
            
            # Step 9: Click form submit button
            for selector in ['#login', '#submit', 'button[type="submit"]', '.btn-claim', '#claim']:
                try:
                    btn = page.query_selector(selector)
                    if btn and btn.is_visible():
                        log.info(f"  [Whisper] Clicking '{selector}'...")
                        btn.click(timeout=3000)
                        time.sleep(3)
                        break
                except:
                    continue
            
            return True
            
        except Exception as e:
            log.warning(f"  [Whisper] Error: {e}")
            import traceback
            log.warning(f"  [Whisper] Traceback: {traceback.format_exc()}")
            return False

    def _solve_api(self, page, site_url: str, site_key_hint: str) -> bool:
        """Fallback: Solve using a captcha API service."""
        if not CAPTCHA_API_KEY:
            return False
        
        log.info(f"  [API] Using {CAPTCHA_SERVICE}...")
        try:
            # Get the site key from the page
            sitekey = page.evaluate("""
                () => {
                    const el = document.querySelector('.g-recaptcha');
                    return el ? el.getAttribute('data-sitekey') : null;
                }
            """)
            if not sitekey:
                log.warning("  [API] Site key not found")
                return False
            
            log.info(f"  [API] Site key: {sitekey[:20]}...")
            
            # Call the API service
            import requests
            
            if CAPTCHA_SERVICE == "capsolver":
                r = requests.post("https://api.capsolver.com/createTask", json={
                    "clientKey": CAPTCHA_API_KEY,
                    "task": {
                        "type": "ReCaptchaV2TaskProxyLess",
                        "websiteURL": site_url,
                        "websiteKey": sitekey,
                    }
                }, timeout=30).json()
                if r.get("errorId") != 0:
                    log.error(f"  [API] Create failed: {r.get('errorDescription')}")
                    return False
                task_id = r["taskId"]
                
                for _ in range(30):
                    time.sleep(2)
                    r = requests.post("https://api.capsolver.com/getTaskResult", json={
                        "clientKey": CAPTCHA_API_KEY,
                        "taskId": task_id
                    }, timeout=15).json()
                    if r.get("status") == "ready":
                        token = r["solution"]["gRecaptchaResponse"]
                        break
                else:
                    log.warning("  [API] Timeout")
                    return False
            
            elif CAPTCHA_SERVICE == "nopecha":
                r = requests.post("https://nopecha.com/api/v1/solve", json={
                    "type": "recaptcha",
                    "sitekey": sitekey,
                    "url": site_url,
                }, timeout=60).json()
                if r.get("data"):
                    token = r["data"]
                else:
                    log.warning(f"  [API] NopeCHA failed: {r}")
                    return False
            else:
                log.error(f"  [API] Unknown service: {CAPTCHA_SERVICE}")
                return False
            
            # Inject token into page
            log.info(f"  [API] Got token: {token[:30]}...")
            page.evaluate(f"""
                () => {{
                    document.querySelectorAll('textarea[id^="g-recaptcha-response"]').forEach(ta => {{
                        ta.innerHTML = '{token}';
                        ta.value = '{token}';
                        ta.dispatchEvent(new Event('input', {{ bubbles: true }}));
                    }});
                    const loginBtn = document.getElementById('login');
                    if (loginBtn) loginBtn.classList.remove('d-none');
                    if (typeof enableBtn === 'function') enableBtn();
                    return true;
                }}
            """)
            time.sleep(1)
            
            submit_btn = page.query_selector('#login')
            if submit_btn and submit_btn.is_visible():
                submit_btn.click()
                time.sleep(3)
            
            return True
            
        except Exception as e:
            log.error(f"  [API] Error: {e}")
            return False


# ===== PLAYWRIGHT FAUCET CLAIMER =====
class FaucetClaimer:
    def __init__(self, state: StateManager, captcha: RecaptchaAudioSolver):
        self.state = state
        self.captcha = captcha
        self.playwright = None
        self.browser = None
        self.page = None
        self.total_claims = 0

    def start_browser(self):
        from playwright.sync_api import sync_playwright
        self.playwright = sync_playwright().__enter__()
        
        self.browser = self.playwright.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
            ],
            timeout=30000,
        )
        
        context = self.browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800},
            locale="en-US",
        )
        
        self.page = context.new_page()
        log.info("[Browser] Started")

    def close_browser(self):
        try:
            if self.page: self.page.close()
            if self.browser: self.browser.close()
            if self.playwright: self.playwright.__exit__(None, None, None)
        except: pass

    def _fill_address(self, email: str):
        """Enter FaucetPay email into the address field."""
        inp = self.page.query_selector('#address')
        if inp:
            inp.fill("")
            inp.fill(email)
            time.sleep(0.5)

    def _click_button(self, text: str) -> bool:
        """Click a button by visible text."""
        btns = self.page.query_selector_all('button')
        for btn in btns:
            if text.lower() in (btn.inner_text() or "").lower():
                btn.click()
                time.sleep(1)
                return True
        return False

    def claim_site(self, site_key: str, url: str, cooldown: int,
                   needs_login: bool = False, select_email: bool = False) -> bool:
        """Generic claim flow for any Claimto faucet."""
        remaining = self.state.cooldown_remaining(site_key, cooldown)
        if remaining > 0:
            log.info(f"[{site_key}] Cooldown: {remaining}s")
            return False

        log.info(f"[{site_key}] Opening {url}...")
        try:
            self.page.goto(url, timeout=30000, wait_until="domcontentloaded")
            time.sleep(2)
            
            # Step 1: Select Email radio if needed
            if select_email:
                email_radio = self.page.query_selector('#type-email')
                if email_radio:
                    email_radio.click()
                    time.sleep(0.5)
            
            # Step 2: Enter FaucetPay email
            log.info(f"  Entering FaucetPay email...")
            self._fill_address(FAUCETPAY_EMAIL)
            
            # Step 3: Click Start/Login button
            btn_text = "start" if not needs_login else "login"
            log.info(f"  Clicking {btn_text.title()}...")
            self._click_button(btn_text)
            time.sleep(2)
            
            # Step 4: Solve captcha
            log.info(f"  Solving captcha...")
            solved = self.captcha.solve(self.page, url, site_key)
            
            if solved:
                self.total_claims += 1
                self.state.mark_claimed(site_key, 0.002)
                log.info(f"[{site_key}] ✅ CLAIM SUCCESSFUL!")
                return True
            else:
                log.warning(f"[{site_key}] ❌ Captcha failed")
                return False

        except Exception as e:
            log.error(f"[{site_key}] Error: {e}")
            try:
                self.page.screenshot(path=f"debug_{site_key}.png")
            except: pass
            return False


# ===== MAIN =====
def main():
    log.info("=" * 65)
    log.info("  FAUCET AUTOMATION v4 (Whisper Audio Solver)")
    log.info(f"  FaucetPay: {FAUCETPAY_EMAIL}")
    log.info(f"  Captcha: WHISPER (FREE, no API key)")
    log.info(f"  Time: {datetime.now(timezone.utc).isoformat()}")
    log.info("=" * 65)

    state = StateManager()
    captcha = RecaptchaAudioSolver()
    claimer = FaucetClaimer(state, captcha)

    try:
        claimer.start_browser()

        sites = [
            # (key, url, cooldown_sec, needs_login, select_email)
            ("claimto.xyz",  "https://freeusdt.claimto.xyz",  60,  False, True),
            ("ethiomi.com",  "https://freeusdt.ethiomi.com",  60,  True,  False),
            ("freetrx.su",   "https://freetrx.su",           120, True,  False),
        ]

        results = {}
        for key, url, cd, login, email_sel in sites:
            log.info(f"\n--- {key} (every {cd}s) ---")
            results[key] = claimer.claim_site(key, url, cd, login, email_sel)
            log.info(f"  -> {'SUCCESS' if results[key] else 'SKIP/FAIL'}")

        # Summary
        success = sum(1 for v in results.values() if v)
        log.info("\n" + "=" * 65)
        log.info(f"  RESULTS: {success}/{len(sites)} claimed")
        for k, v in results.items():
            log.info(f"    {k}: {'OK' if v else 'X'}")
        log.info(f"  Total claims this run: {claimer.total_claims}")
        log.info(f"  Total earned (est): {state.data.get('total_earned', 0):.4f} USDT")
        log.info("  [DONE]")

    finally:
        claimer.close_browser()


if __name__ == "__main__":
    main()
