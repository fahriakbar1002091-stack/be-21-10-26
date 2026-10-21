# main.py - Social Radar API
from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, Depends, HTTPException, Request, UploadFile, File
from fastapi.security import APIKeyHeader
from fastapi.responses import JSONResponse, StreamingResponse, RedirectResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from urllib.parse import quote as _q
from sqlalchemy.orm import Session
from typing import List, Optional, Dict
from datetime import datetime
import random
import re
import os
import shutil
import json
import traceback

from database import get_db, engine
import models
import schemas
from scraper_engine import run_crawler
from ai_engine import analyze_user_behavior, analyze_user_comments, analyze_reposts
from ai_image_analysis import analyze_image_real, is_image_file
from media_extractor import extract_post_content, build_combined_text, check_dependencies

models.Base.metadata.create_all(bind=engine)

# ── Cek dependency media extraction saat startup ──────────────────────────
_media_deps = check_dependencies()
_extraction_enabled = os.getenv("MEDIA_EXTRACTION_ENABLED", "true").lower() == "true"

import logging as _logging
_logger = _logging.getLogger("social_radar")
_logger.info(f"Media extraction deps: {_media_deps}")
_logger.info(f"Media extraction enabled: {_extraction_enabled}")

# ── App setup ─────────────────────────────────────────────────────────────────
api_key_scheme = APIKeyHeader(name="X-API-KEY", auto_error=False)

app = FastAPI(
    title="Social Radar - Social Media Analytics Engine",
    version="3.0.0",
    description="Analisis perilaku user media sosial berbasis AI",
    docs_url="/docs",   # Swagger UI aktif di /docs
    redoc_url="/redoc"
)

MASTER_API_KEY = "RAHASIA_AGENSIDETEKTIF_123"


def verify_api_key(api_key: str = Depends(api_key_scheme)):
    if not api_key or api_key != MASTER_API_KEY:
        raise HTTPException(status_code=401, detail="API Key tidak valid!")
    return api_key


# ── Global error handler — tampilkan detail error, bukan cuma '500' ──────────
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={
            "status": "ERROR",
            "error": type(exc).__name__,
            "detail": str(exc),
            "traceback": traceback.format_exc().splitlines()[-6:]  # 6 baris terakhir
        }
    )


# ─────────────────────────────────────────────────────────────────────────────
# ROOT
# ─────────────────────────────────────────────────────────────────────────────
@app.get("/")
def home():
    return {
        "status": "ONLINE",
        "service": "Social Radar API v3.0",
        "docs": "/docs"
    }


# ─────────────────────────────────────────────────────────────────────────────
# DEBUG — lihat raw item dari Apify untuk deteksi struktur komentar
# Bisa diakses via header X-API-KEY ATAU query param ?key=
# Contoh: GET /api/v1/debug/tiktok-raw/khaby.lame?key=RAHASIA_AGENSIDETEKTIF_123
# ─────────────────────────────────────────────────────────────────────────────
@app.get("/api/v1/debug/tiktok-raw/{username}")
async def debug_tiktok_raw(
    username: str,
    key: str = "",                          # query param fallback
    api_key: str = Depends(api_key_scheme)  # header
):
    """
    Debug: dump SEMUA field mentah dari dataset Apify TikTok.
    Akses via header X-API-KEY atau ?key= di URL.
    """
    # Validasi key dari header atau query param
    effective_key = api_key or key
    if effective_key != MASTER_API_KEY:
        raise HTTPException(status_code=401, detail="API Key tidak valid!")

    import asyncio
    from functools import partial
    from apify_client import ApifyClient

    token = os.getenv("APIFY_TOKEN", "")
    if not token:
        raise HTTPException(status_code=500, detail="APIFY_TOKEN tidak ada di .env")

    def _fetch():
        client = ApifyClient(token)
        run = client.actor("clockworks/tiktok-scraper").call(
            run_input={
                "profiles": [username],
                "resultsPerPage": 3,
                "maxVideosPerProfile": 3,
                "shouldDownloadVideos": False,
                "shouldDownloadCovers": False,
                "shouldDownloadSubtitles": False,
                "includeComments": True,
                "maxComments": 5,
                "proxyConfiguration": {"useApifyProxy": True},
            }
        )
        dataset_id = getattr(run, "default_dataset_id", None)
        if not dataset_id:
            return []
        return client.dataset(dataset_id).list_items().items or []

    loop = asyncio.get_event_loop()
    items = await loop.run_in_executor(None, _fetch)

    debug_items = []
    for i, item in enumerate(items[:15]):
        # Cek semua field yang mungkin mengandung komentar
        all_comment_fields = {
            k: v for k, v in item.items()
            if "comment" in k.lower() or "reply" in k.lower()
        }

        debug_items.append({
            "index":       i,
            # Field tipe item — kunci utama untuk pisahkan video vs komentar
            "type":        item.get("type"),
            "itemType":    item.get("itemType"),
            "isRepost":    item.get("isRepost"),
            # ID fields
            "id":          item.get("id"),
            "videoId":     item.get("videoId"),
            "awemeId":     item.get("awemeId"),
            # Cek komentar nested
            "latestComments_count": len(item.get("latestComments") or []),
            "comments_count":       len(item.get("comments") or []),
            # Dump SEMUA field yang mengandung kata "comment" / "reply"
            "comment_related_fields": all_comment_fields,
            # Sample komentar pertama jika ada (nested)
            "latestComments_sample": (item.get("latestComments") or [])[:2],
            "comments_sample":       (item.get("comments") or [])[:2],
            # Teks postingan
            "text_snippet": str(item.get("text") or item.get("desc") or "")[:120],
            # SEMUA keys — untuk tahu field apa saja yang ada
            "all_keys": sorted(item.keys()),
        })

    return {
        "username":    username,
        "total_items": len(items),
        "hint": "Perhatikan 'type'/'itemType' tiap item dan 'all_keys' untuk lihat field komentar",
        "items":       debug_items
    }


# ── DEBUG X/Twitter — dump raw field dari cryptosignals actor ────────────────
@app.get("/api/v1/debug/x-raw/{username}")
async def debug_x_raw(
    username: str,
    key: str = "",
    api_key: str = Depends(api_key_scheme)
):
    """
    Debug: dump raw field dari cryptosignals/twitter-scraper untuk X.
    Akses: GET /api/v1/debug/x-raw/JustinRose99?key=RAHASIA_AGENSIDETEKTIF_123
    """
    effective_key = api_key or key
    if effective_key != MASTER_API_KEY:
        raise HTTPException(status_code=401, detail="API Key tidak valid!")

    import asyncio
    from apify_client import ApifyClient

    token = os.getenv("APIFY_TOKEN", "")
    if not token:
        raise HTTPException(status_code=500, detail="APIFY_TOKEN tidak ada di .env")

    def _fetch():
        client = ApifyClient(token)
        run = client.actor("cryptosignals/twitter-scraper").call(run_input={
            "username":  username,
            "action":    "profile",
            "maxTweets": 30,
        })
        ds = getattr(run, "default_dataset_id", None)
        if not ds:
            return []
        return client.dataset(ds).list_items().items or []

    loop = asyncio.get_event_loop()
    raw_items = await loop.run_in_executor(None, _fetch)

    # Pisahkan tweet vs profile
    tweets  = [i for i in raw_items if i.get("tweet_text") or i.get("tweet_id")]
    profile = [i for i in raw_items if i.get("followers") is not None and not i.get("tweet_text")]

    # Dump semua unique keys + sample value dari setiap tweet
    result = []
    for tw in tweets[:30]:
        # Tentukan tipe berdasarkan field yang ada
        detected_type = "POST"
        if tw.get("is_retweet") or tw.get("isRetweet"):
            detected_type = "RETWEET"
        elif tw.get("is_reply") or tw.get("isReply"):
            detected_type = "REPLY"
        elif tw.get("is_quote") or tw.get("isQuote"):
            detected_type = "QUOTE"

        result.append({
            "detected_type":          detected_type,
            "tweet_id":               tw.get("tweet_id"),
            "tweet_text_preview":     (tw.get("tweet_text") or "")[:80],
            # --- type detection fields ---
            "is_reply":               tw.get("is_reply"),
            "is_retweet":             tw.get("is_retweet"),
            "is_quote":               tw.get("is_quote"),
            "type":                   tw.get("type"),
            # --- reply metadata ---
            "in_reply_to_tweet_id":   tw.get("in_reply_to_tweet_id"),
            "in_reply_to_status_id":  tw.get("in_reply_to_status_id"),
            "in_reply_to_user_id":    tw.get("in_reply_to_user_id"),
            "in_reply_to_username":   tw.get("in_reply_to_username"),
            "in_reply_to_user_name":  tw.get("in_reply_to_user_name"),
            "in_reply_to_screen_name":tw.get("in_reply_to_screen_name"),
            "in_reply_to_user":       tw.get("in_reply_to_user"),
            # --- all keys for full inspection ---
            "all_keys":               sorted(tw.keys()),
        })

    # Hitung breakdown
    breakdown = {"POST": 0, "REPLY": 0, "RETWEET": 0, "QUOTE": 0}
    for r in result:
        breakdown[r["detected_type"]] = breakdown.get(r["detected_type"], 0) + 1

    return {
        "username":       username,
        "total_raw":      len(raw_items),
        "total_tweets":   len(tweets),
        "total_profile":  len(profile),
        "type_breakdown": breakdown,
        "tweets":         result,
    }


# ── DEBUG REPOST — test parameter clockworks/tiktok-profile-scraper ──────────
@app.get("/api/v1/debug/tiktok-reposts/{username}")
async def debug_tiktok_reposts(
    username: str,
    key: str = "",
    api_key: str = Depends(api_key_scheme)
):
    """
    Debug: test scraping repost profil TikTok.
    Akses: GET /api/v1/debug/tiktok-reposts/williesalim?key=RAHASIA_AGENSIDETEKTIF_123
    """
    effective_key = api_key or key
    if effective_key != MASTER_API_KEY:
        raise HTTPException(status_code=401, detail="API Key tidak valid!")

    import asyncio
    from apify_client import ApifyClient

    token = os.getenv("APIFY_TOKEN", "")
    if not token:
        raise HTTPException(status_code=500, detail="APIFY_TOKEN tidak ada di .env")

    def _fetch_reposts():
        client = ApifyClient(token)
        run = client.actor("clockworks/tiktok-profile-scraper").call(
            run_input={
                "profiles":             [username],
                "profileSection":       "reposts",
                "resultsPerPage":       10,
                "shouldDownloadVideos": False,
                "shouldDownloadCovers": False,
            }
        )
        dataset_id = getattr(run, "default_dataset_id", None)
        if not dataset_id:
            return [], "no_dataset_id"
        items = client.dataset(dataset_id).list_items().items or []
        return items, "ok"

    loop = asyncio.get_event_loop()
    items, status = await loop.run_in_executor(None, _fetch_reposts)

    first_keys = sorted(items[0].keys()) if items else []
    first_sample = {}
    if items:
        for k in ["id", "text", "webVideoUrl", "createTimeISO", "authorMeta",
                  "isRepost", "repostSource", "type", "itemType", "errorCode",
                  "diggCount", "commentCount", "shareCount", "playCount"]:
            first_sample[k] = items[0].get(k)

    return {
        "username":          username,
        "fetch_status":      status,
        "total_items":       len(items),
        "first_item_keys":   first_keys,
        "first_item_sample": first_sample,
        "preview": [
            {
                "id":           item.get("id"),
                "text":         str(item.get("text") or "")[:80],
                "webVideoUrl":  item.get("webVideoUrl"),
                "author_name":  (item.get("authorMeta") or {}).get("name"),
                "author_unique":(item.get("authorMeta") or {}).get("uniqueId"),
                "isRepost":     item.get("isRepost"),
                "type":         item.get("type"),
                "errorCode":    item.get("errorCode"),
                "all_keys":     sorted(item.keys()),
            }
            for item in items[:10]
        ]
    }


# ─────────────────────────────────────────────────────────────────────────────
# TENANTS
# ─────────────────────────────────────────────────────────────────────────────
@app.post("/api/v1/tenants", response_model=schemas.TenantResponse, status_code=201)
def create_tenant(
    tenant: schemas.TenantCreate,
    db: Session = Depends(get_db),
    api_key: str = Depends(verify_api_key)
):
    generated_key = f"KEY_TENANT_{random.randint(10000, 99999)}"
    db_tenant = models.Tenant(
        name=tenant.name,
        daily_scan_limit=tenant.daily_scan_limit,
        api_key=generated_key,
        is_active=True
    )
    db.add(db_tenant)
    db.commit()
    db.refresh(db_tenant)
    return db_tenant


@app.get("/api/v1/tenants", response_model=List[schemas.TenantResponse])
def get_all_tenants(
    db: Session = Depends(get_db),
    api_key: str = Depends(verify_api_key)
):
    return db.query(models.Tenant).all()


@app.get("/api/v1/tenants/{tenant_id}", response_model=schemas.TenantResponse)
def get_tenant(
    tenant_id: int,
    db: Session = Depends(get_db),
    api_key: str = Depends(verify_api_key)
):
    tenant = db.query(models.Tenant).filter(models.Tenant.tenant_id == tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant tidak ditemukan.")
    return tenant


# ─────────────────────────────────────────────────────────────────────────────
# SCAN TRIGGER
# ─────────────────────────────────────────────────────────────────────────────
@app.post("/api/v1/scan/trigger", status_code=201)
async def trigger_social_scan(
    payload: schemas.DynamicScanRequest,
    db: Session = Depends(get_db),
    api_key: str = Depends(verify_api_key)
):
    # Validasi tenant
    tenant = db.query(models.Tenant).filter(
        models.Tenant.tenant_id == payload.tenant_id,
        models.Tenant.is_active == True
    ).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant tidak ditemukan atau tidak aktif.")

    # ── 1. Scrape ──────────────────────────────────────────────────────────
    scrape_result, source_status = await run_crawler(
        platform=payload.platform.value,
        target=payload.target,
        scan_type=payload.scan_type.value
    )

    scrape_profile    = scrape_result.get("profile", {})
    raw_activities    = scrape_result.get("activities", [])
    user_comments     = scrape_result.get("user_comments", [])
    reposts           = scrape_result.get("reposts", [])
    quotes_list       = scrape_result.get("quotes_list", [])   # X/Twitter quote tweets
    platform_photos   = scrape_result.get("photos", [])        # Facebook & LinkedIn
    platform_reels    = scrape_result.get("reels", [])         # Facebook reels (dedicated)
    osint_findings    = scrape_result.get("osint_findings", {})
    scrape_errors     = scrape_result.get("scrape_errors", [])

    # platform_val dibutuhkan lebih awal untuk cek media extraction
    platform_val = payload.platform.value  # "tiktok" / "instagram" / "x" / "facebook" / "linkedin"

    # ── 1b. Media Extraction — OCR + transcript per post ──────────────────
    # Dijalankan di thread executor agar tidak blocking event loop.
    # Dikendalikan oleh env var MEDIA_EXTRACTION_ENABLED (default: true).
    # Jika extraction gagal per-post, combined_text fallback ke caption.
    # Pipeline lama tetap berjalan normal meski extraction dimatikan.
    # Instagram: skip extraction — tidak ada video CDN yang bisa diproses
    _platform_supports_extraction = platform_val in ("tiktok", "x", "twitter")
    if _extraction_enabled and _platform_supports_extraction and raw_activities:
        import asyncio
        from functools import partial

        loop = asyncio.get_event_loop()

        async def _extract_one(activity: dict) -> dict:
            """Jalankan extraction satu post di thread, dengan timeout 60 detik."""
            try:
                extraction = await asyncio.wait_for(
                    loop.run_in_executor(
                        None,
                        partial(extract_post_content, activity)
                    ),
                    timeout=60.0
                )
                ocr_text        = extraction.get("ocr_text", "")
                audio_transcript= extraction.get("audio_transcript", "")
                visual_desc     = extraction.get("visual_description", "")
                ext_errors      = extraction.get("extraction_errors", [])

                combined = build_combined_text(
                    caption_text      = activity.get("caption_text") or activity.get("text") or "",
                    ocr_text          = ocr_text,
                    audio_transcript  = audio_transcript,
                    visual_description= visual_desc,
                )

                return {
                    **activity,
                    "ocr_text":          ocr_text,
                    "audio_transcript":  audio_transcript,
                    "visual_description": visual_desc,
                    "combined_text":     combined or activity.get("text") or "",
                    "extraction_errors": ext_errors,
                }
            except asyncio.TimeoutError:
                return {
                    **activity,
                    "combined_text":     activity.get("text") or "",
                    "extraction_errors": ["Extraction timeout (>60s)"],
                }
            except Exception as exc:
                return {
                    **activity,
                    "combined_text":     activity.get("text") or "",
                    "extraction_errors": [f"Extraction error: {str(exc)}"],
                }

        # Jalankan semua post secara concurrent (tapi tetap di thread pool)
        raw_activities = list(await asyncio.gather(
            *[_extract_one(act) for act in raw_activities]
        ))

    # ── 2. Upsert SocialUser ───────────────────────────────────────────────
    try:
        db_user = db.query(models.SocialUser).filter(
            models.SocialUser.username == payload.target,
            models.SocialUser.platform == payload.platform.value
        ).first()

        if not db_user:
            db_user = models.SocialUser(
                username=payload.target,
                platform=payload.platform.value,
                target_type=payload.scan_type.value
            )
            db.add(db_user)
            db.flush()  # dapatkan user_id tanpa commit dulu

        db_user.full_name    = scrape_profile.get("full_name")    or db_user.full_name
        db_user.bio          = scrape_profile.get("bio")          or db_user.bio
        db_user.followers    = scrape_profile.get("followers",  0)
        db_user.following    = scrape_profile.get("following",  0)
        db_user.verified     = scrape_profile.get("verified",   False)
        db_user.profile_pic  = scrape_profile.get("profile_pic") or db_user.profile_pic
        db_user.last_scanned = datetime.now()
        db.commit()
        db.refresh(db_user)

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"DB error saat simpan user: {e}")

    # ── 3. Simpan activities ───────────────────────────────────────────────
    try:
        for item in raw_activities:
            ai_image = item.get("ai_image_analysis")
            db_activity = models.Activity(
                user_id          = db_user.user_id,
                action_type      = item.get("action_type", "POST"),
                content_text     = item.get("text", ""),
                combined_text    = item.get("combined_text") or item.get("text") or "",
                ocr_text         = item.get("ocr_text", ""),
                audio_transcript = item.get("audio_transcript", ""),
                image_path       = item.get("image_url"),
                post_url         = item.get("post_url"),
                ai_caption       = ai_image.get("ai_caption") if ai_image else None,
                ai_objects       = json.dumps(ai_image.get("ai_objects", [])) if ai_image else None,
                ai_topics        = json.dumps(ai_image.get("ai_topics",  [])) if ai_image else None,
                ai_mood          = json.dumps(ai_image.get("ai_mood",    [])) if ai_image else None,
                ai_summary       = ai_image.get("ai_summary")  if ai_image else None,
                analyzed_at      = datetime.now() if ai_image else None
            )
            db.add(db_activity)
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"DB error saat simpan activities: {e}")

    # ── 4. AI Analysis ────────────────────────────────────────────────────
    ai_result = analyze_user_behavior(
        username   = payload.target,
        platform   = payload.platform.value,
        activities = raw_activities,
        profile    = scrape_profile
    )

    enriched_activities = ai_result.pop("enriched_activities", raw_activities)

    # ── 4b. Analisis sentimen untuk user_comments ──────────────────────────
    # user_comments = komentar yang dibuat si target di postingannya sendiri
    from ai_engine import _analyze_single_sentiment
    enriched_user_comments = []
    for uc in user_comments:
        c_text = uc.get("content") or ""
        sent   = _analyze_single_sentiment(c_text) if c_text else {"label": "NEUTRAL", "score": 0.5}
        enriched_user_comments.append({**uc, "sentiment": sent})
    user_comments = enriched_user_comments

    # ── 4c. Analisis insight komentar user ─────────────────────────────────
    comment_insight = analyze_user_comments(
        username      = payload.target,
        user_comments = user_comments
    )
    # Komentar sudah di-enrich di dalam analyze_user_comments, pakai itu
    user_comments = comment_insight.pop("enriched_user_comments", user_comments)

    # ── 4d. Analisis repost ────────────────────────────────────────────────
    reposts = analyze_reposts(username=payload.target, reposts=reposts)

    # Update sentiment di DB (best-effort, tidak crash kalau gagal)
    try:
        saved = (
            db.query(models.Activity)
            .filter(models.Activity.user_id == db_user.user_id)
            .order_by(models.Activity.activity_id.desc())
            .limit(len(enriched_activities))
            .all()
        )
        for db_act, enriched in zip(saved, enriched_activities):
            sent = enriched.get("sentiment", {})
            db_act.ai_sentiment  = sent.get("label", "NEUTRAL")
            db_act.ai_risk_score = ai_result.get("risk_score", 50)
        db.commit()
    except Exception:
        db.rollback()  # non-critical, lanjut

    # ── 5. Simpan AI Summary ───────────────────────────────────────────────
    try:
        db_summary = models.AISummary(
            tenant_id   = tenant.tenant_id,
            user_id     = db_user.user_id,
            summary_text= ai_result.get("summary_text", "")
        )
        db.add(db_summary)
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"DB error saat simpan summary: {e}")

    # ── 6. Response ────────────────────────────────────────────────────────
    # platform_val sudah di-assign di atas (sebelum media extraction)
    _sp  = scrape_profile
    _ai  = ai_result
    _ci  = comment_insight

    # ── Helpers format per platform ───────────────────────────────────────
    def _fmt_activity_tiktok(a: dict) -> dict:
        """Format satu aktivitas TikTok — include visual_description, topic, mood."""
        _ca   = a.get("content_analysis") or {}
        _m    = a.get("metrics") or {}
        _sent = a.get("sentiment") or {"label": "NEUTRAL", "score": 0.5}
        _music = a.get("music") or {}
        _dur  = a.get("duration_sec") or 0
        _cap  = a.get("caption_text") or a.get("caption") or ""
        _tags = a.get("hashtags") or []

        # visual_description: ambil dari field baru (fetch_tiktok v3)
        # atau fallback ke ai_description dari content_analysis
        _vd = (
            a.get("visual_description") or
            _ca.get("ai_description") or
            a.get("content_description") or
            ""
        )
        # Fix label generik "Foto ini" / "Konten ini"
        if _vd.startswith("Foto ini") or _vd.startswith("Konten ini"):
            _lbl = f"Video TikTok berdurasi {_dur} detik ini" if _dur > 0 else "Konten TikTok ini"
            _vd  = re.sub(r"^(Foto ini|Konten ini)", _lbl, _vd)

        _topic = a.get("topic") or _ca.get("topic") or ""
        _mood  = a.get("mood")  or ""
        _obj   = a.get("objects")  or ""
        _act   = a.get("activity") or ""

        # Deteksi kategori non-fyp
        _cat = _topic
        if not _cat and _tags:
            _non_fyp = [t for t in _tags if "fyp" not in t.lower()]
            _cat = _non_fyp[0] if _non_fyp else (_tags[0] if _tags else "")

        return {
            "post_id":            a.get("post_id") or a.get("id") or "",
            "post_url":           a.get("post_url") or "",
            "caption":            _cap,
            "caption_text":       _cap,
            "visual_description": _vd,
            "ai_description":     _vd,
            "transcript":         a.get("transcript", ""),
            "ocr_text":           a.get("ocr_text", ""),
            "content_summary":    a.get("content_summary", ""),
            "detected_negative_words": a.get("detected_negative_words", []),
            "analysis_method":    a.get("analysis_method", "caption_only"),
            "topic":              _topic,
            "mood":               _mood,
            "objects":            _obj,
            "activity":           _act,
            "likes":              _m.get("likes",    0),
            "comments":           _m.get("comments", 0),
            "shares":             _m.get("shares",   0),
            "views":              _m.get("plays",    0),
            "music":              {"title": _music.get("title",""), "author": _music.get("author","")},
            "hashtags":           _tags,
            "mentions":           a.get("mentions") or [],
            "duration_sec":       _dur,
            "location":           a.get("location") or "",
            "created_at":         a.get("created_at") or "",
            "is_repost":          bool(a.get("is_repost")),
            "is_pinned":          bool(a.get("is_pinned")),
            "video_url":          a.get("video_url") or "",
            "cover_url":          a.get("cover_url") or a.get("image_url") or "",
            "image_url":          a.get("image_url") or a.get("cover_url") or "",
            "image_urls":         a.get("image_urls") or a.get("images_list") or [],
            "images_list":        a.get("images_list") or a.get("image_urls") or (
                # Fallback: jika slide tapi images_list kosong, pakai cover_url
                [a.get("cover_url") or a.get("image_url")] if (
                    (a.get("media_type") == "image") and
                    not (a.get("images_list") or a.get("image_urls")) and
                    (a.get("cover_url") or a.get("image_url"))
                ) else []
            ),
            "media_type":         a.get("media_type") or "video",
            "sentiment":          _sent.get("label", "NEUTRAL"),
            "category":           _cat,
        }

    def _fmt_comment_tiktok(uc: dict) -> dict:
        _s = uc.get("sentiment") or {"label": "NEUTRAL", "score": 0.5}
        _sl = _s.get("label", "NEUTRAL") if isinstance(_s, dict) else str(_s)
        return {
            "post_url":     uc.get("post_url") or "",
            "post_caption": uc.get("post_caption") or "",
            "comment_text": uc.get("comment_text") or uc.get("content") or "",
            "likes":        uc.get("likes") or 0,
            "is_reply":     bool(uc.get("is_reply")),
            "reply_to":     uc.get("reply_to") or "",
            "created_at":   uc.get("created_at") or "",
            "sentiment":    _sl,
        }

    def _fmt_repost_tiktok(r: dict) -> dict:
        _s  = r.get("sentiment") or {"label": "NEUTRAL", "score": 0.5}
        _sl = _s.get("label", "NEUTRAL") if isinstance(_s, dict) else str(_s)
        _m  = r.get("metrics") or {}
        # Support field langsung (likes/plays) atau nested di metrics
        _likes = _m.get("likes", 0) or r.get("likes", 0)
        _plays = _m.get("plays", 0) or r.get("plays", 0)
        _comms = _m.get("comments", 0) or r.get("comments", 0)
        _shrs  = _m.get("shares", 0) or r.get("shares", 0)
        _raw_vid = r.get("video_url") or ""
        # Jangan pakai page URL sebagai video_url — hanya CDN/KV URL yang valid
        _is_page_url = (
            "tiktok.com/@" in _raw_vid or
            "tiktok.com/video/" in _raw_vid or
            "tiktok.com/t/" in _raw_vid
        )
        _clean_vid = "" if _is_page_url else _raw_vid
        # Extract video ID dari post_url atau video_url untuk TikTok embed
        _purl_r = r.get("post_url") or r.get("video_url") or ""
        _vid_id_r = r.get("id") or ""
        if not _vid_id_r:
            import re as _re_r
            _m_r = _re_r.search(r'/video/(\d{10,})', _purl_r)
            if _m_r: _vid_id_r = _m_r.group(1)
        return {
            "id":                  _vid_id_r,
            "video_url":           _clean_vid,
            "post_url":            r.get("post_url") or r.get("video_url") or "",
            "cover_url":           r.get("cover_url") or r.get("image_url") or "",
            "original_author":     r.get("original_author") or "",
            "original_caption":    r.get("original_caption") or r.get("caption") or r.get("content") or "",
            "caption":             r.get("original_caption") or r.get("caption") or r.get("content") or "",
            "visual_description":  r.get("visual_description") or r.get("content_description") or "",
            "ai_description":      r.get("ai_description") or r.get("visual_description") or "",
            "topic":               r.get("topic") or "",
            "mood":                r.get("mood") or "",
            "repost_date":         r.get("repost_date") or r.get("created_at") or "",
            "created_at":          r.get("repost_date") or r.get("created_at") or "",
            "hashtags":            r.get("hashtags") or [],
            "duration_sec":        r.get("duration_sec") or 0,
            "music":               r.get("music") or {"title": "", "author": ""},
            "likes":    _likes,
            "plays":    _plays,
            "comments": _comms,
            "shares":   _shrs,
            "metrics":  {"likes": _likes, "comments": _comms, "shares": _shrs, "plays": _plays},
            "sentiment": {"label": _sl, "score": _s.get("score", 0.5) if isinstance(_s, dict) else 0.5},
            "is_repost": True,
            "content_analysis": {
                "topic":           r.get("topic") or "",
                "mood":            r.get("mood") or "",
                "objects":         r.get("objects") or "",
                "activity":        r.get("activity") or "",
                "content_summary": r.get("original_caption") or r.get("caption") or "",
                "ai_description":  r.get("ai_description") or r.get("visual_description") or "",
                "key_themes":      r.get("hashtags") or [],
                "engagement_level": "RENDAH",
            },
            "detected_negative_words": r.get("detected_negative_words") or [],
        }

    # ── Kumpulkan topik dominan ────────────────────────────────────────────
    from collections import Counter as _Ctr
    _all_topics = []
    for _a in enriched_activities:
        _ca2 = _a.get("content_analysis") or {}
        _all_topics.extend(_ca2.get("topics") or [])
        if _a.get("topic"): _all_topics.append(_a["topic"])
    _dom_topics = [t for t, _ in _Ctr(_all_topics).most_common(5)] if _all_topics else []
    _sent_bd    = _ai.get("sentiment_breakdown", {})

    # ── Response TikTok — format lama yang berhasil ───────────────────────
    if platform_val == "tiktok":
        _profile_tiktok = {
            "username":     _sp.get("username",    payload.target),
            "full_name":    _sp.get("full_name",   ""),
            "bio":          _sp.get("bio",         ""),
            "followers":    _sp.get("followers",   0),
            "following":    _sp.get("following",   0),
            "verified":     _sp.get("verified",    False),
            "profile_pic":  _sp.get("profile_pic", ""),
            "total_posts":  _sp.get("total_posts", len(enriched_activities)),
            "total_likes":  _sp.get("likes", 0) or _sp.get("total_likes", 0),
            "platform":     "tiktok",
            "last_updated": _sp.get("last_updated", datetime.now().strftime("%Y-%m-%d")),
        }
        _fmt_posts    = [_fmt_activity_tiktok(a) for a in enriched_activities if not a.get("is_repost")]
        _fmt_reposts  = [_fmt_repost_tiktok(r)   for r in reposts]
        _fmt_comments = [_fmt_comment_tiktok(uc) for uc in user_comments]

        return {
            "status":    "SUCCESS",
            "timestamp": datetime.now().isoformat(),
            "scan_meta": {
                "platform":          "TIKTOK",
                "scan_type":         payload.scan_type.value,
                "target":            payload.target,
                "data_source_status": source_status,
                "db_user_id":        db_user.user_id,
                "scrape_errors":     scrape_errors,
            },
            "profile": _profile_tiktok,
            "behavior_metrics": {
                "total_extracted": len(_fmt_posts),
                "activities":      _fmt_posts,
                "user_comments":   _fmt_comments,
                "reposts":         _fmt_reposts,
            },
            "analytics_insight": {
                "sentiment_overall":   _ai.get("sentiment_overall",   "NEUTRAL"),
                "sentiment_score":     _ai.get("sentiment_score",     0.5),
                "sentiment_breakdown": _sent_bd,
                "risk_score":          _ai.get("risk_score",          0),
                "risk_level":          _ai.get("risk_level",          "RENDAH"),
                "personality":         _ai.get("personality",         {}),
                "summary_text":        _ai.get("summary_text",        ""),
                "ai_narrative":        _ai.get("ai_narrative",        ""),
                "ai_narrative_short":  _ai.get("ai_narrative_short",  ""),
                "ai_narrative":        _ai.get("ai_narrative",        ""),
                "ai_narrative_short":  _ai.get("ai_narrative_short",  ""),
                "red_flags":           _ai.get("red_flags",           []),
                "green_flags":         _ai.get("green_flags",         []),
                "recommendation":      _ai.get("recommendation",      ""),
                "suitable_roles":      _ai.get("suitable_roles",      []),
                "comment_sentiment_overall":   _ci.get("comment_sentiment_overall",   "NEUTRAL"),
                "comment_sentiment_score":     _ci.get("comment_sentiment_score",     0.5),
                "comment_sentiment_breakdown": _ci.get("comment_sentiment_breakdown", {}),
                "comment_topics":              _ci.get("comment_topics",              []),
                "comment_style":               _ci.get("comment_style",               ""),
                "comment_red_flags":           _ci.get("comment_red_flags",           []),
                "comment_green_flags":         _ci.get("comment_green_flags",         []),
                "comment_summary":             _ci.get("comment_summary",             ""),
                "osint_findings":              osint_findings,
            },
        }

    # ── Response semua platform lain ─────────────────────────────────────
    # ── X/Twitter — format khusus dengan content_analysis per tweet ───────
    if platform_val in ("x", "twitter"):

        def _fmt_tweet(a: dict) -> dict:
            """Format satu tweet untuk response JSON X."""
            _ca   = a.get("content_analysis") or {}
            _m    = a.get("metrics") or {}
            _sent = a.get("sentiment") or {"label": "NEUTRAL", "score": 0.5}
            _sl   = _sent.get("label", "NEUTRAL") if isinstance(_sent, dict) else str(_sent)
            _ss   = _sent.get("score", 0.5) if isinstance(_sent, dict) else 0.5
            _tt   = a.get("tweet_type") or a.get("action_type") or "POST"
            _text = a.get("content") or a.get("text") or ""
            return {
                "tweet_id":       a.get("post_id") or a.get("id") or "",
                "tweet_url":      a.get("tweet_url") or a.get("post_url") or "",
                "tweet_type":     _tt,
                "text":           _text,
                "created_at":     a.get("created_at") or "",
                "lang":           a.get("lang") or "",
                "metrics": {
                    "likes":      _m.get("likes",     0),
                    "retweets":   _m.get("retweets",  0) or _m.get("shares", 0),
                    "replies":    _m.get("replies",   0) or _m.get("comments", 0),
                    "quotes":     _m.get("quotes",    0),
                    "views":      _m.get("views",     0) or _m.get("plays", 0),
                    "bookmarks":  _m.get("bookmarks", 0),
                },
                "media": {
                    "type":       a.get("media_type") or "text",
                    "image_url":  a.get("image_url") or "",
                    "video_url":  a.get("video_url") or "",
                    "gif_url":    a.get("gif_url")   or "",
                    "all_media":  a.get("all_media") or [],
                },
                "hashtags":   a.get("hashtags")  or [],
                "mentions":   a.get("mentions")  or [],
                "urls":       a.get("urls")       or [],
                "is_reply":   bool(a.get("is_reply")),
                "is_retweet": bool(a.get("is_repost")),
                "is_quote":   bool(a.get("is_quote")),
                "in_reply_to_user":    a.get("in_reply_to_user") or "",
                "referenced_tweet_url": a.get("referenced_tweet_url") or "",
                "sentiment": {
                    "label": _sl,
                    "score": _ss,
                },
                "content_analysis": {
                    "topic":           _ca.get("topic")           or "",
                    "mood":            _ca.get("mood")            or "",
                    "objects":         _ca.get("objects")         or "",
                    "activity":        _ca.get("activity")        or "",
                    "content_summary": _ca.get("content_summary") or _text[:200],
                    "ai_description":  _ca.get("ai_description") or a.get("ai_description") or a.get("visual_description") or "",
                    "key_themes":      _ca.get("key_themes")       or [],
                    "engagement_level": _ca.get("engagement_level") or "RENDAH",
                },
            }

        def _fmt_x_comment(uc: dict) -> dict:
            """Format satu user_comment (reply dari target) untuk X."""
            _ca   = uc.get("content_analysis") or {}
            _sent = uc.get("sentiment") or {"label": "NEUTRAL", "score": 0.5}
            _sl   = _sent.get("label", "NEUTRAL") if isinstance(_sent, dict) else str(_sent)
            _ss   = _sent.get("score", 0.5) if isinstance(_sent, dict) else 0.5
            _text = uc.get("reply_text") or uc.get("content") or ""
            return {
                "post_url":     uc.get("post_url")     or "",
                "post_caption": uc.get("post_caption") or "",
                "reply_text":   _text,
                "reply_to":     uc.get("reply_to") or uc.get("in_reply_to_user") or "",
                "likes":        uc.get("likes",  0),
                "replies":      uc.get("replies", 0),
                "quotes":       uc.get("quotes",  0),
                "is_reply":     True,
                "created_at":   uc.get("created_at") or "",
                "lang":         uc.get("lang") or "",
                "sentiment": {
                    "label": _sl,
                    "score": _ss,
                },
                "content_analysis": {
                    "topic":           _ca.get("topic")           or "",
                    "mood":            _ca.get("mood")            or "",
                    "objects":         _ca.get("objects")         or "",
                    "activity":        _ca.get("activity")        or "",
                    "content_summary": _ca.get("content_summary") or _text[:200],
                    "ai_description":  _ca.get("ai_description") or a.get("ai_description") or a.get("visual_description") or "",
                    "key_themes":      _ca.get("key_themes")       or [],
                    "engagement_level": _ca.get("engagement_level") or "RENDAH",
                },
            }

        def _fmt_x_retweet(r: dict) -> dict:
            """Format satu retweet untuk X."""
            _ca   = r.get("content_analysis") or {}
            _sent = r.get("sentiment") or {"label": "NEUTRAL", "score": 0.5}
            _sl   = _sent.get("label", "NEUTRAL") if isinstance(_sent, dict) else str(_sent)
            _ss   = _sent.get("score", 0.5) if isinstance(_sent, dict) else 0.5
            _m    = r.get("metrics") or {}
            return {
                "retweet_url":         r.get("tweet_url") or r.get("video_url") or "",
                "tweet_url":           r.get("tweet_url") or r.get("video_url") or "",
                "original_author":     r.get("original_author")     or "",
                "original_author_url": r.get("original_author_url") or "",
                "original_tweet_url":  r.get("original_tweet_url")  or "",
                "original_text":       r.get("original_caption") or r.get("orig_text") or "",
                "retweet_date":        r.get("repost_date") or r.get("created_at") or "",
                "created_at":          r.get("repost_date") or r.get("created_at") or "",
                "hashtags":            r.get("hashtags") or [],
                "mentions":            r.get("mentions") or [],
                "metrics": {
                    "likes":    _m.get("likes",    0),
                    "retweets": _m.get("retweets", 0),
                    "replies":  _m.get("replies",  0),
                    "quotes":   _m.get("quotes",   0),
                    "views":    _m.get("views",    0),
                },
                "sentiment": {"label": _sl, "score": _ss},
                "content_analysis": {
                    "topic":           _ca.get("topic")           or "",
                    "mood":            _ca.get("mood")            or "",
                    "objects":         _ca.get("objects")         or "",
                    "activity":        _ca.get("activity")        or "",
                    "content_summary": _ca.get("content_summary") or (r.get("original_caption") or "")[:200],
                    "ai_description":  _ca.get("ai_description") or r.get("ai_description") or r.get("visual_description") or r.get("content_description") or "",
                    "key_themes":      _ca.get("key_themes")       or [],
                    "engagement_level": _ca.get("engagement_level") or "RENDAH",
                },
            }

        def _fmt_x_quote(q: dict) -> dict:
            """Format satu quote tweet untuk X."""
            _ca   = q.get("content_analysis") or {}
            _sent = q.get("sentiment") or {"label": "NEUTRAL", "score": 0.5}
            _sl   = _sent.get("label", "NEUTRAL") if isinstance(_sent, dict) else str(_sent)
            _ss   = _sent.get("score", 0.5) if isinstance(_sent, dict) else 0.5
            _m    = q.get("metrics") or {}
            return {
                "tweet_id":         q.get("post_id")  or q.get("id") or "",
                "tweet_url":        q.get("tweet_url") or q.get("post_url") or "",
                "quote_comment":    q.get("quote_comment") or q.get("content") or "",
                "original_author":  q.get("original_author")  or "",
                "original_text":    q.get("original_text")    or "",
                "quoted_tweet_url": q.get("referenced_tweet_url") or "",
                "created_at":       q.get("created_at") or "",
                "hashtags":         q.get("hashtags") or [],
                "mentions":         q.get("mentions") or [],
                "metrics": {
                    "likes":    q.get("likes", 0),
                    "retweets": q.get("shares", 0),
                    "replies":  q.get("comments", 0),
                    "quotes":   q.get("quotes", 0),
                    "views":    q.get("plays", 0),
                },
                "sentiment": {"label": _sl, "score": _ss},
                "content_analysis": {
                    "topic":           _ca.get("topic")           or "",
                    "mood":            _ca.get("mood")            or "",
                    "objects":         _ca.get("objects")         or "",
                    "activity":        _ca.get("activity")        or "",
                    "content_summary": _ca.get("content_summary") or (q.get("content") or "")[:200],
                    "ai_description":  _ca.get("ai_description") or a.get("ai_description") or a.get("visual_description") or "",
                    "key_themes":      _ca.get("key_themes")       or [],
                    "engagement_level": _ca.get("engagement_level") or "RENDAH",
                },
            }

        # Pisahkan activities berdasarkan tipe
        _x_posts     = [_fmt_tweet(a) for a in enriched_activities
                        if a.get("tweet_type") == "POST" or
                        (not a.get("is_repost") and not a.get("is_quote") and not a.get("is_reply"))]
        _x_replies   = [_fmt_tweet(a) for a in enriched_activities if a.get("tweet_type") == "REPLY"]
        _x_quotes_ea = [_fmt_tweet(a) for a in enriched_activities if a.get("tweet_type") == "QUOTE"]
        _x_all       = [_fmt_tweet(a) for a in enriched_activities]  # semua termasuk replies

        _x_comments   = [_fmt_x_comment(uc) for uc in user_comments]
        _x_retweets   = [_fmt_x_retweet(r)  for r in reposts]
        _x_quotes_fmt = [_fmt_x_quote(q)    for q in quotes_list]

        # Statistik ringkasan
        _total_likes_x  = sum(a.get("likes", 0) for a in enriched_activities)
        _total_rts_x    = sum(a.get("shares", 0) for a in enriched_activities)
        _total_views_x  = sum(a.get("plays", 0)  for a in enriched_activities)
        _dominant_topics = _dom_topics[:5]

        # tweet_types_breakdown
        from collections import Counter as _CtrX
        _type_ctr = _CtrX(a.get("tweet_type") or "POST" for a in enriched_activities)
        _tweet_types_bd = dict(_type_ctr)

        # language_breakdown
        _lang_map = {"id": "Indonesian (id)", "in": "Indonesian (id)",
                     "en": "English (en)", "ja": "Japanese (ja)",
                     "ko": "Korean (ko)", "ar": "Arabic (ar)"}
        _lang_ctr = _CtrX(
            _lang_map.get(a.get("lang",""), a.get("lang","unknown"))
            for a in enriched_activities if a.get("lang")
        )
        _lang_bd = dict(_lang_ctr.most_common(10))

        # top_hashtags dari semua activities
        _all_ht_x = [ht for a in enriched_activities for ht in (a.get("hashtags") or [])]
        _top_ht_x = [ht for ht, _ in _CtrX(_all_ht_x).most_common(10)]

        return {
            "status":    "SUCCESS",
            "timestamp": datetime.now().isoformat(),
            "scan_meta": {
                "platform":           "X",
                "scan_type":          payload.scan_type.value,
                "target":             payload.target,
                "data_source_status": source_status,
                "db_user_id":         db_user.user_id,
                "scrape_errors":      scrape_errors,
                "data_limitations":   _sp.get("data_limitations", []),
            },
            "profile": {
                "username":      _sp.get("username",    payload.target),
                "full_name":     _sp.get("full_name",   ""),
                "bio":           _sp.get("bio",         ""),
                "followers":     _sp.get("followers",   0),
                "following":     _sp.get("following",   0),
                "verified":      _sp.get("verified",    False),
                "profile_pic":   _sp.get("profile_pic", ""),
                "banner_image":  _sp.get("banner_image",""),
                "user_id":       _sp.get("user_id",     ""),
                "profile_url":   f"https://x.com/{_sp.get('username', payload.target)}",
                "location":      _sp.get("location",   ""),
                "website":       _sp.get("website",    ""),
                "join_date":     _sp.get("join_date",  ""),
                "tweet_count":   _sp.get("tweet_count", 0),
                "total_posts":   _sp.get("total_posts", len(enriched_activities)),
                "total_likes":   _sp.get("total_likes", 0) or _total_likes_x,
                "platform":      "x",
                "last_updated":  datetime.now().strftime("%Y-%m-%d"),
            },
            "behavior_metrics": {
                "total_extracted":  len(_x_all),
                "total_posts":      len(_x_posts),
                "total_replies":    len(_x_replies),
                "total_retweets":   len(_x_retweets),
                "total_quotes":     len(_x_quotes_fmt),
                "total_user_comments": len(_x_comments),
                "total_likes":      _total_likes_x,
                "total_retweets_received": _total_rts_x,
                "total_views":      _total_views_x,
                # Breakdown tipe tweet: {"POST": N, "REPLY": N, "RETWEET": N, "QUOTE": N}
                "tweet_types_breakdown": _tweet_types_bd,
                # Breakdown bahasa: {"Indonesian (id)": N, "English (en)": N}
                "language_breakdown":    _lang_bd,
                # Top hashtags dari semua tweet
                "top_hashtags":          _top_ht_x,
                # Semua tweet (POST + REPLY + QUOTE) dengan content_analysis
                "activities":       _x_all,
                # Hanya original POST
                "original_posts":   _x_posts,
                # Reply yang DITULIS OLEH TARGET di post orang lain
                "user_comments":    _x_comments,
                # Tweet yang di-RT oleh target
                "retweets":         _x_retweets,
                # Quote tweet dari target — key ganda untuk kompatibilitas dashboard
                "quotes":           _x_quotes_fmt,
                "quotes_list":      _x_quotes_fmt,
            },
            "analytics_insight": {
                "sentiment_overall":   _ai.get("sentiment_overall",   "NEUTRAL"),
                "sentiment_score":     _ai.get("sentiment_score",     0.5),
                "sentiment_breakdown": _sent_bd,
                "risk_score":          _ai.get("risk_score",          0),
                "risk_level":          _ai.get("risk_level",          "RENDAH"),
                "personality":         _ai.get("personality",         {}),
                "summary_text":        _ai.get("summary_text",        ""),
                "ai_narrative":        _ai.get("ai_narrative",        ""),
                "ai_narrative_short":  _ai.get("ai_narrative_short",  ""),
                "dominant_topics":     _dominant_topics,
                "red_flags":           _ai.get("red_flags",           []),
                "green_flags":         _ai.get("green_flags",         []),
                "recommendation":      _ai.get("recommendation",      ""),
                "suitable_roles":      _ai.get("suitable_roles",      []),
                "comment_sentiment_overall":   _ci.get("comment_sentiment_overall",   "NEUTRAL"),
                "comment_sentiment_score":     _ci.get("comment_sentiment_score",     0.5),
                "comment_sentiment_breakdown": _ci.get("comment_sentiment_breakdown", {}),
                "comment_topics":              _ci.get("comment_topics",              []),
                "comment_style":               _ci.get("comment_style",               ""),
                "comment_red_flags":           _ci.get("comment_red_flags",           []),
                "comment_green_flags":         _ci.get("comment_green_flags",         []),
                "comment_summary":             _ci.get("comment_summary",             ""),
                "osint_findings":              osint_findings,
            },
        }

    # ── Response Facebook — format khusus dengan content_analysis per post ──
    if platform_val == "facebook":

        def _fmt_fb_post(a: dict) -> dict:
            _ca   = a.get("content_analysis") or {}
            _sent = a.get("sentiment") or {"label": "NEUTRAL", "score": 0.5}
            _sl   = _sent.get("label", "NEUTRAL") if isinstance(_sent, dict) else str(_sent)
            _ss   = _sent.get("score", 0.5)         if isinstance(_sent, dict) else 0.5
            _m    = a.get("metrics") or {}
            _rxn  = a.get("reactions") or {}
            return {
                "id":               a.get("post_id") or a.get("id") or "",
                "post_id":          a.get("post_id") or a.get("id") or "",
                "content":          a.get("content") or a.get("text") or "",
                "post_url":         a.get("post_url") or "",
                "created_at":           a.get("created_at") or "",
                "created_at_timestamp": a.get("created_at_timestamp") or 0,
                "created_at_iso":       a.get("created_at_iso") or "",
                "likes":    _m.get("likes",    0) or a.get("likes",    0),
                "comments": _m.get("comments", 0) or a.get("comments", 0),
                "shares":   _m.get("shares",   0) or a.get("shares",   0),
                "plays":    _m.get("plays",    0) or a.get("plays",    0),
                "reactions": {
                    "like":  _rxn.get("like",  0),
                    "love":  _rxn.get("love",  0),
                    "care":  _rxn.get("care",  0),
                    "haha":  _rxn.get("haha",  0),
                    "wow":   _rxn.get("wow",   0),
                    "sad":   _rxn.get("sad",   0),
                    "angry": _rxn.get("angry", 0),
                },
                "reactions_total": a.get("reactions_total") or sum(_rxn.values()),
                "video_url":   a.get("video_url")  or "",
                "image_url":   a.get("image_url")  or "",
                "image_urls":  a.get("image_urls") or [],
                "cover_url":   a.get("cover_url")  or "",
                "media_type":  a.get("media_type") or "text",
                "media_count": a.get("media_count") or 0,
                "media_list":  a.get("media_list") or [],
                "hashtags":     a.get("hashtags")     or [],
                "mentions":     a.get("mentions")     or [],
                "tagged_users": a.get("tagged_users") or [],
                "urls":         a.get("urls")         or [],
                "is_ad":        bool(a.get("is_ad")),
                "is_repost":    bool(a.get("is_repost")),
                "is_sponsored": bool(a.get("is_sponsored")),
                "is_pinned":    bool(a.get("is_pinned")),
                "is_story":     bool(a.get("is_story")),
                "visual_description": a.get("visual_description") or "",
                "topic":    _ca.get("topic")    or a.get("topic")    or "",
                "mood":     _ca.get("mood")     or a.get("mood")     or "",
                "objects":  _ca.get("objects")  or a.get("objects")  or "",
                "activity": _ca.get("activity") or a.get("activity") or "",
                "sentiment": {"label": _sl, "score": _ss},
                "content_analysis": {
                    "topic":             _ca.get("topic")            or "",
                    "mood":              _ca.get("mood")             or "",
                    "objects":           _ca.get("objects")          or "",
                    "activity":          _ca.get("activity")         or "",
                    "content_summary":   _ca.get("content_summary")  or "",
                    "ai_description":    _ca.get("ai_description") or a.get("ai_description") or a.get("visual_description") or "",
                    "key_themes":        _ca.get("key_themes")        or [],
                    "engagement_level":  _ca.get("engagement_level") or "RENDAH",
                    "word_count":        _ca.get("word_count")        or 0,
                    "readability_score": _ca.get("readability_score") or 0,
                    "language":          _ca.get("language")          or "",
                    "detected_emotions": _ca.get("detected_emotions") or [],
                },
                "comments_data":          a.get("comments_data") or [],
                "comments_count_total":   a.get("comments_count_total")   or 0,
                "comments_count_visible": a.get("comments_count_visible") or 0,
            }

        def _fmt_fb_comment(uc: dict) -> dict:
            _sent = uc.get("sentiment") or {"label": "NEUTRAL", "score": 0.5}
            _sl   = _sent.get("label", "NEUTRAL") if isinstance(_sent, dict) else str(_sent)
            _ss   = _sent.get("score", 0.5)         if isinstance(_sent, dict) else 0.5
            return {
                "post_url":     uc.get("post_url")     or "",
                "post_caption": uc.get("post_caption") or "",
                "content":      uc.get("content") or uc.get("comment_text") or "",
                "likes":        uc.get("likes",  0),
                "is_reply":     bool(uc.get("is_reply")),
                "reply_to":     uc.get("reply_to") or "",
                "created_at":   uc.get("created_at") or "",
                "comment_url":  uc.get("comment_url") or "",
                "sentiment":    {"label": _sl, "score": _ss},
            }

        def _fmt_fb_repost(r: dict) -> dict:
            _ca   = r.get("content_analysis") or {}
            _sent = r.get("sentiment") or {"label": "NEUTRAL", "score": 0.5}
            _sl   = _sent.get("label", "NEUTRAL") if isinstance(_sent, dict) else str(_sent)
            _ss   = _sent.get("score", 0.5)         if isinstance(_sent, dict) else 0.5
            _rxn  = r.get("reactions") or {}
            _m    = r.get("metrics")   or {}
            return {
                "post_url":            r.get("video_url")           or "",
                "original_author":     r.get("original_author")     or "",
                "original_author_url": r.get("original_author_url") or "",
                "original_caption":    r.get("original_caption")    or "",
                "repost_date":         r.get("repost_date")          or "",
                "hashtags":            r.get("hashtags")             or [],
                "media_type":          r.get("media_type")           or "text",
                "image_url":           r.get("image_url")            or "",
                "metrics": {
                    "likes":    _m.get("likes",    0),
                    "comments": _m.get("comments", 0),
                    "shares":   _m.get("shares",   0),
                    "plays":    _m.get("plays",    0),
                },
                "reactions":       _rxn,
                "reactions_total": r.get("reactions_total") or sum(_rxn.values()),
                "sentiment":       {"label": _sl, "score": _ss},
                "content_analysis": {
                    "topic":            _ca.get("topic")            or "",
                    "mood":             _ca.get("mood")             or "",
                    "ai_description":   _ca.get("ai_description")   or r.get("content_description") or "",
                    "engagement_level": _ca.get("engagement_level") or "RENDAH",
                },
            }

        _fb_posts    = [_fmt_fb_post(a)     for a in enriched_activities]
        _fb_comments = [_fmt_fb_comment(uc) for uc in user_comments]
        _fb_reposts  = [_fmt_fb_repost(r)   for r in reposts]
        # photos ada di platform_photos (dari scrape_result), bukan scrape_profile
        _fb_photos   = platform_photos or _sp.get("photos") or []

        # Fallback: extract photos dari posts jika photo scraper gagal
        if not _fb_photos:
            for _fp in enriched_activities:
                _img = _fp.get("image_url") or ""
                _imgs = _fp.get("image_urls") or []
                _all_imgs = _imgs if _imgs else ([_img] if _img else [])
                for _iu in _all_imgs:
                    if _iu and len(_fb_photos) < 10:
                        _fb_photos.append({
                            "image_url":  _iu,
                            "photo_page": _fp.get("post_url", ""),
                            "caption":    (_fp.get("content") or "")[:80],
                            "album":      "Timeline",
                            "likes":      _fp.get("likes", 0),
                            "date":       _fp.get("created_at", ""),
                        })

        _fb_total_likes    = sum(p.get("likes",    0) for p in _fb_posts)
        _fb_total_comments = sum(p.get("comments", 0) for p in _fb_posts)
        _fb_total_shares   = sum(p.get("shares",   0) for p in _fb_posts)
        _fb_total_rxn      = sum(p.get("reactions_total", 0) for p in _fb_posts)

        # ── Reels: ambil dari scrape_result["reels"] (dedicated scraper)
        # TIDAK fallback ke posts — reels dan posts harus beda konten
        _raw_reels = platform_reels or _sp.get("reels") or scrape_result.get("reels") or []
        _fb_reels  = [_fmt_fb_post(r) for r in _raw_reels][:10]

        # ── Mentions: posts dengan @mention atau tagged_users
        # Tidak fallback ke semua posts — tampilkan empty jika memang tidak ada
        _fb_mentions = [p for p in _fb_posts
                        if (p.get("mentions") and len(p.get("mentions", [])) > 0)
                        or (p.get("tagged_users") and len(p.get("tagged_users", [])) > 0)
                        or "@" in (p.get("content") or "")][:10]
        # Level 2: ada hashtag di konten
        if not _fb_mentions:
            _fb_mentions = [p for p in _fb_posts
                            if "#" in (p.get("content") or "")
                            or (p.get("hashtags") and len(p.get("hashtags", [])) > 0)][:10]
        # Level 3: jika masih kosong, TIDAK fallback ke semua posts
        # Biarkan kosong — UI akan tampilkan empty state

        return {
            "status":    "SUCCESS",
            "timestamp": datetime.now().isoformat(),
            "scan_meta": {
                "platform":           "FACEBOOK",
                "scan_type":          payload.scan_type.value,
                "target":             payload.target,
                "data_source_status": source_status,
                "db_user_id":         db_user.user_id,
                "scrape_errors":      scrape_errors,
            },
            "profile": {
                "username":    _sp.get("username",    payload.target),
                "full_name":   _sp.get("full_name",   ""),
                "bio":         _sp.get("bio",         ""),
                "about_me":    _sp.get("about_me",    ""),
                "followers":   _sp.get("followers",   0),
                "following":   _sp.get("following",   0),
                "page_likes":  _sp.get("page_likes",  0),
                "verified":    _sp.get("verified",    False),
                "profile_pic": _sp.get("profile_pic", ""),
                "cover_photo": _sp.get("cover_photo", ""),
                "user_id":     _sp.get("user_id",     ""),
                "profile_url": _sp.get("profile_url",
                                        f"https://www.facebook.com/{payload.target}"),
                "location":    _sp.get("location",   ""),
                "address":     _sp.get("address",    ""),
                "website":     _sp.get("website",    ""),
                "email":       _sp.get("email",      ""),
                "phone":       _sp.get("phone",      ""),
                "categories":  _sp.get("categories", []),
                "rating":      _sp.get("rating",     ""),
                "join_date":   _sp.get("join_date",  ""),
                "total_posts": _sp.get("total_posts", len(enriched_activities)),
                "total_likes": _sp.get("total_likes", 0) or _fb_total_likes,
                "platform":    "facebook",
                "last_updated": datetime.now().strftime("%Y-%m-%d"),
            },
            "behavior_metrics": {
                "total_extracted":     len(_fb_posts),
                "total_likes":         _fb_total_likes,
                "total_comments":      _fb_total_comments,
                "total_shares":        _fb_total_shares,
                "total_reactions":     _fb_total_rxn,
                "total_user_comments": len(_fb_comments),
                "total_reposts":       len(_fb_reposts),
                "total_photos":        len(_fb_photos),
                "total_reels":         len(_fb_reels),
                "total_mentions":      len(_fb_mentions),
                "activities":          _fb_posts,
                "user_comments":       _fb_comments,
                "reposts":             _fb_reposts,
                "photos":              _fb_photos,
                "reels":               _fb_reels,
                "mentions":            _fb_mentions,
            },
            "analytics_insight": {
                "sentiment_overall":   _ai.get("sentiment_overall",   "NEUTRAL"),
                "sentiment_score":     _ai.get("sentiment_score",     0.5),
                "sentiment_breakdown": _sent_bd,
                "risk_score":          _ai.get("risk_score",          0),
                "risk_level":          _ai.get("risk_level",          "RENDAH"),
                "personality":         _ai.get("personality",         {}),
                "summary_text":        _ai.get("summary_text",        ""),
                "ai_narrative":        _ai.get("ai_narrative",        ""),
                "ai_narrative_short":  _ai.get("ai_narrative_short",  ""),
                "dominant_topics":     _dom_topics[:5],
                "red_flags":           _ai.get("red_flags",           []),
                "green_flags":         _ai.get("green_flags",         []),
                "recommendation":      _ai.get("recommendation",      ""),
                "suitable_roles":      _ai.get("suitable_roles",      []),
                "comment_sentiment_overall":   _ci.get("comment_sentiment_overall",   "NEUTRAL"),
                "comment_sentiment_score":     _ci.get("comment_sentiment_score",     0.5),
                "comment_sentiment_breakdown": _ci.get("comment_sentiment_breakdown", {}),
                "comment_topics":              _ci.get("comment_topics",              []),
                "comment_style":               _ci.get("comment_style",               ""),
                "comment_summary":             _ci.get("comment_summary",             ""),
                "osint_findings":              osint_findings,
            },
        }

    # ── Response LinkedIn — format khusus dengan content_analysis per post ──
    if platform_val == "linkedin":

        def _fmt_li_post(a: dict) -> dict:
            """Format satu LinkedIn post untuk response JSON."""
            _ca   = a.get("content_analysis") or {}
            _sent = a.get("sentiment") or {"label": "NEUTRAL", "score": 0.5}
            _sl   = _sent.get("label", "NEUTRAL") if isinstance(_sent, dict) else str(_sent)
            _ss   = _sent.get("score", 0.5)        if isinstance(_sent, dict) else 0.5
            _m    = a.get("metrics") or {}
            _rb   = a.get("reactions_breakdown") or {}
            return {
                "id":                    a.get("post_id") or a.get("id") or "",
                "post_id":               a.get("post_id") or a.get("id") or "",
                "content":               a.get("content") or "",
                "post_url":              a.get("post_url") or a.get("tweet_url") or "",
                "created_at":            a.get("created_at") or "",
                "created_at_timestamp":  a.get("created_at_timestamp") or 0,
                "created_at_iso":        a.get("created_at_iso") or "",
                "likes":    _m.get("likes",    0) or a.get("likes",    0),
                "comments": _m.get("comments", 0) or a.get("comments", 0),
                "shares":   _m.get("shares",   0) or a.get("shares",   0),
                "plays":    0,
                "reactions_breakdown": _rb,
                "reactions_total":     a.get("reactions_total") or sum(_rb.values()),
                "reactions_actors":    a.get("reactions_actors") or [],
                "image_url":   a.get("image_url")  or "",
                "video_url":   a.get("video_url")  or "",
                "cover_url":   a.get("cover_url")  or "",
                "media_type":  a.get("media_type") or "text",
                "media_count": a.get("media_count") or 0,
                "media_list":  a.get("media_list") or [],
                "hashtags":     a.get("hashtags")     or [],
                "mentions":     a.get("mentions")     or [],
                "tagged_users": a.get("tagged_users") or [],
                "urls":         a.get("urls")         or [],
                "is_ad":        bool(a.get("is_ad")),
                "is_repost":    bool(a.get("is_repost")),
                "is_sponsored": bool(a.get("is_sponsored")),
                "is_pinned":    bool(a.get("is_pinned")),
                "is_article":   bool(a.get("is_article")),
                "document":     a.get("document")     or {},
                "article":      a.get("article")      or {},
                "post_images":  a.get("post_images")  or [],
                "comments_data":          a.get("comments_data") or [],
                "comments_count_total":   a.get("comments_count_total")   or 0,
                "comments_count_visible": a.get("comments_count_visible") or 0,
                # ── Content Analysis ──────────────────────────────────────
                "visual_description": (
                    _ca.get("visual_description") or a.get("visual_description") or ""
                ),
                "topic":    _ca.get("topic")    or a.get("topic")    or "",
                "mood":     _ca.get("mood")     or a.get("mood")     or "",
                "objects":  _ca.get("objects")  or a.get("objects")  or "",
                "activity": _ca.get("activity") or a.get("activity") or "",
                "sentiment": {"label": _sl, "score": _ss},
                "content_analysis": {
                    "topic":             _ca.get("topic")            or "",
                    "mood":              _ca.get("mood")             or "",
                    "objects":           _ca.get("objects")          or "",
                    "activity":          _ca.get("activity")         or "",
                    "content_summary":   _ca.get("content_summary")  or "",
                    "ai_description":    (_ca.get("ai_description")  or
                                          a.get("ai_description")   or ""),
                    "visual_description":(_ca.get("visual_description") or
                                          a.get("visual_description") or ""),
                    "key_themes":        _ca.get("key_themes")        or [],
                    "engagement_level":  _ca.get("engagement_level") or "RENDAH",
                    "word_count":        _ca.get("word_count")        or 0,
                    "readability_score": _ca.get("readability_score") or 0,
                    "language":          _ca.get("language")          or "",
                    "detected_emotions": _ca.get("detected_emotions") or [],
                },
            }

        def _fmt_li_comment(uc: dict) -> dict:
            """Format satu LinkedIn user_comment dengan semua field lengkap."""
            _sent = uc.get("sentiment") or {"label": "NEUTRAL", "score": 0.5}
            _sl   = _sent.get("label", "NEUTRAL") if isinstance(_sent, dict) else str(_sent)
            _ss   = _sent.get("score", 0.5)        if isinstance(_sent, dict) else 0.5
            _ca   = uc.get("content_analysis") or {}
            return {
                # ── Identitas ─────────────────────────────────────────────
                "comment_id":   uc.get("comment_id")  or "",
                "comment_url":  uc.get("comment_url") or "",
                "post_url":     uc.get("post_url")     or "",
                "post_caption": uc.get("post_caption") or "",
                "post_author":  uc.get("post_author")  or "",
                # ── Isi komentar ──────────────────────────────────────────
                "content":     uc.get("content") or uc.get("comment_text") or "",
                # ── Metrics ───────────────────────────────────────────────
                "likes":       uc.get("likes",       0),
                "replies":     uc.get("replies",     0),
                "num_replies": uc.get("num_replies", 0),
                # ── Flags ─────────────────────────────────────────────────
                "is_reply":    bool(uc.get("is_reply")),
                "reply_to":    uc.get("reply_to") or "",
                # ── Waktu ─────────────────────────────────────────────────
                "created_at":  uc.get("created_at") or "",
                # ── Sentimen ─────────────────────────────────────────────
                "sentiment":   {"label": _sl, "score": _ss},
                # ── Content Analysis ─────────────────────────────────────
                "content_analysis": {
                    "topic":            _ca.get("topic")            or "",
                    "mood":             _ca.get("mood")             or "",
                    "objects":          _ca.get("objects")          or "",
                    "activity":         _ca.get("activity")         or "",
                    "ai_description":   _ca.get("ai_description")   or "",
                    "engagement_level": _ca.get("engagement_level") or "RENDAH",
                },
            }

        def _fmt_li_repost(r: dict) -> dict:
            _ca   = r.get("content_analysis") or {}
            _sent = r.get("sentiment") or {"label": "NEUTRAL", "score": 0.5}
            _sl   = _sent.get("label", "NEUTRAL") if isinstance(_sent, dict) else str(_sent)
            _ss   = _sent.get("score", 0.5)        if isinstance(_sent, dict) else 0.5
            _m    = r.get("metrics") or {}
            _rb   = r.get("reactions_breakdown") or {}
            return {
                "post_url":            r.get("video_url")           or "",
                "original_author":     r.get("original_author")     or "",
                "original_author_url": r.get("original_author_url") or "",
                "original_caption":    r.get("original_caption")    or "",
                "repost_date":         r.get("repost_date")          or "",
                "hashtags":            r.get("hashtags")             or [],
                "media_type":          r.get("media_type")           or "text",
                "metrics": {
                    "likes":    _m.get("likes",    0),
                    "comments": _m.get("comments", 0),
                    "shares":   _m.get("shares",   0),
                    "plays":    0,
                },
                "reactions_breakdown": _rb,
                "sentiment": {"label": _sl, "score": _ss},
                "content_analysis": {
                    "topic":          _ca.get("topic")          or "",
                    "ai_description": _ca.get("ai_description") or r.get("content_description") or "",
                    "engagement_level": _ca.get("engagement_level") or "RENDAH",
                },
            }

        _li_posts    = [_fmt_li_post(a)     for a in enriched_activities if not a.get("is_repost")]
        _li_reposts  = [_fmt_li_repost(r)   for r in reposts]
        _li_comments = [_fmt_li_comment(uc) for uc in user_comments]

        # ── Statistics ────────────────────────────────────────────────────
        _li_tl = sum(p.get("likes",    0) for p in _li_posts)
        _li_tc = sum(p.get("comments", 0) for p in _li_posts)
        _li_ts = sum(p.get("shares",   0) for p in _li_posts)
        _li_n  = len(_li_posts)
        _li_avg_l = round(_li_tl / _li_n, 1) if _li_n else 0
        _li_avg_c = round(_li_tc / _li_n, 1) if _li_n else 0
        _li_avg_s = round(_li_ts / _li_n, 1) if _li_n else 0
        _li_followers = _sp.get("followers", 0)
        _li_eng_rate  = round((_li_tl + _li_tc + _li_ts) / (_li_followers * _li_n)
                               if _li_followers and _li_n else 0, 4)

        # Top hashtags dari semua posts
        from collections import Counter as _Ctr2
        _all_ht: List[str] = []
        for _p in _li_posts:
            _all_ht.extend(_p.get("hashtags") or [])
        _top_ht = [h for h, _ in _Ctr2(_all_ht).most_common(10)]

        # Top mentions
        _all_mn: List[str] = []
        for _p in _li_posts:
            _all_mn.extend(_p.get("mentions") or [])
        _top_mn = [m for m, _ in _Ctr2(_all_mn).most_common(5)]

        # Engagement buckets
        _viral   = sum(1 for p in _li_posts if p.get("content_analysis", {}).get("engagement_level") == "VIRAL")
        _hi_eng  = sum(1 for p in _li_posts if p.get("content_analysis", {}).get("engagement_level") in ("SANGAT TINGGI", "TINGGI"))
        _med_eng = sum(1 for p in _li_posts if p.get("content_analysis", {}).get("engagement_level") == "SEDANG")
        _low_eng = sum(1 for p in _li_posts if p.get("content_analysis", {}).get("engagement_level") == "RENDAH")

        return {
            "status":    "SUCCESS",
            "timestamp": datetime.now().isoformat(),
            "scan_meta": {
                "platform":           "LINKEDIN",
                "scan_type":          payload.scan_type.value,
                "target":             payload.target,
                "data_source_status": source_status,
                "db_user_id":         db_user.user_id,
                "scrape_errors":      scrape_errors,
                "actors_used": [
                    "linkedintel-core/linkedin-profile-scraper-no-cookies",
                    "harvestapi/linkedin-profile-posts",
                    "datadoping/linkedin-post-comments-scraper",
                ],
            },
            "profile": {
                "username":          _sp.get("username",        payload.target),
                "user_id":           _sp.get("user_id",         ""),
                "full_name":         _sp.get("full_name",       ""),
                "headline":          _sp.get("headline",        ""),
                "bio":               _sp.get("bio",             ""),
                "about":             _sp.get("about",           ""),
                "profile_pic":       _sp.get("profile_pic",    ""),
                "background_image":  _sp.get("background_image",""),
                "linkedin_url":      _sp.get("linkedin_url",
                                              f"https://www.linkedin.com/in/{payload.target}"),
                "website":           _sp.get("website",        ""),
                "website_label":     _sp.get("website_label",  ""),
                "location":          _sp.get("location",       ""),
                "industry":          _sp.get("industry",       ""),
                "followers":         _sp.get("followers",       0),
                "following":         _sp.get("following",       0),
                "connections_count": _sp.get("connections_count", 0),
                "connections":       _sp.get("connections",    ""),
                "verified":          _sp.get("verified",       False),
                "is_creator":        _sp.get("is_creator",     False),
                "is_premium":        _sp.get("is_premium",     False),
                "is_influencer":     _sp.get("is_influencer",  False),
                "is_open_to_work":   _sp.get("is_open_to_work", False),
                "is_hiring":         _sp.get("is_hiring",      False),
                "join_date":         _sp.get("join_date",      ""),
                "current_company":   _sp.get("current_company",""),
                "current_title":     _sp.get("current_title",  ""),
                # ── Profile sections ──────────────────────────────────────
                "experience":        _sp.get("experience",     []),
                "education":         _sp.get("education",      []),
                "skills":            _sp.get("skills",         []),
                "certifications":    _sp.get("certifications", []),
                "languages":         _sp.get("languages",      []),
                "interests":         _sp.get("interests",      []),
                "volunteering":      _sp.get("volunteering",   []),
                "projects":          _sp.get("projects",       []),
                "publications":      _sp.get("publications",   []),
                "honors":            _sp.get("honors",         []),
                "courses":           _sp.get("courses",        []),
                "organizations":     _sp.get("organizations",  []),
                "contact_email":     _sp.get("contact_email",  ""),
                "contact_phone":     _sp.get("contact_phone",  ""),
                # ── Stats ─────────────────────────────────────────────────
                "total_posts":   _sp.get("total_posts",  _li_n),
                "total_likes":   _sp.get("total_likes",  0) or _li_tl,
                "total_comments":_sp.get("total_comments",0) or _li_tc,
                "total_shares":  _sp.get("total_shares", 0) or _li_ts,
                "has_text":      _sp.get("has_text",     bool(_li_posts)),
                "platform":      "linkedin",
                "last_updated":  datetime.now().strftime("%Y-%m-%d"),
                "data_limitations": _sp.get("data_limitations", [
                    "private_posts: tidak bisa diakses",
                    "dm: tidak bisa diakses",
                    "connections_list: selalu privat",
                    "email_phone: hanya tersedia jika user set public",
                    "video_views: tidak di-expose free API",
                ]),
            },
            "behavior_metrics": {
                # ── Counts ────────────────────────────────────────────────
                "total_extracted":         _li_n,
                "total_posts":             _li_n,
                "total_articles":          sum(1 for p in _li_posts if p.get("is_article")),
                "total_reposts":           len(_li_reposts),
                "total_user_comments":     len(_li_comments),
                "total_likes_received":    _li_tl,
                "total_comments_received": _li_tc,
                "total_shares_received":   _li_ts,
                "total_reactions":         _li_tl,
                # ── Averages ──────────────────────────────────────────────
                "average_likes_per_post":    _li_avg_l,
                "average_comments_per_post": _li_avg_c,
                "average_shares_per_post":   _li_avg_s,
                "engagement_rate":           _li_eng_rate,
                # ── Patterns ─────────────────────────────────────────────
                "top_hashtags":  _top_ht,
                "top_mentions":  _top_mn,
                # ── Engagement buckets ────────────────────────────────────
                "viral_posts_count":           _viral,
                "high_engagement_posts_count": _hi_eng,
                "medium_engagement_posts_count": _med_eng,
                "low_engagement_posts_count":  _low_eng,
                # ── Data ─────────────────────────────────────────────────
                "activities":    _li_posts,
                "user_comments": _li_comments,
                "user_comments_summary": _sp.get("user_comments_summary") or {},
                "reposts":       _li_reposts,
                "photos":        _sp.get("photos") or [],
            },
            "analytics_insight": {
                "sentiment_overall":   _ai.get("sentiment_overall",   "NEUTRAL"),
                "sentiment_score":     _ai.get("sentiment_score",     0.5),
                "sentiment_breakdown": _sent_bd,
                "risk_score":          _ai.get("risk_score",          0),
                "risk_level":          _ai.get("risk_level",          "RENDAH"),
                "personality":         _ai.get("personality",         {}),
                "summary_text":        _ai.get("summary_text",        ""),
                "ai_narrative":        _ai.get("ai_narrative",        ""),
                "ai_narrative_short":  _ai.get("ai_narrative_short",  ""),
                "dominant_topics":     _dom_topics[:5],
                "red_flags":           _ai.get("red_flags",           []),
                "green_flags":         _ai.get("green_flags",         []),
                "recommendation":      _ai.get("recommendation",      ""),
                "suitable_roles":      _ai.get("suitable_roles",      []),
                "comment_sentiment_overall":   _ci.get("comment_sentiment_overall",   "NEUTRAL"),
                "comment_sentiment_score":     _ci.get("comment_sentiment_score",     0.5),
                "comment_sentiment_breakdown": _ci.get("comment_sentiment_breakdown", {}),
                "comment_topics":              _ci.get("comment_topics",              []),
                "comment_style":               _ci.get("comment_style",               ""),
                "comment_red_flags":           _ci.get("comment_red_flags",           []),
                "comment_green_flags":         _ci.get("comment_green_flags",         []),
                "comment_summary":             _ci.get("comment_summary",             ""),
                "osint_findings":              osint_findings,
            },
        }

    # ── Response Instagram — dedicated block, beda dari TikTok ──────────────
    if platform_val == "instagram":

        def _fmt_ig_post(a: dict) -> dict:
            """Format satu post Instagram — image / carousel / reel."""
            _ca   = a.get("content_analysis") or {}
            _sent = a.get("sentiment") or {"label": "NEUTRAL", "score": 0.5}
            _sl   = _sent.get("label", "NEUTRAL") if isinstance(_sent, dict) else str(_sent)
            _ss   = _sent.get("score", 0.5)        if isinstance(_sent, dict) else 0.5
            _m    = a.get("metrics") or {}
            _cap  = a.get("content") or a.get("text") or ""
            _med  = a.get("media_type") or "image"
            _pid  = a.get("post_id") or a.get("id") or ""
            _sc   = a.get("shortcode") or _pid
            _purl = a.get("post_url") or (
                f"https://www.instagram.com/p/{_sc}/" if _sc else ""
            )
            # AI description: ambil dari field baru atau fallback ke visual_description
            _vd = (
                a.get("ai_description") or
                _ca.get("ai_description") or
                a.get("visual_description") or
                a.get("content_description") or
                ""
            )
            _vis = a.get("visual_description") or ""

            return {
                # ── Identitas ─────────────────────────────────────────────
                "post_id":       _pid or _sc,
                "shortcode":     _sc,
                "post_url":      _purl,
                "instagram_url": _purl,
                # ── Konten ───────────────────────────────────────────────
                "caption":        _cap,
                "media_type":     _med,           # image | carousel | video | reel
                "image_url":      a.get("image_url")  or a.get("cover_url")  or "",
                "video_url":      a.get("video_url")  or "",
                "cover_url":      a.get("cover_url")  or a.get("image_url")  or "",
                "images_list":    a.get("images_list") or a.get("image_urls") or [],  # foto slide TikTok/carousel IG
                "image_urls":     a.get("image_urls") or a.get("images_list") or [],  # alias
                "duration_sec":   a.get("duration_sec") or 0,
                "location":       a.get("location") or "",
                "hashtags":       a.get("hashtags") or [],
                "mentions":       a.get("mentions") or [],
                "is_pinned":      bool(a.get("is_pinned")),
                "is_sponsored":   bool(a.get("is_sponsored")),
                "is_repost":      bool(a.get("is_repost")),
                "repost_author":  a.get("repost_author") or "",
                "created_at":     a.get("created_at") or "",
                # ── Metrics ───────────────────────────────────────────────
                "likes":    _m.get("likes",    0) or a.get("likes",    0),
                "comments": _m.get("comments", 0) or a.get("comments", 0),
                "shares":   _m.get("shares",   0) or a.get("shares",   0),
                "views":    (_m.get("plays",   0) or a.get("plays",    0) or
                             a.get("views",    0) or a.get("videoViewCount", 0)),
                # ── AI Analysis ───────────────────────────────────────────
                "topic":              a.get("topic")    or _ca.get("topic")    or "",
                "mood":               a.get("mood")     or _ca.get("mood")     or "",
                "objects":            a.get("objects")  or _ca.get("objects")  or "",
                "activity":           a.get("activity") or _ca.get("activity") or "",
                "visual_description": _vis,
                "ai_description":     _vd,
                "analysis_method":    a.get("analysis_method") or "caption_only",
                "sentiment": {
                    "label": _sl,
                    "score": _ss,
                },
            }

        def _fmt_ig_comment(uc: dict) -> dict:
            """Format satu komentar/reply yang ditulis target di postnya sendiri."""
            _sent = uc.get("sentiment") or {"label": "NEUTRAL", "score": 0.5}
            _sl   = _sent.get("label", "NEUTRAL") if isinstance(_sent, dict) else str(_sent)
            _ss   = _sent.get("score", 0.5)        if isinstance(_sent, dict) else 0.5
            _purl = uc.get("post_url") or ""
            _pcap = uc.get("post_caption") or ""
            return {
                # ── Post yang dikomentari ─────────────────────────────────
                "post_url":     _purl,
                "post_caption": _pcap,
                # ── Komentar ─────────────────────────────────────────────
                "comment_text": uc.get("content") or uc.get("comment_text") or "",
                "likes":        uc.get("likes", 0),
                "replies":      uc.get("replies", 0),
                "is_reply":     bool(uc.get("is_reply")),
                "reply_to":     uc.get("reply_to") or "",   # username yang dibalas
                "created_at":   uc.get("created_at") or "",
                "sentiment": {
                    "label": _sl,
                    "score": _ss,
                },
            }

        def _fmt_ig_repost(r: dict) -> dict:
            """Format satu repost Instagram."""
            _sent = r.get("sentiment") or {"label": "NEUTRAL", "score": 0.5}
            _sl   = _sent.get("label", "NEUTRAL") if isinstance(_sent, dict) else str(_sent)
            _ss   = _sent.get("score", 0.5)        if isinstance(_sent, dict) else 0.5
            _m    = r.get("metrics") or {}
            _purl = r.get("post_url") or r.get("video_url") or ""
            _vd   = r.get("ai_description") or r.get("visual_description") or r.get("content_description") or ""
            _vid  = r.get("video_file_url") or r.get("video_url") or ""
            # Jangan pakai page URL sebagai video_url
            if _vid and ("instagram.com" in _vid and "/p/" in _vid):
                _vid = ""
            _img  = r.get("image_url") or r.get("cover_url") or r.get("thumbnail_url") or ""
            _cover = r.get("cover_url") or r.get("thumbnail_url") or r.get("image_url") or ""
            _imgs = r.get("images_list") or r.get("image_urls") or (([_img] if _img else []))
            return {
                # ── Sumber konten ─────────────────────────────────────────
                "post_url":        _purl,
                "original_author": r.get("original_author") or "",
                "original_caption": r.get("original_caption") or r.get("caption") or "",
                "caption":         r.get("original_caption") or r.get("caption") or "",
                # ── Media ─────────────────────────────────────────────────
                "media_type":     r.get("media_type") or r.get("post_type") or "image",
                "image_url":      _img,
                "cover_url":      _cover,
                "video_url":      _vid,
                "images_list":    _imgs,
                "image_urls":     _imgs,
                "hashtags":       r.get("hashtags") or [],
                "repost_date":    r.get("repost_date") or r.get("created_at") or "",
                "created_at":     r.get("repost_date") or r.get("created_at") or "",
                # ── Metrics ───────────────────────────────────────────────
                "likes":    _m.get("likes",    0) or r.get("likes",    0),
                "comments": _m.get("comments", 0) or r.get("comments", 0),
                "shares":   _m.get("shares",   0) or r.get("shares",   0),
                "views":    _m.get("plays",    0) or r.get("plays",    0),
                # ── AI Analysis ───────────────────────────────────────────
                "topic":              r.get("topic") or "",
                "visual_description": r.get("visual_description") or "",
                "ai_description":     _vd,
                "is_repost":          True,
                "sentiment": {"label": _sl, "score": _ss},
            }

        # Format semua data
        _ig_posts    = [_fmt_ig_post(a)     for a in enriched_activities if not a.get("is_repost")]
        _ig_comments = [_fmt_ig_comment(uc) for uc in user_comments]
        _ig_reposts  = [_fmt_ig_repost(r)   for r in reposts]

        # Statistik
        _ig_n       = len(_ig_posts)
        _ig_tl      = sum(p.get("likes",    0) for p in _ig_posts)
        _ig_tc      = sum(p.get("comments", 0) for p in _ig_posts)
        _ig_tv      = sum(p.get("views",    0) for p in _ig_posts)
        _ig_avg_l   = round(_ig_tl / _ig_n, 1) if _ig_n else 0
        _ig_avg_c   = round(_ig_tc / _ig_n, 1) if _ig_n else 0
        _ig_eng     = round((_ig_tl + _ig_tc) / (_sp.get("followers", 1) * max(_ig_n, 1)) * 100, 3) if _sp.get("followers") else 0

        # Hitung media type breakdown
        from collections import Counter as _Ctr3
        _med_breakdown = dict(_Ctr3(p.get("media_type","image") for p in _ig_posts))
        _top_ht_ig = [h for h, _ in _Ctr3(
            ht for p in _ig_posts for ht in (p.get("hashtags") or [])
        ).most_common(10)]
        _top_mn_ig = [m for m, _ in _Ctr3(
            mn for p in _ig_posts for mn in (p.get("mentions") or [])
        ).most_common(5)]

        return {
            "status":    "SUCCESS",
            "timestamp": datetime.now().isoformat(),
            "scan_meta": {
                "platform":           "INSTAGRAM",
                "scan_type":          payload.scan_type.value,
                "target":             payload.target,
                "data_source_status": source_status,
                "db_user_id":         db_user.user_id,
                "scrape_errors":      scrape_errors,
                "comment_method":     "instagrapi" if _ig_comments else "apify_fallback",
                "actors_used": [
                    "apify/instagram-scraper",
                    "apify/instagram-comment-scraper (fallback)",
                    "data-slayer/instagram-reposts",
                ],
            },
            "profile": {
                "username":      _sp.get("username",    payload.target),
                "full_name":     _sp.get("full_name",   ""),
                "bio":           _sp.get("bio",         ""),
                "followers":     _sp.get("followers",   0),
                "following":     _sp.get("following",   0),
                "verified":      _sp.get("verified",    False),
                "profile_pic":   _sp.get("profile_pic", ""),
                "user_id":       _sp.get("user_id",     ""),
                "profile_url":   _sp.get("profile_url",
                                          f"https://www.instagram.com/{payload.target}/"),
                "instagram_url": f"https://www.instagram.com/{payload.target}/",
                "website":       _sp.get("website",     ""),
                "category":      _sp.get("category",    ""),
                "is_private":    _sp.get("is_private",  False),
                "is_business":   _sp.get("is_business", False),
                "total_posts":   _sp.get("total_posts", _ig_n),
                "total_likes":   _sp.get("total_likes", 0) or _ig_tl,
                "platform":      "instagram",
                "last_updated":  datetime.now().strftime("%Y-%m-%d"),
                "data_limitations": [
                    "stories: tidak bisa diakses (hilang 24 jam)",
                    "dm: tidak bisa diakses",
                    "followers_list: protected",
                    "video_embed: tidak tersedia (hanya link ke IG)",
                    "comments_by_others: tidak diambil (hanya komentar target sendiri)",
                ],
            },
            "behavior_metrics": {
                # ── Counts ────────────────────────────────────────────────
                "total_posts":         _ig_n,
                "total_user_comments": len(_ig_comments),
                "total_reposts":       len(_ig_reposts),
                # ── Media breakdown ───────────────────────────────────────
                "media_type_breakdown": _med_breakdown,
                # ── Engagement stats ──────────────────────────────────────
                "total_likes":         _ig_tl,
                "total_comments":      _ig_tc,
                "total_views":         _ig_tv,
                "avg_likes_per_post":  _ig_avg_l,
                "avg_comments_per_post": _ig_avg_c,
                "engagement_rate":     _ig_eng,
                # ── Content patterns ─────────────────────────────────────
                "top_hashtags":  _top_ht_ig,
                "top_mentions":  _top_mn_ig,
                # ── Data ─────────────────────────────────────────────────
                "activities":    _ig_posts,       # semua posts (image/video/carousel)
                "user_comments": _ig_comments,    # komentar target di postnya sendiri
                "reposts":       _ig_reposts,     # konten yang di-repost target
            },
            "analytics_insight": {
                "sentiment_overall":   _ai.get("sentiment_overall",   "NEUTRAL"),
                "sentiment_score":     _ai.get("sentiment_score",     0.5),
                "sentiment_breakdown": _sent_bd,
                "risk_score":          _ai.get("risk_score",          0),
                "risk_level":          _ai.get("risk_level",          "RENDAH"),
                "personality":         _ai.get("personality",         {}),
                "summary_text":        _ai.get("summary_text",        ""),
                "ai_narrative":        _ai.get("ai_narrative",        ""),
                "ai_narrative_short":  _ai.get("ai_narrative_short",  ""),
                "dominant_topics":     _dom_topics[:5],
                "red_flags":           _ai.get("red_flags",           []),
                "green_flags":         _ai.get("green_flags",         []),
                "recommendation":      _ai.get("recommendation",      ""),
                "suitable_roles":      _ai.get("suitable_roles",      []),
                "comment_sentiment_overall":   _ci.get("comment_sentiment_overall",   "NEUTRAL"),
                "comment_sentiment_score":     _ci.get("comment_sentiment_score",     0.5),
                "comment_sentiment_breakdown": _ci.get("comment_sentiment_breakdown", {}),
                "comment_topics":              _ci.get("comment_topics",              []),
                "comment_style":               _ci.get("comment_style",               ""),
                "comment_red_flags":           _ci.get("comment_red_flags",           []),
                "comment_green_flags":         _ci.get("comment_green_flags",         []),
                "comment_summary":             _ci.get("comment_summary",             ""),
                "osint_findings":              osint_findings,
            },
        }

    # ── Response semua platform lain ─────────────────────────────────────
    # Build profile block sesuai platform
    if platform_val == "facebook":
        _profile_block = {
            "username":      _sp.get("username",    payload.target),
            "full_name":     _sp.get("full_name",   ""),
            "bio":           _sp.get("bio",         ""),
            "about_me":      _sp.get("about_me",    ""),
            "followers":     _sp.get("followers",   0),
            "following":     _sp.get("following",   0),
            "page_likes":    _sp.get("page_likes",  0),
            "verified":      _sp.get("verified",    False),
            "profile_pic":   _sp.get("profile_pic", ""),
            "cover_photo":   _sp.get("cover_photo", ""),
            "user_id":       _sp.get("user_id",     ""),
            "profile_url":   _sp.get("profile_url", f"https://www.facebook.com/{payload.target}"),
            "location":      _sp.get("location",   ""),
            "address":       _sp.get("address",    ""),
            "website":       _sp.get("website",    ""),
            "email":         _sp.get("email",      ""),
            "phone":         _sp.get("phone",      ""),
            "categories":    _sp.get("categories", []),
            "rating":        _sp.get("rating",     ""),
            "join_date":     _sp.get("join_date",  ""),
            "total_posts":   _sp.get("total_posts", len(enriched_activities)),
            "total_likes":   _sp.get("total_likes", 0),
            "platform":      "facebook",
            "last_updated":  _sp.get("last_updated", datetime.now().strftime("%Y-%m-%d")),
        }
    elif platform_val == "linkedin":
        _profile_block = {
            "username":          _sp.get("username",        payload.target),
            "full_name":         _sp.get("full_name",       ""),
            "headline":          _sp.get("headline",        ""),
            "bio":               _sp.get("bio",             ""),
            "about":             _sp.get("about",           ""),
            "followers":         _sp.get("followers",       0),
            "connections_count": _sp.get("connections_count", 0),
            "verified":          _sp.get("verified",        False),
            "profile_pic":       _sp.get("profile_pic",    ""),
            "background_image":  _sp.get("background_image",""),
            "linkedin_url":      _sp.get("linkedin_url",   f"https://www.linkedin.com/in/{payload.target}"),
            "location":          _sp.get("location",       ""),
            "industry":          _sp.get("industry",       ""),
            "website":           _sp.get("website",        ""),
            "current_company":   _sp.get("current_company",""),
            "current_title":     _sp.get("current_title",  ""),
            "is_creator":        _sp.get("is_creator",     False),
            "is_premium":        _sp.get("is_premium",     False),
            "is_open_to_work":   _sp.get("is_open_to_work",False),
            "is_hiring":         _sp.get("is_hiring",      False),
            "join_date":         _sp.get("join_date",      ""),
            "experience":        _sp.get("experience",     []),
            "education":         _sp.get("education",      []),
            "skills":            _sp.get("skills",         []),
            "certifications":    _sp.get("certifications", []),
            "languages":         _sp.get("languages",      []),
            "interests":         _sp.get("interests",      []),
            "contact_email":     _sp.get("contact_email",  ""),
            "contact_phone":     _sp.get("contact_phone",  ""),
            "total_posts":       _sp.get("total_posts",    len(enriched_activities)),
            "total_likes":       _sp.get("total_likes",    0),
            "data_limitations":  _sp.get("data_limitations", []),
            "platform":          "linkedin",
            "last_updated":      _sp.get("last_updated", datetime.now().strftime("%Y-%m-%d")),
        }
    else:
        # Generic fallback
        _profile_block = {
            "username":    _sp.get("username",   payload.target),
            "full_name":   _sp.get("full_name",  ""),
            "bio":         _sp.get("bio",        ""),
            "followers":   _sp.get("followers",  0),
            "following":   _sp.get("following",  0),
            "verified":    _sp.get("verified",   False),
            "profile_pic": _sp.get("profile_pic",""),
            "total_posts": _sp.get("total_posts", len(enriched_activities)),
            "total_likes": _sp.get("total_likes", 0),
            "platform":    platform_val,
            "last_updated":_sp.get("last_updated", datetime.now().strftime("%Y-%m-%d")),
        }

    return {
        "status":    "SUCCESS",
        "timestamp": datetime.now().isoformat(),
        "scan_meta": {
            "platform":          payload.platform.value.upper(),
            "scan_type":         payload.scan_type.value,
            "target":            payload.target,
            "data_source_status": source_status,
            "db_user_id":        db_user.user_id,
            "scrape_errors":     scrape_errors,
        },
        "profile": _profile_block,
        "behavior_metrics": {
            "total_extracted":   len(enriched_activities),
            "activities":        enriched_activities,
            "user_comments":     user_comments,
            "reposts":           reposts,
            "photos":            platform_photos,
        },
        "analytics_insight": {
            "sentiment_overall":   _ai.get("sentiment_overall",   "NEUTRAL"),
            "sentiment_score":     _ai.get("sentiment_score",     0.5),
            "sentiment_breakdown": _sent_bd,
            "risk_score":          _ai.get("risk_score",          0),
            "risk_level":          _ai.get("risk_level",          "RENDAH"),
            "personality":         _ai.get("personality",         {}),
            "summary_text":        _ai.get("summary_text",        ""),
                "ai_narrative":        _ai.get("ai_narrative",        ""),
                "ai_narrative_short":  _ai.get("ai_narrative_short",  ""),
            "red_flags":           _ai.get("red_flags",           []),
            "green_flags":         _ai.get("green_flags",         []),
            "recommendation":      _ai.get("recommendation",      ""),
            "suitable_roles":      _ai.get("suitable_roles",      []),
            "comment_sentiment_overall":   _ci.get("comment_sentiment_overall",   "NEUTRAL"),
            "comment_sentiment_score":     _ci.get("comment_sentiment_score",     0.5),
            "comment_sentiment_breakdown": _ci.get("comment_sentiment_breakdown", {}),
            "comment_topics":              _ci.get("comment_topics",              []),
            "comment_style":               _ci.get("comment_style",               ""),
            "comment_red_flags":           _ci.get("comment_red_flags",           []),
            "comment_green_flags":         _ci.get("comment_green_flags",         []),
            "comment_summary":             _ci.get("comment_summary",             ""),
            "osint_findings":              osint_findings,
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
# SCAN HISTORY
# ─────────────────────────────────────────────────────────────────────────────
@app.get("/api/v1/scan/history/{tenant_id}")
def get_scan_history(
    tenant_id: int,
    db: Session = Depends(get_db),
    api_key: str = Depends(verify_api_key)
):
    histories = (
        db.query(models.AISummary)
        .filter(models.AISummary.tenant_id == tenant_id)
        .order_by(models.AISummary.generated_at.desc())
        .all()
    )
    if not histories:
        raise HTTPException(status_code=404, detail="Belum ada history scan.")
    return {
        "status":        "SUCCESS",
        "tenant_id":     tenant_id,
        "total_records": len(histories),
        "data": [
            {
                "summary_id": h.summary_id,
                "user_id":    h.user_id,
                "summary_text": h.summary_text,
                "created_at": h.generated_at.strftime("%Y-%m-%d %H:%M:%S") if h.generated_at else ""
            }
            for h in histories
        ]
    }


@app.get("/api/v1/scan/user/{platform}/{username}")
def get_user_scan_result(
    platform: str,
    username: str,
    db: Session = Depends(get_db),
    api_key: str = Depends(verify_api_key)
):
    """Ambil hasil scan terakhir untuk user tertentu."""
    db_user = db.query(models.SocialUser).filter(
        models.SocialUser.username == username,
        models.SocialUser.platform == platform.lower()
    ).first()
    if not db_user:
        raise HTTPException(status_code=404, detail=f"User @{username} di {platform} belum pernah di-scan.")

    latest_summary = (
        db.query(models.AISummary)
        .filter(models.AISummary.user_id == db_user.user_id)
        .order_by(models.AISummary.generated_at.desc())
        .first()
    )
    activities = (
        db.query(models.Activity)
        .filter(models.Activity.user_id == db_user.user_id)
        .order_by(models.Activity.activity_id.desc())
        .limit(20)
        .all()
    )

    return {
        "status": "SUCCESS",
        "profile": {
            "username":    db_user.username,
            "full_name":   db_user.full_name,
            "bio":         db_user.bio,
            "followers":   db_user.followers,
            "following":   db_user.following,
            "verified":    db_user.verified,
            "profile_pic": db_user.profile_pic,
            "platform":    db_user.platform,
            "last_scanned": db_user.last_scanned.strftime("%Y-%m-%d %H:%M:%S") if db_user.last_scanned else ""
        },
        "summary_text": latest_summary.summary_text if latest_summary else "",
        "total_activities": len(activities),
        "activities": [
            {
                "activity_id":   a.activity_id,
                "action_type":   a.action_type,
                "content_text":  a.content_text,
                "post_url":      a.post_url,
                "ai_sentiment":  a.ai_sentiment,
                "ai_risk_score": a.ai_risk_score,
                "created_at":    a.created_at.strftime("%Y-%m-%d %H:%M:%S") if a.created_at else ""
            }
            for a in activities
        ]
    }


# ─────────────────────────────────────────────────────────────────────────────
# AI IMAGE ANALYSIS
# ─────────────────────────────────────────────────────────────────────────────
@app.post("/api/v1/analyze-image", status_code=200)
async def analyze_image_endpoint(
    image: UploadFile = File(...),
    caption: str = "",
    db: Session = Depends(get_db),
    api_key: str = Depends(verify_api_key)
):
    if not is_image_file(image.filename):
        raise HTTPException(status_code=400, detail="File harus berupa gambar (jpg, png, gif, webp).")

    upload_dir = "uploads"
    os.makedirs(upload_dir, exist_ok=True)
    file_path = os.path.join(upload_dir, image.filename)

    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(image.file, buffer)

    ai_result = analyze_image_real(file_path, caption)

    return {
        "status":      "SUCCESS",
        "filename":    image.filename,
        "ai_analysis": ai_result
    }


# ─────────────────────────────────────────────────────────────────────────────
# VIDEO TIKTOK — PLAY IN SWAGGER
# ─────────────────────────────────────────────────────────────────────────────
import httpx as _httpx


@app.get(
    "/api/v1/video/tiktok/player",
    summary="🎬 Video Player Page (buka di browser baru)",
    tags=["Video Player"],
    response_class=HTMLResponse,
    include_in_schema=False,   # tersembunyi dari Swagger, akses langsung via URL
)
async def tiktok_player_page(video_url: str):
    """
    Halaman video player yang bisa dibuka langsung di browser.
    Tidak butuh API key — akses langsung via URL.
    """
    _vid_id = ""
    _m = re.search(r"/video/(\d+)", video_url)
    if _m:
        _vid_id = _m.group(1)
    _user = ""
    _mu = re.search(r"@([^/]+)/", video_url)
    if _mu:
        _user = _mu.group(1)

    return HTMLResponse(_build_tiktok_embed(video_url))


@app.get(
    "/api/v1/video/tiktok/play",
    summary="▶️  Putar video TikTok langsung di Swagger",
    tags=["Video Player"],
    response_class=HTMLResponse,
)
async def play_tiktok_video(
    video_url: str,
    api_key: str = Depends(verify_api_key),
):
    """
    ## Cara Pakai

    1. Scan TikTok → copy field **`video_url`** dari activities
    2. Paste ke parameter `video_url` di bawah → klik **Execute**
    3. Di response muncul HTML dengan tombol **"Buka Video Player"**
    4. **Klik link tersebut** → tab baru terbuka dengan video TikTok!

    > ⚠️ Swagger tidak bisa render video langsung — klik link di response untuk membuka player di tab baru.
    """
    import os as _os2
    from dotenv import load_dotenv as _ld
    _ld()
    _token = _os2.getenv("APIFY_TOKEN", "").strip()

    # Extract video info
    _vid_id = ""
    _m = re.search(r"/video/(\d+)", video_url)
    if _m:
        _vid_id = _m.group(1)
    _user = ""
    _mu = re.search(r"@([^/]+)/", video_url)
    if _mu:
        _user = _mu.group(1)

    # URL untuk player page (buka di tab baru)
    _player_url = f"/api/v1/video/tiktok/player?video_url={_q(video_url, safe='')}"

    # ── Case 1: sudah Apify KV URL atau direct mp4 ────────────────────────────
    _is_playable = (
        "api.apify.com/v2/key-value-stores" in video_url or
        video_url.lower().endswith(".mp4") or
        "mime_type=video_mp4" in video_url.lower()
    )

    if _is_playable:
        return HTMLResponse(_build_launch_page(
            player_url=_player_url,
            video_url=video_url,
            vid_id=_vid_id,
            user=_user,
            status="direct",
        ))

    # ── Case 2: TikTok page URL → download via Apify actor ────────────────────
    if not _token:
        return HTMLResponse(_build_launch_page(
            player_url=_player_url,
            video_url=video_url,
            vid_id=_vid_id,
            user=_user,
            status="no_token",
        ))

    try:
        from apify_client import ApifyClient as _AC
        _client = _AC(_token)

        print(f"   ↳ [VideoPlayer] Download via logical_scrapers/tiktok-video-downloader...")
        _run = _client.actor("logical_scrapers/tiktok-video-downloader").call(run_input={
            "startUrls":          [video_url],
            "saveToKvStore":      True,
            "proxyConfiguration": {"useApifyProxy": True},
        })

        _ds_id = getattr(_run, "default_dataset_id", None)
        _kv_id = getattr(_run, "default_key_value_store_id", None)
        _mp4_url   = ""
        _thumb_url = ""
        _title     = video_url

        if _ds_id:
            _items = _client.dataset(_ds_id).list_items().items or []
            if _items:
                _it        = _items[0]
                _title     = _it.get("description") or _title
                _thumb_url = (_it.get("video") or {}).get("cover") or ""

        if _kv_id:
            _kvs = _client.key_value_store(_kv_id)
            try:
                _keys = list(_kvs.list_keys().items or [])
                for _k in _keys:
                    _kname = _k.get("key", "")
                    if _kname.lower().endswith(".mp4") or "video" in _kname.lower():
                        _mp4_url = (
                            f"https://api.apify.com/v2/key-value-stores/"
                            f"{_kv_id}/records/{_kname}?token={_token}"
                        )
                        break
            except Exception:
                pass

        if _mp4_url:
            print(f"   ✅ [VideoPlayer] MP4 ready: {_mp4_url[:70]}")
            # Update player URL dengan MP4 langsung
            _player_url = f"/api/v1/video/tiktok/player?video_url={_q(_mp4_url, safe='')}"
            return HTMLResponse(_build_launch_page(
                player_url=_player_url,
                video_url=_mp4_url,
                vid_id=_vid_id,
                user=_user,
                status="downloaded",
                title=_title,
                thumb=_thumb_url,
            ))
        else:
            return HTMLResponse(_build_launch_page(
                player_url=_player_url,
                video_url=video_url,
                vid_id=_vid_id,
                user=_user,
                status="embed",
            ))

    except Exception as _e:
        import traceback as _tb
        print(f"   ❌ [VideoPlayer] Error: {_e}")
        return HTMLResponse(_build_launch_page(
            player_url=_player_url,
            video_url=video_url,
            vid_id=_vid_id,
            user=_user,
            status="embed",
        ))


def _build_launch_page(player_url: str, video_url: str,
                        vid_id: str = "", user: str = "",
                        status: str = "embed", title: str = "",
                        thumb: str = "") -> str:
    """
    Halaman launcher yang muncul di Swagger response.
    Berisi tombol besar untuk buka video player di tab baru.
    Swagger tidak bisa render video langsung — user klik tombol → tab baru → video jalan.
    """
    _status_map = {
        "direct":     ("✅", "#4caf50", "Direct MP4 siap diputar!"),
        "downloaded": ("✅", "#4caf50", "Video berhasil diproses — siap diputar!"),
        "embed":      ("▶️", "#fe2c55", "Klik tombol untuk putar via TikTok embed"),
        "no_token":   ("⚠️", "#ff9800", "APIFY_TOKEN kosong — putar via TikTok embed"),
    }
    _ico, _color, _msg = _status_map.get(status, ("▶️", "#fe2c55", "Klik untuk putar"))
    _title_html = f"<p style='color:#aaa;font-size:13px;margin:6px 0 0;max-width:360px'>{title[:180]}</p>" if title else ""
    _thumb_html = f"<img src='{thumb}' style='width:120px;border-radius:8px;margin-bottom:12px' /><br/>" if thumb else ""
    _uid_html   = f"@{user}" if user else vid_id

    return f"""<!DOCTYPE html>
<html lang="id">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Social Radar — TikTok Player</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ background: #0f0f0f; display: flex; align-items: center;
            justify-content: center; min-height: 100vh;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; }}
    .card {{ background: #1c1c1e; border-radius: 20px; padding: 32px 28px;
             text-align: center; max-width: 420px; width: 100%;
             box-shadow: 0 12px 48px rgba(0,0,0,.7); }}
    .badge {{ background: {_color}; color: #fff; padding: 5px 14px;
              border-radius: 20px; font-size: 12px; font-weight: 700;
              display: inline-block; margin-bottom: 16px; }}
    .title {{ color: #fff; font-size: 20px; font-weight: 700; margin-bottom: 6px; }}
    .sub   {{ color: #888; font-size: 13px; margin-bottom: 20px; }}
    .msg   {{ color: {_color}; font-size: 13px; margin-bottom: 20px;
              padding: 10px; background: rgba(255,255,255,.05);
              border-radius: 10px; border-left: 3px solid {_color}; }}
    .btn-primary {{
      display: block; background: {_color}; color: #fff;
      padding: 16px 24px; border-radius: 14px; font-size: 16px;
      font-weight: 700; text-decoration: none; margin-bottom: 12px;
      transition: transform .15s, opacity .15s;
    }}
    .btn-primary:hover {{ transform: scale(1.02); opacity: .92; }}
    .btn-secondary {{
      display: block; background: transparent; color: #888;
      border: 1px solid #333; padding: 10px 24px;
      border-radius: 10px; font-size: 13px; text-decoration: none;
      transition: border-color .15s;
    }}
    .btn-secondary:hover {{ border-color: #fe2c55; color: #fe2c55; }}
    .hint {{ color: #555; font-size: 11px; margin-top: 16px;
             line-height: 1.6; }}
    code {{ background: #2a2a2a; padding: 2px 6px; border-radius: 4px;
            font-size: 10px; color: #fe2c55; word-break: break-all; }}
  </style>
</head>
<body>
  <div class="card">
    <span class="badge">{_ico} TikTok Video Player</span>
    <p class="title">{_uid_html}</p>
    <p class="sub">Video ID: {vid_id or 'N/A'}</p>
    {_thumb_html}
    {_title_html}
    <p class="msg">{_msg}</p>

    <!-- Tombol utama — buka player di tab baru -->
    <a class="btn-primary"
       href="{player_url}"
       target="_blank"
       rel="noopener">
      ▶&nbsp; Putar Video Sekarang
    </a>

    <!-- Buka langsung di TikTok -->
    <a class="btn-secondary"
       href="{video_url}"
       target="_blank"
       rel="noopener">
      🔗 Buka di TikTok
    </a>

    <p class="hint">
      ℹ️ Swagger tidak bisa render video inline.<br>
      Klik <strong style="color:#fe2c55">▶ Putar Video Sekarang</strong> untuk membuka player di tab baru.<br><br>
      URL yang diputar:<br>
      <code>{video_url[:80]}{'...' if len(video_url)>80 else ''}</code>
    </p>
  </div>
</body>
</html>"""


def _build_video_player(mp4_url: str, original_url: str,
                         title: str = "", thumb: str = "") -> str:
    """Build HTML5 video player page."""
    _title_html = f"<p style='color:#ccc;margin:8px 0;font-size:13px;max-width:700px;word-break:break-all'>{title[:200]}</p>" if title else ""
    _thumb_html  = f"<img src='{thumb}' style='max-width:200px;border-radius:8px;margin-bottom:8px' /><br/>" if thumb else ""
    return f"""<!DOCTYPE html>
<html lang="id">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>TikTok Video Player — Social Radar</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ background: #0f0f0f; display: flex; flex-direction: column;
            align-items: center; justify-content: center;
            min-height: 100vh; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; }}
    .container {{ text-align: center; padding: 24px; max-width: 500px; width: 100%; }}
    h2 {{ color: #fff; font-size: 18px; margin-bottom: 12px; }}
    video {{ width: 100%; max-width: 400px; max-height: 70vh;
             border-radius: 12px; background: #000;
             box-shadow: 0 8px 32px rgba(0,0,0,0.6); }}
    .badge {{ background: #fe2c55; color: white; padding: 4px 10px;
              border-radius: 20px; font-size: 12px; font-weight: 700;
              display: inline-block; margin-bottom: 12px; }}
    .url {{ color: #888; font-size: 11px; margin-top: 12px;
            word-break: break-all; max-width: 400px; }}
    a {{ color: #fe2c55; text-decoration: none; }}
    .err {{ color: #ff6b6b; font-size: 13px; margin-top: 12px; display: none; }}
  </style>
</head>
<body>
  <div class="container">
    <span class="badge">▶ TikTok Video</span>
    <h2>Social Radar — Video Player</h2>
    {_thumb_html}
    {_title_html}
    <video controls autoplay playsinline preload="auto"
           onerror="document.getElementById('err').style.display='block'">
      <source src="{mp4_url}" type="video/mp4">
      Browser tidak mendukung HTML5 video.
    </video>
    <p id="err" class="err">
      ⚠️ Video tidak bisa dimuat langsung.<br>
      <a href="{original_url}" target="_blank">Buka di TikTok →</a>
    </p>
    <p class="url">
      <a href="{original_url}" target="_blank">🔗 Original URL</a>
    </p>
  </div>
</body>
</html>"""


def _build_tiktok_embed(page_url: str) -> str:
    """Fallback: TikTok oEmbed iframe player."""
    # Extract video ID dari URL
    _vid_id = ""
    _m = re.search(r"/video/(\d+)", page_url)
    if _m:
        _vid_id = _m.group(1)

    # Extract username
    _user = ""
    _mu = re.search(r"@([^/]+)/", page_url)
    if _mu:
        _user = _mu.group(1)

    _enc = _q(page_url, safe="")

    # Buka langsung di browser baru via link — lebih reliable dari embed
    _player_url = f"http://localhost:8000/api/v1/video/tiktok/player?video_url={_enc}"

    return f"""<!DOCTYPE html>
<html lang="id">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>TikTok Video — Social Radar</title>
  <style>
    body {{ background:#0f0f0f; display:flex; align-items:center;
            justify-content:center; min-height:100vh;
            font-family:-apple-system,sans-serif; padding:20px; }}
    .wrap {{ text-align:center; max-width:400px; }}
    .badge {{ background:#fe2c55; color:#fff; padding:4px 12px;
              border-radius:20px; font-size:12px; font-weight:700; }}
    .card {{ background:#1a1a1a; border-radius:16px; padding:24px;
             margin-top:16px; box-shadow:0 8px 32px rgba(0,0,0,.6); }}
    .btn {{ display:inline-block; background:#fe2c55; color:#fff;
            padding:12px 28px; border-radius:30px; font-size:15px;
            font-weight:700; text-decoration:none; margin:8px;
            transition:opacity .2s; }}
    .btn:hover {{ opacity:.85; }}
    .btn.outline {{ background:transparent; border:2px solid #fe2c55;
                   color:#fe2c55; }}
    .vid-id {{ color:#555; font-size:11px; margin-top:8px;
               word-break:break-all; }}
    iframe {{ border:none; border-radius:12px; margin-top:16px;
              box-shadow:0 4px 16px rgba(0,0,0,.4); }}
  </style>
</head>
<body>
  <div class="wrap">
    <span class="badge">▶ TikTok Video Player</span>
    <div class="card">
      <p style="color:#fff;font-weight:700;margin-bottom:4px">@{_user}</p>
      <p class="vid-id">Video ID: {_vid_id}</p>

      <!-- TikTok Official Embed -->
      <blockquote class="tiktok-embed"
        cite="{page_url}"
        data-video-id="{_vid_id}"
        style="max-width:325px;min-width:325px;">
        <section>
          <a target="_blank" href="https://www.tiktok.com/@{_user}">@{_user}</a>
        </section>
      </blockquote>
      <script async src="https://www.tiktok.com/embed.js"></script>

      <div style="margin-top:16px">
        <a class="btn" href="{page_url}" target="_blank">🔗 Buka di TikTok</a>
      </div>
      <p style="color:#555;font-size:11px;margin-top:12px">
        Jika embed tidak muncul, klik tombol di atas untuk buka di TikTok
      </p>
    </div>
  </div>
</body>
</html>"""


def _build_error_page(title: str, detail: str) -> str:
    return f"""<!DOCTYPE html><html><head><meta charset="UTF-8">
<style>body{{background:#0f0f0f;color:#fff;font-family:sans-serif;
display:flex;align-items:center;justify-content:center;min-height:100vh;}}
.box{{background:#1a1a1a;padding:32px;border-radius:12px;max-width:500px;text-align:center;}}
h3{{color:#fe2c55;}}p{{color:#ccc;margin-top:8px;font-size:14px;}}</style></head>
<body><div class="box"><h3>⚠️ {title}</h3><p>{detail}</p></div></body></html>"""



# ─────────────────────────────────────────────────────────────────────────────
# SOCIAL RADAR DASHBOARD — scan + video player dalam satu halaman
# ─────────────────────────────────────────────────────────────────────────────
from fastapi.responses import FileResponse as _FR
import os as _osd


@app.get("/dashboard", include_in_schema=False)
async def serve_dashboard():
    """Serve the Social Radar dashboard dengan video player terintegrasi."""
    _path = os.path.join(os.path.dirname(__file__), "dashboard.html")
    if os.path.exists(_path):
        return _FR(_path, media_type="text/html")
    raise HTTPException(status_code=404, detail="dashboard.html tidak ditemukan")


@app.get("/api/v1/debug/ig-carousel", include_in_schema=False)
async def debug_ig_carousel(
    url: str,
    key: str = "",
    api_key: str = Depends(api_key_scheme)
):
    """Debug: test carousel fetch untuk satu post URL."""
    effective_key = api_key or key
    if effective_key != MASTER_API_KEY:
        raise HTTPException(status_code=401, detail="API Key tidak valid!")
    import os as _os_dbg
    from fetch_instagram import _fetch_carousel_photos
    sess = _os_dbg.getenv("INSTAGRAM_SESSIONID", "")
    photos = _fetch_carousel_photos(url, sess)
    return {"url": url, "photos_count": len(photos), "photos": photos[:5]}


@app.get("/social-radar", include_in_schema=False)
async def serve_social_radar():
    """Social Radar full dashboard — scan + video player dalam satu tab."""
    _path = os.path.join(os.path.dirname(__file__), "social_radar_dashboard.html")
    if os.path.exists(_path):
        from fastapi.responses import FileResponse as _FR2
        return _FR2(_path, media_type="text/html")
    raise HTTPException(status_code=404, detail="social_radar_dashboard.html tidak ditemukan")


# ─────────────────────────────────────────────────────────────────────────────
# EMAIL FOOTPRINT — Breach Checker & Account Footprint
# ─────────────────────────────────────────────────────────────────────────────
@app.get("/email-checker", include_in_schema=False)
async def serve_email_checker():
    """OSINT Intelligence Center — Email & Phone checker."""
    _path = os.path.join(os.path.dirname(__file__), "email_checker.html")
    if os.path.exists(_path):
        from fastapi.responses import FileResponse as _FR3
        return _FR3(_path, media_type="text/html")
    raise HTTPException(status_code=404, detail="email_checker.html tidak ditemukan")


class _EmailScanRequest(schemas.BaseModel if hasattr(schemas, "BaseModel") else object):
    email: str


from pydantic import BaseModel as _PydanticBase

class EmailScanPayload(_PydanticBase):
    email: str

class OsintCheckPayload(_PydanticBase):
    target: str  # email ATAU nomor telepon


@app.post(
    "/api/v1/email/scan",
    tags=["Email OSINT"],
    summary="📧 Scan jejak digital & breach status email target",
    status_code=200,
)
async def email_scan(
    payload: EmailScanPayload,
    api_key: str = Depends(verify_api_key),
):
    """Scan email: holehe (120+ platform) + HIBP + Hudson Rock stealer logs."""
    try:
        from email_footprint import scan_email as _scan_email
        result = await _scan_email(payload.email)
        return result
    except Exception as e:
        import traceback as _tb
        return {"status": "error", "email": payload.email, "error": str(e),
                "traceback": _tb.format_exc().splitlines()[-5:]}


@app.post(
    "/api/v1/osint/check",
    tags=["OSINT Intelligence"],
    summary="🔍 OSINT Check — Email atau Nomor HP",
    status_code=200,
)
async def osint_check(
    payload: OsintCheckPayload,
    api_key: str = Depends(verify_api_key),
):
    """
    Unified OSINT checker — deteksi otomatis apakah input adalah email atau nomor HP.

    **Email** → holehe (120+ platform) + HIBP breach + Hudson Rock stealer logs

    **Nomor HP** → info carrier + Hudson Rock by phone + spam reputation + social links

    **Contoh:**
    ```json
    {"target": "target@gmail.com"}
    {"target": "08123456789"}
    {"target": "+6281234567890"}
    ```
    """
    target = payload.target.strip()
    _email_re = re.compile(r'^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$')
    _phone_re = re.compile(r'^(\+?62|0)[0-9]{8,12}$|^\+[1-9][0-9]{6,14}$')

    try:
        if _email_re.match(target):
            # Input adalah email
            from email_footprint import scan_email as _scan_email
            result = await _scan_email(target)
            result['input_type'] = 'email'
            return result
        elif _phone_re.match(re.sub(r'[\s\-\(\)\.]', '', target)):
            # Input adalah nomor HP
            from phone_osint import scan_phone as _scan_phone
            result = await _scan_phone(target)
            return result
        else:
            return {
                'status': 'error',
                'target': target,
                'error': 'Input tidak dikenali. Gunakan format email (x@x.com) atau nomor HP (08xx, +628xx)',
            }
    except Exception as e:
        import traceback as _tb
        return {'status': 'error', 'target': target, 'error': str(e),
                'traceback': _tb.format_exc().splitlines()[-5:]}


# ─────────────────────────────────────────────────────────────────────────────
# IMAGE PROXY — untuk bypass CORS/CDN restriction foto Instagram
# GET /api/v1/proxy/image?url=https://...
# Browser tidak bisa load CDN Instagram langsung karena CORS.
# Endpoint ini fetch gambar di sisi server lalu kirim ke browser.
# ─────────────────────────────────────────────────────────────────────────────
from fastapi.responses import Response as _Response
from urllib.parse import quote as _q2

@app.get(
    "/api/v1/proxy/image",
    include_in_schema=False,
)
async def proxy_image(url: str, request: Request):
    """
    Proxy media (gambar & video) dari CDN Instagram/TikTok.
    Support Range requests untuk video streaming.
    """
    if not url:
        return _Response(status_code=400, content="URL required")

    _allowed = [
        "instagram.com", "cdninstagram.com", "fbcdn.net",
        "tiktok.com", "tiktokcdn.com", "tiktokcdn-us.com", "muscdn.com",
        "p16-sign", "p19-sign", "p9-sign", "v19-", "v26-", "v16-",
        "apify.com", "scontent",
    ]
    from urllib.parse import urlparse as _up
    try:
        _parsed_url = _up(url)
        _host = _parsed_url.netloc.lower()
        _full = url.lower()
        if not any(d in _host or d in _full for d in _allowed):
            return _Response(status_code=403, content="Domain not allowed")
    except Exception:
        return _Response(status_code=400, content="Invalid URL")

    try:
        import httpx as _hx
        import os as _os_px
        from dotenv import load_dotenv as _ld_px
        _ld_px()
        _ig_sess = _os_px.getenv("INSTAGRAM_SESSIONID", "").strip()

        _is_ig = any(d in url for d in ["instagram.com", "cdninstagram.com", "fbcdn.net"])
        _is_tt = any(d in url for d in ["tiktok.com", "tiktokcdn.com", "tiktokcdn-us.com",
                                          "muscdn.com", "p16-sign", "p19-sign", "p9-sign",
                                          "v19-", "v26-", "v16-"])
        _is_tw = any(d in url for d in ["twimg.com", "pbs.twimg.com", "video.twimg.com",
                                          "abs.twimg.com", "ton.twimg.com"])
        _headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            "Accept": "*/*",
            "Accept-Encoding": "identity",
            "Accept-Language": "en-US,en;q=0.9",
        }
        if _is_ig:
            _headers["Referer"] = "https://www.instagram.com/"
            if _ig_sess:
                _headers["Cookie"] = f"sessionid={_ig_sess}"
        elif _is_tt:
            # TikTok CDN requires these headers to serve media
            _headers["Referer"]        = "https://www.tiktok.com/"
            _headers["Origin"]         = "https://www.tiktok.com"
            _headers["Sec-Fetch-Site"] = "cross-site"
            _headers["Sec-Fetch-Mode"] = "cors"
            _headers["Sec-Fetch-Dest"] = "image"
        elif _is_tw:
            # Twitter/X CDN requires Referer to serve media (video.twimg.com returns 403 without it)
            _headers["Referer"]        = "https://x.com/"
            _headers["Origin"]         = "https://x.com"
            _headers["Sec-Fetch-Site"] = "cross-site"
            _headers["Sec-Fetch-Mode"] = "cors"
            _headers["Sec-Fetch-Dest"] = "empty"

        # Forward Range header untuk video streaming
        _range = request.headers.get("range")
        if _range:
            _headers["Range"] = _range

        async with _hx.AsyncClient(timeout=30, follow_redirects=True) as _client:
            _resp = await _client.get(url, headers=_headers)

        content_type = _resp.headers.get("content-type", "application/octet-stream")
        resp_headers = {
            "Access-Control-Allow-Origin": "*",
            "Accept-Ranges": "bytes",
        }
        # Pass through content-range for video streaming
        if "content-range" in _resp.headers:
            resp_headers["Content-Range"] = _resp.headers["content-range"]
        if "content-length" in _resp.headers:
            resp_headers["Content-Length"] = _resp.headers["content-length"]

        # Cache hanya untuk non-video
        if "video" not in content_type:
            resp_headers["Cache-Control"] = "public, max-age=3600"

        status = _resp.status_code if _resp.status_code in (200, 206) else 200

        return _Response(
            content=_resp.content,
            status_code=status,
            media_type=content_type,
            headers=resp_headers,
        )
    except Exception as _pe:
        # Fallback: redirect ke URL asli
        from fastapi.responses import RedirectResponse as _RR
        return _RR(url=url, status_code=302)


# ─────────────────────────────────────────────────────────────────────────────
# ENTRYPOINT
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    debug = os.getenv("DEBUG", "False").lower() == "true"
    uvicorn.run("main:app", host=host, port=port, reload=debug)