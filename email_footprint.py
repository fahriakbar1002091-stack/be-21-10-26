"""
email_footprint.py — Breach Checker & Account Footprint Scanner
Sumber data:
  1. holehe        — cek email terdaftar di 120+ platform
  2. HaveIBeenPwned (HIBP) — cek data breach publik (gratis, no API key)
  3. Hudson Rock   — cek stealer logs / combolist (gratis endpoint)
"""

import asyncio
import re
import time
import json
import os
import urllib.request as _ur
from typing import Dict, List, Any, Optional

# ── Validasi email ────────────────────────────────────────────────────────────
_EMAIL_RE = re.compile(r'^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$')

def _valid_email(email: str) -> bool:
    return bool(_EMAIL_RE.match(email.strip()))


# ── 1. HOLEHE — Account footprint ────────────────────────────────────────────
async def _run_holehe(email: str) -> List[Dict]:
    """
    Jalankan holehe untuk cek email terdaftar di platform apa saja.
    Menggunakan API holehe yang benar: func(email, client, out)
    """
    results = []
    try:
        import httpx
        from holehe import core as hcore
        import holehe.modules as _hmod

        # Load semua modules via import_submodules
        modules = hcore.import_submodules(_hmod)
        funcs   = hcore.get_functions(modules)
        print(f"   ↳ holehe: {len(funcs)} platforms akan dicek...")

        found     = []
        not_found = []

        async with httpx.AsyncClient(
            timeout=15,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/125.0.0.0"}
        ) as client:
            # Jalankan semua fungsi secara concurrent
            import asyncio as _aio

            async def _call_one(func):
                out = []
                try:
                    await func(email, client, out)
                    return out[0] if out else None
                except Exception as ex:
                    return {"name": func.__name__, "exists": None, "error": str(ex)}

            tasks = [_call_one(f) for f in funcs]
            responses = await _aio.gather(*tasks, return_exceptions=True)

        for resp in responses:
            if resp is None or isinstance(resp, Exception):
                continue
            reg = bool(resp.get("exists") or False)
            entry = {
                "platform":      resp.get("name", "unknown"),
                "registered":    reg,
                "domain":        resp.get("domain", ""),
                "method":        resp.get("method", ""),
                "rateLimit":     resp.get("rateLimit", False),
                "emailrecovery": resp.get("emailrecovery"),
                "phoneNumber":   resp.get("phoneNumber"),
            }
            if reg:
                found.append(entry)
            else:
                not_found.append(entry)

        print(f"   ↳ holehe: {len(found)} platform ditemukan dari {len(found)+len(not_found)} dicek")
        results = found + not_found

    except ImportError:
        results = [{"platform": "holehe", "registered": None,
                    "error": "holehe tidak terinstall — pip install holehe"}]
    except Exception as e:
        import traceback
        print(f"   ❌ holehe error: {e}")
        print(traceback.format_exc())
        results = [{"platform": "holehe", "registered": None, "error": str(e)}]

    return results


# ── 2. HaveIBeenPwned — Breach check ─────────────────────────────────────────
def _check_hibp(email: str, hibp_api_key: str = "") -> Dict:
    """
    Cek HIBP untuk data breach.
    Gratis tanpa API key untuk /range endpoint (password hash check).
    Untuk breach by email butuh API key (berbayar $3.95/bulan).
    Fallback ke gratis jika tidak ada API key.
    """
    result = {
        "checked": False,
        "breached": False,
        "breach_count": 0,
        "breaches": [],
        "pastes": [],
        "error": None,
    }

    try:
        if hibp_api_key:
            # Full breach check dengan API key
            import urllib.parse
            encoded = urllib.parse.quote(email)
            req = _ur.Request(
                f"https://haveibeenpwned.com/api/v3/breachedaccount/{encoded}?truncateResponse=false",
                headers={
                    "hibp-api-key": hibp_api_key,
                    "User-Agent": "SocialRadarOSINT/1.0",
                    "Accept": "application/json",
                }
            )
            try:
                with _ur.urlopen(req, timeout=10) as resp:
                    data = json.loads(resp.read().decode())
                    result["checked"] = True
                    result["breached"] = True
                    result["breach_count"] = len(data)
                    result["breaches"] = [
                        {
                            "name": b.get("Name"),
                            "domain": b.get("Domain"),
                            "breach_date": b.get("BreachDate"),
                            "pwn_count": b.get("PwnCount"),
                            "data_classes": b.get("DataClasses", []),
                            "description": b.get("Description", "")[:200],
                        }
                        for b in data
                    ]
            except Exception as e:
                if "404" in str(e):
                    # 404 = email not found in any breach
                    result["checked"] = True
                    result["breached"] = False
                else:
                    result["error"] = str(e)
        else:
            # Tanpa API key — gunakan free endpoint untuk domain check
            # HIBP v3 free: check if domain has been pwned
            domain = email.split("@")[-1] if "@" in email else ""
            if domain:
                try:
                    req2 = _ur.Request(
                        f"https://haveibeenpwned.com/api/v3/breacheddomain/{domain}",
                        headers={"User-Agent": "SocialRadarOSINT/1.0"}
                    )
                    with _ur.urlopen(req2, timeout=8) as resp2:
                        data2 = json.loads(resp2.read().decode())
                        result["checked"] = True
                        result["domain_breached"] = True
                        result["domain_breach_info"] = f"Domain {domain} ditemukan di {len(data2)} breach"
                        result["note"] = "Domain-level check only (no API key). Untuk email-level check, tambah HIBP_API_KEY di .env"
                except:
                    result["checked"] = True
                    result["note"] = "Tambah HIBP_API_KEY di .env untuk full breach check per email"

    except Exception as e:
        result["error"] = str(e)

    return result


# ── 3. Hudson Rock — Stealer Logs / Combolist ─────────────────────────────────
def _check_hudson_rock(email: str) -> Dict:
    """
    Cek Hudson Rock Cavalier API untuk stealer logs.
    Free endpoint: https://cavalier.hudsonrock.com/api/json/v2/
    """
    result = {
        "checked": False,
        "compromised": False,
        "stealer_count": 0,
        "stealers": [],
        "error": None,
    }

    try:
        # Hudson Rock update endpoint (2024+)
        # Try new endpoint first, fallback ke old
        urls_to_try = [
            f"https://cavalier.hudsonrock.com/api/json/v2/search-by-login/osint-tools?email={encoded}",
            f"https://cavalier.hudsonrock.com/api/json/v2/osint-tools/search-by-email?email={encoded}",
        ]
        data = None
        for url in urls_to_try:
            try:
                req = _ur.Request(url, headers={
                    "User-Agent": "SocialRadarOSINT/1.0",
                    "Accept": "application/json",
                })
                with _ur.urlopen(req, timeout=10) as resp:
                    data = json.loads(resp.read().decode())
                break
            except Exception as url_e:
                if "404" in str(url_e):
                    continue
                raise

        result["checked"] = True

        if data.get("stealers") or data.get("data"):
            stealers = data.get("stealers") or data.get("data") or []
            result["compromised"] = len(stealers) > 0
            result["stealer_count"] = len(stealers)
            result["stealers"] = [
                {
                    "stealer_family": s.get("stealer_family", "Unknown"),
                    "date_compromised": s.get("date_compromised", ""),
                    "computer_name": s.get("computer_name", ""),
                    "operating_system": s.get("operating_system", ""),
                    "country": s.get("country", ""),
                    "antiviruses": s.get("antiviruses", []),
                    "passwords_count": s.get("passwords", 0),
                    "credentials_count": s.get("credentials", 0),
                }
                for s in stealers[:10]
            ]
        else:
            result["compromised"] = False

        print(f"   ↳ Hudson Rock: {'COMPROMISED' if result['compromised'] else 'CLEAN'} | {result['stealer_count']} logs")

    except Exception as e:
        err_str = str(e)
        if "429" in err_str:
            result["error"] = "Rate limit Hudson Rock — coba lagi dalam beberapa menit"
        elif "403" in err_str or "401" in err_str:
            result["error"] = "Hudson Rock API tidak tersedia saat ini"
        else:
            result["error"] = err_str
        print(f"   ⚠️ Hudson Rock error: {err_str}")

    return result


# ── 4. Hitung Risk Score berdasarkan semua findings ───────────────────────────
def _compute_email_risk(
    holehe_results: List[Dict],
    hibp_result: Dict,
    hudson_result: Dict,
) -> Dict:
    """Hitung risk score 0-100 dan kategori berdasarkan semua temuan."""
    score = 0
    flags = []
    positives = []

    # Platform count — semakin banyak platform, makin besar footprint
    registered = [r for r in holehe_results if r.get("registered")]
    platform_count = len(registered)

    if platform_count >= 20:
        score += 25
        flags.append(f"Footprint sangat luas ({platform_count} platform terdeteksi)")
    elif platform_count >= 10:
        score += 15
        flags.append(f"Footprint luas ({platform_count} platform terdeteksi)")
    elif platform_count >= 5:
        score += 8
    elif platform_count > 0:
        positives.append(f"Jejak digital terbatas ({platform_count} platform)")

    # HIBP breach
    if hibp_result.get("breached"):
        bc = hibp_result.get("breach_count", 0)
        if bc >= 10:
            score += 40
            flags.append(f"Data bocor di {bc} breach besar — SANGAT BERBAHAYA")
        elif bc >= 5:
            score += 30
            flags.append(f"Data bocor di {bc} breach — BERBAHAYA")
        elif bc >= 1:
            score += 20
            flags.append(f"Data bocor di {bc} breach")
    else:
        if hibp_result.get("checked"):
            positives.append("Tidak ditemukan di database breach publik")

    # Hudson Rock stealer logs
    if hudson_result.get("compromised"):
        sc2 = hudson_result.get("stealer_count", 0)
        score += min(sc2 * 15, 45)
        flags.append(f"Ditemukan di {sc2} stealer log — CREDENTIALS BOCOR")
    else:
        if hudson_result.get("checked"):
            positives.append("Tidak ditemukan di stealer logs")

    # Check platform categories
    sensitive_platforms = ["pornhub", "stripchat", "bongacams", "chaturbate",
                           "adultfriendfinder", "ashley madison"]
    for r in registered:
        pname = (r.get("platform") or "").lower()
        if any(s in pname for s in sensitive_platforms):
            score += 20
            flags.append(f"Terdaftar di platform sensitif: {r.get('platform')}")
            break

    score = min(score, 100)

    if score >= 70:
        level = "KRITIS"
        color = "#dc2626"
        verdict = "Profil email sangat berisiko. Banyak data breach dan stealer logs."
    elif score >= 50:
        level = "TINGGI"
        color = "#f87171"
        verdict = "Profil email berisiko. Ada indikasi kebocoran data."
    elif score >= 30:
        level = "SEDANG"
        color = "#f59e0b"
        verdict = "Footprint digital cukup luas. Perlu monitoring."
    elif score >= 10:
        level = "RENDAH"
        color = "#3b82f6"
        verdict = "Footprint kecil, tidak ada breach yang diketahui."
    else:
        level = "AMAN"
        color = "#22c55e"
        verdict = "Email tidak ditemukan di breach atau stealer logs yang diketahui."

    return {
        "score": score,
        "level": level,
        "color": color,
        "verdict": verdict,
        "red_flags": flags,
        "green_flags": positives,
    }


# ── MAIN: Full email scan ─────────────────────────────────────────────────────
async def scan_email(email: str) -> Dict[str, Any]:
    """
    Full email footprint scan.
    Return dict dengan semua hasil dan risk assessment.
    """
    email = email.strip().lower()

    if not _valid_email(email):
        return {
            "status": "error",
            "error": f"Format email tidak valid: {email}",
        }

    print(f"\n📧 [EmailScan] Scanning: {email}")
    start = time.time()

    # Jalankan semua check
    hibp_api_key = os.getenv("HIBP_API_KEY", "").strip()

    # Holehe async
    print("   ↳ [1/3] holehe account footprint...")
    holehe_results = await _run_holehe(email)

    # HIBP sync (dalam thread)
    print("   ↳ [2/3] HaveIBeenPwned breach check...")
    hibp_result = await asyncio.get_event_loop().run_in_executor(
        None, _check_hibp, email, hibp_api_key
    )

    # Hudson Rock sync
    print("   ↳ [3/3] Hudson Rock stealer logs...")
    hudson_result = await asyncio.get_event_loop().run_in_executor(
        None, _check_hudson_rock, email
    )

    # Risk score
    risk = _compute_email_risk(holehe_results, hibp_result, hudson_result)

    elapsed = round(time.time() - start, 1)
    print(f"   ✅ Scan selesai dalam {elapsed}s | Risk: {risk['score']}/100 {risk['level']}")

    # Summary platforms
    registered_platforms = [r for r in holehe_results if r.get("registered")]
    not_found_platforms  = [r for r in holehe_results if r.get("registered") == False]

    return {
        "status": "success",
        "email": email,
        "scan_duration_sec": elapsed,
        "risk": risk,
        "account_footprint": {
            "total_checked": len(holehe_results),
            "total_found": len(registered_platforms),
            "total_not_found": len(not_found_platforms),
            "registered": registered_platforms,
            "not_found": not_found_platforms,
        },
        "breach_data": {
            "hibp": hibp_result,
            "hudson_rock": hudson_result,
        },
    }
