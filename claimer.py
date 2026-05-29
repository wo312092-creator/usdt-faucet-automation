#!/usr/bin/env python3
"""
USDT / TRX Faucet Automation Bot - v2 (Playwright)
===================================================
REALITY-BASED REWRITE:
  - These sites pay via FaucetPay, NOT direct wallet
  - They use Google reCAPTCHA v2, NOT text captchas
  - They require Playwright browser automation, NOT curl_cffi
  - Claims happen every 1-2 minutes, NOT every hour

Supported sites:
  1. FreeTether (claimto.xyz) - USDT - every 1 min - FaucetPay
  2. Tether faucet (ethiomi.com) - USDT - every 1 min - FaucetPay (login)
  3. FreeTRX.su - TRX - every 2 min - FaucetPay (PROVEN WORKING)

Requires:
  - FAUCETPAY_EMAIL (GitHub secret)
  - FAUCETPAY_PASS  (GitHub secret, for login-required sites)
  - CAPTCHA_API_KEY (optional - CapSolver/2Captcha/NopeCHA)

Author: wo312092-creator
"""

import os, sys, json, time, base64, re, logging
from datetime import datetime, timezone
from typing import Optional

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
log = logging.getLogger(__name__)

# ===== CONFIG (from environment secrets) =====
FAUCETPAY_EMAIL = os.environ.get("FAUCETPAY_EMAIL", "").strip()
FAUCETPAY_PASS = os.environ.get("FAUCETPAY_PASS", "").strip()
CAPTCHA_API_KEY = os.environ.get("CAPTCHA_API_KEY", "").strip()
CAPTCHA_SERVICE = os.environ.get("CAPTCHA_SERVICE", "capsolver").strip().lower()

if not FAUCETPAY_EMAIL:
    log.error("[FATAL] FAUCETPAY_EMAIL not set! Add as GitHub secret.")
    sys.exit(1)

# State file
STATE_FILE = "claim_state.json"


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

    def get_cooldown_remaining(self, site_key: str, cooldown: int) -> int:
        last = self.get_last_claim(site_key)
        elapsed = time.time() - last
        if elapsed >= cooldown:
            return 0
        return int(cooldown - elapsed)


# ===== CAPTCHA SOLVER =====
class CaptchaSolver:
    """Solve Google reCAPTCHA v2 using configured service."""

    def __init__(self):
        self.api_key = CAPTCHA_API_KEY
        self.service = CAPTCHA_SERVICE
        self.solver_available = bool(self.api_key)
        if self.solver_available:
            log.info(f"[Captcha] Using {self.service.upper()} (API key: {self.api_key[:8]}...)")
        else:
            log.info("[Captcha] No API key set. Will try browser-based solving.")

    def solve_recaptcha(self, site_key: str, page_url: str) -> Optional[str]:
        """Solve reCAPTCHA v2 and return the g-recaptcha-response token."""
        if not self.solver_available:
            log.warning("[Captcha] No API key - cannot solve reCAPTCHA")
            return None

        try:
            if self.service == "capsolver":
                return self._solve_capsolver(site_key, page_url)
            elif self.service == "2captcha":
                return self._solve_2captcha(site_key, page_url)
            elif self.service == "nopecha":
                return self._solve_nopecha(site_key, page_url)
            else:
                log.error(f"[Captcha] Unknown service: {self.service}")
                return None
        except Exception as e:
            log.error(f"[Captcha] Solve failed: {e}")
            return None

    def _solve_capsolver(self, site_key: str, page_url: str) -> Optional[str]:
        """Solve via CapSolver (accepts USDT/BNB/ETH crypto payments)."""
        import requests
        # Step 1: Create task
        task_payload = {
            "clientKey": self.api_key,
            "task": {
                "type": "ReCaptchaV2TaskProxyLess",
                "websiteURL": page_url,
                "websiteKey": site_key,
            }
        }
        r = requests.post("https://api.capsolver.com/createTask", json=task_payload, timeout=30)
        resp = r.json()
        if resp.get("errorId") != 0:
            log.error(f"[CapSolver] Create failed: {resp.get('errorDescription', 'unknown')}")
            return None
        task_id = resp.get("taskId")

        # Step 2: Poll for result
        for attempt in range(30):
            time.sleep(2)
            r = requests.post("https://api.capsolver.com/getTaskResult", json={
                "clientKey": self.api_key,
                "taskId": task_id
            }, timeout=15)
            resp = r.json()
            if resp.get("status") == "ready":
                return resp.get("solution", {}).get("gRecaptchaResponse")
            elif resp.get("status") == "failed":
                log.error(f"[CapSolver] Task failed")
                return None
        log.error("[CapSolver] Timeout after 60s")
        return None

    def _solve_2captcha(self, site_key: str, page_url: str) -> Optional[str]:
        """Solve via 2Captcha."""
        import requests
        r = requests.post("https://2captcha.com/in.php", data={
            "key": self.api_key,
            "method": "userrecaptcha",
            "googlekey": site_key,
            "pageurl": page_url,
            "json": 1,
        }, timeout=30)
        resp = r.json()
        if resp.get("status") != 1:
            log.error(f"[2Captcha] Create failed: {resp}")
            return None
        captcha_id = resp.get("request")

        for attempt in range(30):
            time.sleep(3)
            r = requests.get("https://2captcha.com/res.php", params={
                "key": self.api_key,
                "action": "get",
                "id": captcha_id,
                "json": 1,
            }, timeout=15)
            resp = r.json()
            if resp.get("status") == 1:
                return resp.get("request")
            elif resp.get("request") != "CAPCHA_NOT_READY":
                log.error(f"[2Captcha] Failed: {resp.get('request')}")
                return None
        log.error("[2Captcha] Timeout after 90s")
        return None

    def _solve_nopecha(self, site_key: str, page_url: str) -> Optional[str]:
        """Solve via NopeCHA API (100 free solves on signup)."""
        import requests
        r = requests.post("https://nopecha.com/api/v1/solve", json={
            "type": "recaptcha",
            "sitekey": site_key,
            "url": page_url,
        }, headers={"Authorization": f"Bearer {self.api_key}"}, timeout=30)
        resp = r.json()
        if resp.get("error"):
            log.error(f"[NopeCHA] Failed: {resp.get('error')}")
            return None
        return resp.get("data")
    
    def inject_token(self, page, token: str):
        """Inject solved captcha token into the page and trigger callbacks."""
        js = f"""
        (() => {{
            // Find the g-recaptcha textarea
            const textareas = document.querySelectorAll('textarea');
            let ta = null;
            for (const t of textareas) {{
                if (t.id && t.id.startsWith('g-recaptcha-response')) {{
                    ta = t;
                    break;
                }}
            }}
            if (!ta) {{
                // Try direct injection
                const frames = document.querySelectorAll('iframe[title="reCAPTCHA"]');
                if (frames.length > 0) {{
                    console.log('reCAPTCHA iframe found, trying API');
                }}
                return false;
            }}
            
            // Set the response
            ta.innerHTML = '{token}';
            ta.value = '{token}';
            ta.textContent = '{token}';
            
            // Trigger callback if defined
            const captchaInput = document.getElementById('captcha');
            if (captchaInput) {{
                captchaInput.value = 'solved';
                const event = new Event('change', {{ bubbles: true }});
                captchaInput.dispatchEvent(event);
            }}
            
            // Find and click the submit button (enableBtn callback should be defined)
            const submitBtn = document.getElementById('login');
            if (submitBtn && submitBtn.classList.contains('d-none')) {{
                submitBtn.classList.remove('d-none');
            }}
            
            // Try window callbacks
            if (typeof enableBtn === 'function') {{
                enableBtn();
            }}
            
            return true;
        }})()
        """
        return page.evaluate(js)


# ===== PLAYWRIGHT FAUCET CLAIMER =====
class FaucetClaimer:
    """Claim from Claimto-network faucets using Playwright."""

    def __init__(self, state: StateManager, captcha: CaptchaSolver):
        self.state = state
        self.captcha = captcha
        self.playwright = None
        self.browser = None
        self.page = None
        self.total_sites_processed = 0
        self.total_claims_made = 0

    def _import_playwright(self):
        """Import playwright with auto-install."""
        try:
            from playwright.sync_api import sync_playwright
            return sync_playwright
        except ImportError:
            log.info("Playwright not installed. Installing...")
            os.system(f"{sys.executable} -m pip install playwright -q")
            os.system(f"{sys.executable} -m playwright install chromium --with-deps -q")
            from playwright.sync_api import sync_playwright
            return sync_playwright

    def start_browser(self):
        """Launch Playwright browser."""
        sync_playwright = self._import_playwright()
        self.playwright = sync_playwright().__enter__()
        
        # Launch Chromium with stealth settings
        self.browser = self.playwright.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-web-security",
                "--disable-features=IsolateOrigins,site-per-process",
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
            timezone_id="America/New_York",
        )
        
        self.page = context.new_page()
        log.info("[Browser] Started Playwright Chromium")

    def close_browser(self):
        """Clean up browser resources."""
        try:
            if self.page:
                self.page.close()
            if self.browser:
                self.browser.close()
            if self.playwright:
                self.playwright.__exit__(None, None, None)
        except:
            pass

    def solve_and_submit(self, site_key: str, page_url: str) -> bool:
        """
        Wait for captcha modal, solve reCAPTCHA, and submit.
        Returns True if claim was successful.
        """
        log.info("  Solving reCAPTCHA...")

        # Try API-based solving first
        if self.captcha.solver_available:
            # Get the reCAPTCHA site key from the page
            sitekey = self.page.evaluate("""
                () => {
                    const el = document.querySelector('.g-recaptcha');
                    return el ? el.getAttribute('data-sitekey') : null;
                }
            """)
            
            if sitekey:
                log.info(f"  Found reCAPTCHA sitekey: {sitekey[:20]}...")
                token = self.captcha.solve_recaptcha(sitekey, page_url)
                if token:
                    log.info(f"  Got captcha token: {token[:30]}...")
                    # Inject token into page
                    try:
                        self.page.evaluate(f"""
                            // Inject token into all g-recaptcha-response textareas
                            document.querySelectorAll('textarea[id^="g-recaptcha-response"]').forEach(ta => {{
                                ta.innerHTML = '{token}';
                                ta.value = '{token}';
                                ta.textContent = '{token}';
                                ta.dispatchEvent(new Event('input', {{ bubbles: true }}));
                            }});
                            // Trigger callback
                            if (typeof ___grecaptcha_cfg !== 'undefined') {{
                                const clients = ___grecaptcha_cfg.clients;
                                for (const [key, client] of Object.entries(clients || {{}})) {{
                                    if (client && client.callback) {{
                                        try {{ client.callback('{token}'); }} catch(e) {{}}
                                    }}
                                }}
                            }}
                            // Enable submit button
                            const loginBtn = document.getElementById('login');
                            if (loginBtn) loginBtn.classList.remove('d-none');
                            if (typeof enableBtn === 'function') enableBtn();
                        """)
                        time.sleep(1)
                        
                        # Click submit
                        submit_btn = self.page.query_selector('#login')
                        if submit_btn and submit_btn.is_visible():
                            submit_btn.click()
                            log.info("  Submitted captcha token")
                            time.sleep(3)
                            return True
                    except Exception as e:
                        log.warning(f"  Token injection failed: {e}")
        
        # Fallback: Browser-based manual interaction
        log.info("  Trying browser-based captcha interaction...")
        try:
            # Look for the captcha iframe
            captcha_frame = self.page.frame_locator('iframe[title="reCAPTCHA"]').first
            if captcha_frame:
                # Click the reCAPTCHA checkbox
                captcha_frame.locator('.recaptcha-checkbox-border').click(timeout=5000)
                time.sleep(2)
                
                # Check if solved (checkbox becomes checked)
                checked = captcha_frame.locator('.recaptcha-checkbox-checked').count()
                if checked > 0:
                    log.info("  reCAPTCHA solved via browser click!")
                    time.sleep(1)
                    # Submit
                    submit_btn = self.page.query_selector('#login')
                    if submit_btn:
                        submit_btn.click()
                        time.sleep(3)
                        return True
        except Exception as e:
            log.warning(f"  Browser captcha click failed: {e}")
        
        log.warning("  reCAPTCHA could not be solved automatically")
        return False

    def claim_freeusdt_claimto(self) -> bool:
        """Claim from FreeTether (claimto.xyz) - USDT, every 1 min."""
        site_key = "claimto.xyz"
        url = "https://freeusdt.claimto.xyz"
        
        cooldown = self.state.get_cooldown_remaining(site_key, 60)
        if cooldown > 0:
            log.info(f"[{site_key}] Cooldown: {cooldown}s remaining")
            return False
        
        log.info(f"[{site_key}] Navigating...")
        try:
            self.page.goto(url, timeout=30000, wait_until="domcontentloaded")
            time.sleep(2)
            
            # Step 1: Select "Email" radio (should be default)
            log.info("  Selecting Email option...")
            email_radio = self.page.query_selector('#type-email')
            if email_radio:
                email_radio.click()
                time.sleep(0.5)
            
            # Step 2: Enter FaucetPay email
            log.info(f"  Entering FaucetPay email: {FAUCETPAY_EMAIL}")
            address_input = self.page.query_selector('#address')
            if address_input:
                address_input.fill("")
                address_input.fill(FAUCETPAY_EMAIL)
                time.sleep(0.5)
            
            # Step 3: Click "Start" button - opens captcha modal
            log.info("  Clicking Start...")
            start_btn = self.page.query_selector('button:has-text("Start")')
            if start_btn:
                start_btn.click()
                time.sleep(2)
            else:
                log.warning("  Start button not found!")
                return False
            
            # Step 4: Solve captcha + submit
            result = self.solve_and_submit(site_key, url)
            if result:
                log.info(f"[{site_key}] ✅ Claim submitted!")
                self.total_claims_made += 1
                self.state.mark_claimed(site_key, 0.002)
                return True
            
            return False

        except Exception as e:
            log.error(f"[{site_key}] Error: {e}")
            self._save_screenshot(f"error_{site_key}")
            return False

    def claim_tether_ethiomi(self) -> bool:
        """Claim from Tether faucet (ethiomi.com) - USDT, every 1 min, login required."""
        site_key = "ethiomi.com"
        url = "https://freeusdt.ethiomi.com"
        
        cooldown = self.state.get_cooldown_remaining(site_key, 60)
        if cooldown > 0:
            log.info(f"[{site_key}] Cooldown: {cooldown}s remaining")
            return False
        
        log.info(f"[{site_key}] Navigating...")
        try:
            self.page.goto(url, timeout=30000, wait_until="domcontentloaded")
            time.sleep(2)
            
            # This site has a "LOGIN" button - requires FaucetPay email + pass
            log.info("  Entering FaucetPay email...")
            address_input = self.page.query_selector('#address')
            if address_input:
                address_input.fill("")
                address_input.fill(FAUCETPAY_EMAIL)
                time.sleep(0.5)
            
            # Click LOGIN button
            log.info("  Clicking LOGIN...")
            login_btn = self.page.query_selector('button:has-text("Login")')
            if login_btn:
                login_btn.click()
                time.sleep(2)
            else:
                log.warning("  LOGIN button not found!")
                return False
            
            # Solve captcha + submit
            result = self.solve_and_submit(site_key, url)
            if result:
                log.info(f"[{site_key}] ✅ Claim submitted!")
                self.total_claims_made += 1
                self.state.mark_claimed(site_key, 0.002)
                return True
            
            return False

        except Exception as e:
            log.error(f"[{site_key}] Error: {e}")
            self._save_screenshot(f"error_{site_key}")
            return False

    def claim_freetrx_su(self) -> bool:
        """Claim from FreeTRX.su - TRX, every 2 min, PROVEN WORKING."""
        site_key = "freetrx.su"
        url = "https://freetrx.su"
        
        cooldown = self.state.get_cooldown_remaining(site_key, 120)
        if cooldown > 0:
            log.info(f"[{site_key}] Cooldown: {cooldown}s remaining")
            return False
        
        log.info(f"[{site_key}] Navigating...")
        try:
            self.page.goto(url, timeout=30000, wait_until="domcontentloaded")
            time.sleep(2)
            
            # Enter FaucetPay email (field says "Enter Your Tron Address" but
            # site says "This faucet requires a FaucetPay account to claim")
            log.info(f"  Entering FaucetPay email...")
            address_input = self.page.query_selector('#address')
            if address_input:
                address_input.fill("")
                address_input.fill(FAUCETPAY_EMAIL)
                time.sleep(0.5)
            
            # Click Login button
            log.info("  Clicking Login...")
            login_btn = self.page.query_selector('button:has-text("Login")')
            if login_btn:
                login_btn.click()
                time.sleep(2)
            else:
                log.warning("  Login button not found!")
                return False
            
            # Solve captcha + submit
            result = self.solve_and_submit(site_key, url)
            if result:
                log.info(f"[{site_key}] ✅ Claim submitted!")
                self.total_claims_made += 1
                self.state.mark_claimed(site_key, 0.0)  # TRX value varies
                return True
            
            return False

        except Exception as e:
            log.error(f"[{site_key}] Error: {e}")
            self._save_screenshot(f"error_{site_key}")
            return False

    def _save_screenshot(self, name: str):
        """Save debug screenshot."""
        try:
            self.page.screenshot(path=f"debug_{name}_{int(time.time())}.png")
        except:
            pass


# ===== MAIN =====
def main():
    log.info("=" * 65)
    log.info("  FAUCET AUTOMATION v2 (REALITY-BASED)")
    log.info(f"  FaucetPay: {FAUCETPAY_EMAIL}")
    log.info(f"  Captcha: {'API KEY SET' if CAPTCHA_API_KEY else 'NO API KEY - browser fallback only'}")
    log.info(f"  Time: {datetime.now(timezone.utc).isoformat()}")
    log.info("=" * 65)

    state = StateManager()
    captcha = CaptchaSolver()
    claimer = FaucetClaimer(state, captcha)

    try:
        claimer.start_browser()
        
        # ===== SITE 1: FreeTether (USDT) =====
        log.info("\n--- Site 1: FreeTether (claimto.xyz) - USDT / 1 min ---")
        result1 = claimer.claim_freeusdt_claimto()
        log.info(f"  Result: {'✅ SUCCESS' if result1 else '❌ FAILED/SKIPPED'}")
        
        # ===== SITE 2: Tether faucet (USDT) =====
        log.info("\n--- Site 2: Tether faucet (ethiomi.com) - USDT / 1 min ---")
        result2 = claimer.claim_tether_ethiomi()
        log.info(f"  Result: {'✅ SUCCESS' if result2 else '❌ FAILED/SKIPPED'}")
        
        # ===== SITE 3: FreeTRX.su (TRX) - PROVEN =====
        log.info("\n--- Site 3: FreeTRX.su - TRX / 2 min (PROVEN) ---")
        result3 = claimer.claim_freetrx_su()
        log.info(f"  Result: {'✅ SUCCESS' if result3 else '❌ FAILED/SKIPPED'}")
        
        # ===== SUMMARY =====
        log.info("\n" + "=" * 65)
        log.info("  RESULTS SUMMARY")
        log.info("=" * 65)
        results = [("claimto.xyz", result1), ("ethiomi.com", result2), ("freetrx.su", result3)]
        for name, ok in results:
            log.info(f"    {name}: {'✅ SUCCESS' if ok else '❌ SKIPPED/FAILED'}")
        
        success_count = sum(1 for _, ok in results if ok)
        log.info(f"\n  Sites claimed: {success_count}/{len(results)}")
        log.info(f"  Total claims this run: {claimer.total_claims_made}")
        log.info(f"  Total all-time earned (est): {state.data.get('total_earned', 0):.4f} USDT")
        log.info(f"\n  Next run will check cooldowns automatically")
        log.info("  [DONE]")

    finally:
        claimer.close_browser()


if __name__ == "__main__":
    main()
