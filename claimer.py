"""
USDT Faucet Automation Bot
============================
Automatically claims from USDT/Tether faucet sites using:
  - curl_cffi (Chrome TLS fingerprint impersonation)
  - ddddocr (FREE text captcha OCR, no API key)
  - GitHub Actions (hourly cron)

Supports:
  1. FreeTether (freeusdt.claimto.xyz) - $2.88/day
  2. Tether faucet (freeusdt.ethiomi.com) - $7.20/day

Wallet address stored as GitHub secret: USDT_WALLET (TRC20)
"""

import os, sys, json, time, re, hashlib, logging
from datetime import datetime, timezone
from typing import Optional

# ===== CONFIG =====
USDT_WALLET = os.environ.get("USDT_WALLET", "").strip()
if not USDT_WALLET:
    print("[FATAL] USDT_WALLET not set! Add it as a GitHub secret.")
    sys.exit(1)

# How often each site can be claimed (in seconds)
CLAIM_COOLDOWNS = {
    "freeusdt.claimto.xyz": 3600,    # 1 hour
    "freeusdt.ethiomi.com": 3600,    # 1 hour
}

# State file to track last claim times (persisted between runs)
STATE_FILE = "claim_state.json"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
log = logging.getLogger(__name__)


# ===== HELPER: Import with fallback =====
def import_curl_cffi():
    """Import curl_cffi with pip auto-install."""
    try:
        from curl_cffi import requests as curl_requests
        return curl_requests
    except ImportError:
        log.info("curl_cffi not installed, installing...")
        os.system(f"{sys.executable} -m pip install curl-cffi -q")
        from curl_cffi import requests as curl_requests
        return curl_requests

def import_ddddocr():
    """Import ddddocr with pip auto-install."""
    try:
        import ddddocr
        return ddddocr
    except ImportError:
        log.info("ddddocr not installed, installing...")
        os.system(f"{sys.executable} -m pip install ddddocr -q")
        import ddddocr
        return ddddocr


# ===== CAPTCHA SOLVER =====
class CaptchaSolver:
    """FREE text captcha solver using ddddocr (14k stars, no API key needed)."""
    
    def __init__(self):
        ddddocr_module = import_ddddocr()
        self.ocr = ddddocr_module.DdddOcr(beta=True)
        log.info("[Captcha] ddddocr initialized (FREE, 95%+ accuracy on text captchas)")
    
    def solve_from_bytes(self, image_bytes: bytes) -> str:
        """Solve a text captcha from raw image bytes."""
        try:
            result = self.ocr.classification(image_bytes)
            return result.strip()
        except Exception as e:
            log.error(f"[Captcha] OCR failed: {e}")
            return ""
    
    def solve_from_url(self, session, image_url: str, referer: str = "") -> str:
        """Download captcha image from URL and solve it."""
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Referer": referer,
            }
            r = session.get(image_url, headers=headers, impersonate="chrome110", timeout=30)
            if r.status_code == 200:
                return self.solve_from_bytes(r.content)
            log.warning(f"[Captcha] Failed to download image: {r.status_code}")
            return ""
        except Exception as e:
            log.error(f"[Captcha] Download failed: {e}")
            return ""


# ===== STATE MANAGER =====
class StateManager:
    """Track last claim times to respect cooldowns."""
    
    def __init__(self, path: str = STATE_FILE):
        self.path = path
        self.data = {}
        self._load()
    
    def _load(self):
        try:
            with open(self.path, "r") as f:
                self.data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            self.data = {"claims": {}}
    
    def save(self):
        with open(self.path, "w") as f:
            json.dump(self.data, f, indent=2)
    
    def can_claim(self, site_key: str) -> tuple[bool, int]:
        """Check if enough time has passed since last claim.
        Returns (can_claim, seconds_remaining)."""
        cooldown = CLAIM_COOLDOWNS.get(site_key, 3600)
        last = self.data.get("claims", {}).get(site_key, 0)
        elapsed = time.time() - last
        if elapsed >= cooldown:
            return True, 0
        return False, int(cooldown - elapsed)
    
    def mark_claimed(self, site_key: str):
        """Record a successful claim."""
        if "claims" not in self.data:
            self.data["claims"] = {}
        self.data["claims"][site_key] = time.time()
        self.save()


# ===== SITE CLAIMERS =====

def claim_freeusdt_claimto_xyz(session, captcha_solver, state):
    """Claim from freeusdt.claimto.xyz - $2.88/day."""
    site_key = "freeusdt.claimto.xyz"
    base_url = "https://freeusdt.claimto.xyz"
    
    can, remaining = state.can_claim(site_key)
    if not can:
        log.info(f"[{site_key}] On cooldown. {remaining}s remaining.")
        return False
    
    log.info(f"[{site_key}] Attempting claim...")
    try:
        # Step 1: Get the main page
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": base_url,
        }
        r = session.get(base_url, headers=headers, impersonate="chrome110", timeout=30)
        if r.status_code != 200:
            log.warning(f"[{site_key}] Page load failed: {r.status_code}")
            return False
        
        html = r.text
        
        # Step 2: Extract captcha image URL (common patterns)
        captcha_url = None
        # Pattern 1: <img src="captcha.php" or similar
        match = re.search(r'<img[^>]*src=["\']([^"\']*captcha[^"\']*)["\']', html, re.IGNORECASE)
        if match:
            captcha_url = match.group(1)
            if not captcha_url.startswith("http"):
                captcha_url = base_url + captcha_url
        
        # Pattern 2: simple text captcha shown as <span> or <div>
        captcha_text = ""
        if not captcha_url:
            # Look for inline captcha text like "2 + 3 = ?"
            match = re.search(r'(\d+\s*[\+\-\*]\s*\d+\s*=\s*\?)', html)
            if match:
                expr = match.group(1).replace("?", "").strip()
                try:
                    captcha_text = str(eval(expr))
                    log.info(f"[{site_key}] Solved math captcha: {expr} = {captcha_text}")
                except:
                    pass
        
        # Solve captcha if we found an image
        if captcha_url:
            log.info(f"[{site_key}] Found captcha image: {captcha_url[:60]}...")
            captcha_text = captcha_solver.solve_from_url(session, captcha_url, base_url)
            log.info(f"[{site_key}] Captcha solved: {captcha_text}")
        
        # Step 3: Extract form fields and submit
        # Try to find form action URL
        form_action = base_url
        match = re.search(r'<form[^>]*action=["\']([^"\']*)["\']', html)
        if match:
            action = match.group(1)
            if action.startswith("/"):
                form_action = base_url + action
            elif action.startswith("http"):
                form_action = action
        
        # Extract any hidden fields
        form_data = {}
        for hidden in re.finditer(r'<input[^>]*type=["\']hidden["\'][^>]*>', html):
            name_match = re.search(r'name=["\']([^"\']*)["\']', hidden.group(0))
            value_match = re.search(r'value=["\']([^"\']*)["\']', hidden.group(0))
            if name_match:
                form_data[name_match.group(1)] = value_match.group(1) if value_match else ""
        
        # Add wallet and captcha
        form_data["wallet"] = USDT_WALLET
        form_data["address"] = USDT_WALLET
        if captcha_text:
            # Try common captcha field names
            for field in ["captcha", "code", "captcha_code", "security_code", "verify"]:
                if field not in form_data:
                    form_data[field] = captcha_text
                    break
        
        # Step 4: Submit claim
        log.info(f"[{site_key}] Submitting claim with wallet: {USDT_WALLET[:8]}...")
        r = session.post(form_action, data=form_data, headers={
            **headers,
            "Content-Type": "application/x-www-form-urlencoded",
            "Referer": base_url,
        }, impersonate="chrome110", timeout=30)
        
        # Step 5: Check result
        resp_text = r.text.lower()
        if any(word in resp_text for word in ["success", "claimed", "sent", "reward", "congratulations"]):
            log.info(f"[{site_key}] CLAIM SUCCESSFUL!")
            state.mark_claimed(site_key)
            return True
        elif "already" in resp_text:
            log.info(f"[{site_key}] Already claimed recently.")
            state.mark_claimed(site_key)  # Still mark to avoid retries
            return True
        else:
            log.warning(f"[{site_key}] Claim may have failed. Response: {resp_text[:200]}")
            return False
            
    except Exception as e:
        log.error(f"[{site_key}] Error: {e}")
        return False


def claim_freeusdt_ethiomi_com(session, captcha_solver, state):
    """Claim from freeusdt.ethiomi.com - $7.20/day."""
    site_key = "freeusdt.ethiomi.com"
    base_url = "https://freeusdt.ethiomi.com"
    
    can, remaining = state.can_claim(site_key)
    if not can:
        log.info(f"[{site_key}] On cooldown. {remaining}s remaining.")
        return False
    
    log.info(f"[{site_key}] Attempting claim...")
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": base_url,
        }
        r = session.get(base_url, headers=headers, impersonate="chrome110", timeout=30)
        if r.status_code != 200:
            log.warning(f"[{site_key}] Page load failed: {r.status_code}")
            return False
        
        html = r.text
        captcha_text = ""
        
        # Check for captcha image
        captcha_url = None
        match = re.search(r'<img[^>]*src=["\']([^"\']*captcha[^"\']*)["\']', html, re.IGNORECASE)
        if match:
            captcha_url = match.group(1)
            if not captcha_url.startswith("http"):
                captcha_url = base_url + captcha_url
        
        # Check for math captcha
        match = re.search(r'(\d+\s*[\+\-\*]\s*\d+\s*=\s*\?)', html)
        if match and not captcha_url:
            expr = match.group(1).replace("?", "").strip()
            try:
                captcha_text = str(eval(expr))
            except:
                pass
        
        if captcha_url:
            captcha_text = captcha_solver.solve_from_url(session, captcha_url, base_url)
            log.info(f"[{site_key}] Captcha solved: {captcha_text}")
        
        # Find form and submit
        form_action = base_url
        match = re.search(r'<form[^>]*action=["\']([^"\']*)["\']', html)
        if match:
            action = match.group(1)
            if action.startswith("/"):
                form_action = base_url + action
            elif action.startswith("http"):
                form_action = action
        
        form_data = {}
        for hidden in re.finditer(r'<input[^>]*type=["\']hidden["\'][^>]*>', html):
            name_match = re.search(r'name=["\']([^"\']*)["\']', hidden.group(0))
            value_match = re.search(r'value=["\']([^"\']*)["\']', hidden.group(0))
            if name_match:
                form_data[name_match.group(1)] = value_match.group(1) if value_match else ""
        
        form_data["wallet"] = USDT_WALLET
        form_data["address"] = USDT_WALLET
        if captcha_text:
            for field in ["captcha", "code", "captcha_code", "security_code", "verify"]:
                if field not in form_data:
                    form_data[field] = captcha_text
                    break
        
        log.info(f"[{site_key}] Submitting...")
        r = session.post(form_action, data=form_data, headers={
            **headers,
            "Content-Type": "application/x-www-form-urlencoded",
            "Referer": base_url,
        }, impersonate="chrome110", timeout=30)
        
        resp_text = r.text.lower()
        if any(word in resp_text for word in ["success", "claimed", "sent", "reward", "congratulations"]):
            log.info(f"[{site_key}] CLAIM SUCCESSFUL!")
            state.mark_claimed(site_key)
            return True
        elif "already" in resp_text:
            log.info(f"[{site_key}] Already claimed.")
            state.mark_claimed(site_key)
            return True
        else:
            log.warning(f"[{site_key}] Response: {resp_text[:200]}")
            return False
            
    except Exception as e:
        log.error(f"[{site_key}] Error: {e}")
        return False


# ===== MAIN =====
def main():
    log.info("=" * 60)
    log.info("USDT FAUCET AUTOMATION BOT")
    log.info(f"Wallet: {USDT_WALLET[:12]}...{USDT_WALLET[-4:]}")
    log.info(f"Time: {datetime.now(timezone.utc).isoformat()}")
    log.info("=" * 60)
    
    # Initialize
    curl = import_curl_cffi()
    session = curl.Session()
    captcha_solver = CaptchaSolver()
    state = StateManager()
    
    results = []
    
    # Site 1: FreeTether
    log.info("\n--- Site 1: freeusdt.claimto.xyz ($2.88/day) ---")
    r1 = claim_freeusdt_claimto_xyz(session, captcha_solver, state)
    results.append(("freeusdt.claimto.xyz", r1))
    
    # Site 2: Tether faucet
    log.info("\n--- Site 2: freeusdt.ethiomi.com ($7.20/day) ---")
    r2 = claim_freeusdt_ethiomi_com(session, captcha_solver, state)
    results.append(("freeusdt.ethiomi.com", r2))
    
    # Summary
    log.info("\n" + "=" * 60)
    log.info("RESULTS SUMMARY")
    log.info("=" * 60)
    for name, success in results:
        status = "SUCCESS" if success else "SKIPPED/FAILED"
        log.info(f"  {name}: {status}")
    
    success_count = sum(1 for _, s in results if s)
    log.info(f"\n{success_count}/{len(results)} sites claimed successfully")
    log.info(f"Total potential: ${success_count * 10.08 / 2:.2f}/day (both sites = $10.08/day)")
    log.info(f"Next run will check cooldowns automatically")
    log.info("[DONE]")

if __name__ == "__main__":
    main()
