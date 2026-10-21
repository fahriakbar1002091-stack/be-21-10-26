"""
osint_tools.py — OSINT Integration untuk Social Radar
Tools: maigret (username 2000+ situs) + holehe (email 100+ situs)
"""

import subprocess
import json
import time
from typing import Dict, List


def check_username(username: str, timeout: int = 30) -> Dict:
    """Cari username di 2000+ situs via maigret."""
    result = {
        "username": username, "found_on": [], "not_found_on": [],
        "total_found": 0, "status": "PENDING", "scan_time": "0s",
    }
    start = time.time()
    try:
        import sys
        # maigret harus dipanggil sebagai module: python -m maigret
        # bukan langsung: maigret (karena entry point bisa tidak ada)
        cmd = [sys.executable, "-m", "maigret",
               username, "--json", "--timeout", str(max(timeout // 2, 10))]
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout + 15
        )
        scan_time = f"{round(time.time() - start, 1)}s"
        result["scan_time"] = scan_time

        # maigret bisa output ke file JSON, bukan stdout
        # Cek stdout dulu, lalu coba file hasil
        raw_text = proc.stdout or ""
        if not raw_text and proc.returncode == 0:
            # maigret sering simpan ke reports/maigret_{username}.json
            import os, glob
            patterns = [
                f"reports/maigret_{username}.json",
                f"maigret_{username}.json",
                f"reports/{username}.json",
            ]
            for pat in patterns:
                if os.path.exists(pat):
                    with open(pat, "r", encoding="utf-8", errors="ignore") as f:
                        raw_text = f.read()
                    break
            # Juga cek glob
            if not raw_text:
                matches = glob.glob(f"reports/*{username}*.json")
                if matches:
                    with open(matches[0], "r", encoding="utf-8", errors="ignore") as f:
                        raw_text = f.read()

        if not raw_text:
            # Parse dari stderr/stdout untuk extract found sites (text mode)
            all_output = (proc.stdout or "") + (proc.stderr or "")
            found = []
            for line in all_output.splitlines():
                line = line.strip()
                # Pattern: [+] SiteName: https://...
                if line.startswith("[+]") and "http" in line:
                    parts = line[3:].split(":")
                    if parts:
                        site = parts[0].strip()
                        if site and site not in found:
                            found.append(site)
            result["found_on"]    = found[:50]
            result["total_found"] = len(found)
            result["status"]      = "SUCCESS" if found else "NO_RESULTS"
            result["scan_time"]   = scan_time
            return result

        raw = json.loads(raw_text)
        sites = raw.get("sites") or raw
        found, not_found = [], []
        if isinstance(sites, dict):
            for site, data in sites.items():
                st = data.get("status") if isinstance(data, dict) else {}
                exists = (
                    (isinstance(st, dict) and st.get("exists")) or
                    (isinstance(data, dict) and data.get("exists"))
                )
                if exists:
                    found.append(site)
                else:
                    not_found.append(site)
        result["found_on"]     = found[:50]
        result["not_found_on"] = not_found[:20]
        result["total_found"]  = len(found)
        result["status"]       = "SUCCESS"
    except subprocess.TimeoutExpired:
        result["status"]  = "TIMEOUT"
        result["message"] = f"Scan timeout ({timeout}s)"
        result["scan_time"] = f"{round(time.time() - start, 1)}s"
    except json.JSONDecodeError:
        # Parse text output sebagai fallback
        result["status"]    = "PARTIAL"
        result["message"]   = "Output bukan JSON, parsed dari text"
        result["scan_time"] = f"{round(time.time() - start, 1)}s"
    except FileNotFoundError:
        result["status"]  = "NOT_INSTALLED"
        result["message"] = "maigret tidak terinstall. Jalankan: pip install maigret"
    except ModuleNotFoundError:
        result["status"]  = "NOT_INSTALLED"
        result["message"] = "maigret tidak terinstall. Jalankan: pip install maigret"
    except Exception as e:
        result["status"]  = "ERROR"
        result["message"] = str(e)[:200]
    return result


def check_email(email: str, timeout: int = 30) -> Dict:
    """Cek email di 100+ situs via holehe."""
    result = {
        "email": email, "found_on": [], "total_found": 0,
        "status": "PENDING", "scan_time": "0s",
    }
    start = time.time()
    try:
        proc = subprocess.run(
            ["holehe", email, "--json", "--no-color"],
            capture_output=True, text=True, timeout=timeout + 10
        )
        result["scan_time"] = f"{round(time.time() - start, 1)}s"
        if proc.returncode != 0 and not proc.stdout:
            result["status"] = "ERROR"
            result["message"] = (proc.stderr or "Unknown error")[:300]
            return result
        raw = json.loads(proc.stdout or "[]")
        found = []
        if isinstance(raw, list):
            for item in raw:
                if isinstance(item, dict) and item.get("exists"):
                    found.append(item.get("name") or item.get("site") or "")
        elif isinstance(raw, dict):
            for site, data in raw.items():
                if isinstance(data, dict) and data.get("exists"):
                    found.append(site)
        result["found_on"]    = [f for f in found if f][:50]
        result["total_found"] = len(result["found_on"])
        result["status"]      = "SUCCESS"
    except subprocess.TimeoutExpired:
        result["status"] = "TIMEOUT"
        result["message"] = f"Scan timeout ({timeout}s)"
    except json.JSONDecodeError:
        result["status"] = "PARTIAL"
        result["message"] = "Output bukan JSON"
        result["scan_time"] = f"{round(time.time() - start, 1)}s"
    except FileNotFoundError:
        result["status"] = "NOT_INSTALLED"
        result["message"] = "holehe tidak terinstall. Jalankan: pip install holehe"
    except Exception as e:
        result["status"] = "ERROR"
        result["message"] = str(e)[:200]
    return result


def run_osint_scan(target: str, target_type: str = "username", timeout: int = 30) -> Dict:
    """Jalankan OSINT scan — username atau email."""
    if target_type == "email":
        return check_email(target, timeout=timeout)
    return check_username(target, timeout=timeout)







