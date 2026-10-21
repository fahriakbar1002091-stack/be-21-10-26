"""
scraper_engine.py - Social Radar Scraper Engine v12.0
- run_crawler sekarang ASYNC — langsung await fetch tanpa asyncio.run()
- Tidak ada lagi nested event loop issue dengan FastAPIyt-dlp

"""

import os
import re
import time
import logging
from typing import Dict, Any, List, Tuple
from dotenv import load_dotenv

load_dotenv()
APIFY_TOKEN = os.getenv("APIFY_TOKEN", "")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# HELPER
# ─────────────────────────────────────────────────────────────────────────────
def _empty_profile(username: str, platform: str) -> Dict[str, Any]:
    return {
        "username": username,
        "full_name": "",
        "bio": "",
        "followers": 0,
        "following": 0,
        "verified": False,
        "profile_pic": "",
        "total_posts": 0,
        "total_likes": 0,
        "platform": platform,
        "last_updated": time.strftime("%Y-%m-%d")
    }


def _normalise_post(raw: Dict, platform: str, username: str) -> Dict[str, Any]:
    text = raw.get("content") or raw.get("text") or ""

    media_type = raw.get("media_type") or ""
    if media_type in ("video", "reel"):
        content_type = "video"
    elif media_type in ("image", "photo"):
        content_type = "image"
    elif media_type == "carousel":
        content_type = "carousel"
    else:
        content_type = "video" if platform == "tiktok" else "image"

    if text:
        clean_text = re.sub(r"[#@]\w+", "", text).strip()
        if clean_text:
            content_description = clean_text[:300]
        else:
            hashtags_str = " ".join(f"#{h}" for h in (raw.get("hashtags") or [])[:5])
            content_description = f"Konten {content_type} {hashtags_str}".strip()
    else:
        content_description = f"Konten {content_type} tanpa caption"

    likes    = int(raw.get("likes")    or 0)
    comments = int(raw.get("comments") or 0)
    # Instagram expose "shares" (reshareCount) dan "plays" (videoViewCount)
    shares   = int(raw.get("shares")   or raw.get("reposts") or raw.get("shareCount") or 0)
    plays    = int(raw.get("plays")    or raw.get("videoViewCount") or raw.get("viewsCount") or 0)

    post_url = raw.get("post_url") or raw.get("url") or ""
    if not post_url:
        pid = raw.get("id") or ""
        if platform == "tiktok" and pid:
            post_url = f"https://www.tiktok.com/@{username}/video/{pid}"
        elif platform == "instagram" and pid:
            post_url = f"https://www.instagram.com/p/{pid}/"

    created_at = raw.get("created_at") or raw.get("timestamp") or time.strftime("%Y-%m-%d")

    # OCR yang sudah tersedia dari scraper (khusus Facebook — actor sudah sertakan ocrText)
    ocr_from_scraper = raw.get("ocr_from_media") or ""

    # combined_text default = caption; akan diperbarui main.py setelah media extraction
    # Untuk Facebook, langsung gabungkan OCR dari actor karena sudah tersedia
    combined_default = " | ".join(filter(None, [text[:700], ocr_from_scraper])) if ocr_from_scraper else text[:700]

    return {
        "action_type":         "POST",
        "id":                  raw.get("id") or raw.get("post_id") or "",
        "post_id":             raw.get("post_id") or raw.get("id") or "",
        "text":                text[:700],
        "post_url":            post_url,
        "content_type":        content_type,
        "content_description": content_description,
        "image_url":           raw.get("image_url") or raw.get("cover_url") or (raw.get("_raw_media_urls") or [None])[0] or "",
        "video_url":           raw.get("video_url") or "",
        "cover_url":           raw.get("cover_url") or raw.get("image_url") or (raw.get("_raw_media_urls") or [None])[0] or "",
        "images_list":         raw.get("images_list") or raw.get("image_urls") or [],  # semua foto carousel IG/TikTok
        # ── TikTok: field baru dari fetch_tiktok v3 ───────────────────────
        "visual_description": raw.get("visual_description") or "",
        "topic":              raw.get("topic")    or "",
        "mood":               raw.get("mood")     or "",
        "objects":            raw.get("objects")  or "",
        "activity":           raw.get("activity") or "",
        "is_pinned":          bool(raw.get("is_pinned")  or False),
        "is_repost":          bool(raw.get("is_repost")  or False),
        "is_reply":           bool(raw.get("is_reply")   or False),
        "is_quote":           bool(raw.get("is_quote")   or False),
        # ── Engagement ────────────────────────────────────────────────────
        "metrics": {
            "likes":     likes,
            "comments":  comments,
            "shares":    shares,
            "plays":     plays,
            "quotes":    int(raw.get("quotes")    or 0),
            "bookmarks": int(raw.get("bookmarks") or 0),
            "saves":     int(raw.get("saves")     or 0),
        },
        "sentiment":    raw.get("sentiment") or {"label": "NEUTRAL", "score": 0.5},
        "hashtags":     raw.get("hashtags")     or [],
        "mentions":     raw.get("mentions")     or [],
        "urls":         raw.get("urls")         or [],
        "music":        raw.get("music")        or {},
        "location":     raw.get("location")     or "",
        "duration_sec": raw.get("duration_sec") or 0,
        "comments_data": raw.get("comments_data") or [],
        "is_ad":        bool(raw.get("is_ad") or raw.get("is_sponsored") or False),
        "created_at":   str(created_at),
        # ── X/Twitter ─────────────────────────────────────────────────────
        "lang":             raw.get("lang")             or "",
        "source":           raw.get("source")           or "",
        "conversation_id":  raw.get("conversation_id")  or "",
        "gif_url":          raw.get("gif_url")          or "",
        "all_media":        raw.get("all_media")        or [],
        "referenced_tweet_url": raw.get("referenced_tweet_url") or "",
        "in_reply_to_user":     raw.get("in_reply_to_user")     or "",
        # ── X/Twitter: tipe tweet + content_analysis yang diisi fetch_tweet.py ─
        "tweet_type":       raw.get("tweet_type")       or raw.get("action_type") or "POST",
        "tweet_url":        raw.get("tweet_url")        or post_url,
        "content_analysis": raw.get("content_analysis") or {},
        # ── LinkedIn ──────────────────────────────────────────────────────
        "reactions_breakdown": raw.get("reactions_breakdown") or {},
        "reactions_actors":    raw.get("reactions_actors")    or [],
        "post_images":         raw.get("post_images")         or [],
        "document":            raw.get("document")            or {},
        "article":             raw.get("article")             or {},
        # ── Facebook extra fields ─────────────────────────────────────────
        "tagged_users":    raw.get("tagged_users")  or [],
        "media_type":      raw.get("media_type")    or content_type,
        "media_count":     raw.get("media_count")   or 0,
        "media_list":      raw.get("media_list")    or [],
        # image_urls: gabungkan dari image_urls dan _raw_media_urls (spbotdel/curious_coder)
        "image_urls":      list(dict.fromkeys(
            (raw.get("image_urls") or []) +
            (raw.get("_raw_media_urls") or [])
        )),
        "reactions":       raw.get("reactions")     or {},
        "reactions_total": raw.get("reactions_total") or 0,
        "is_sponsored":    bool(raw.get("is_sponsored") or False),
        "is_story":        bool(raw.get("is_story") or False),
        "ocr_from_media":  raw.get("ocr_from_media") or "",
        "comments_count_total":   raw.get("comments_count_total") or 0,
        "comments_count_visible": raw.get("comments_count_visible") or 0,
        # ── Media extraction ──────────────────────────────────────────────
        "caption_text":       text[:700],
        "ai_description":     raw.get("ai_description") or "",   # dari _gen_vd fetch layer
        "ocr_text":           raw.get("ocr_from_media") or "",
        "audio_transcript":   "",
        "visual_description_extracted": "",
        "combined_text":      text[:700],
        "extraction_errors":  [],
    }


def _normalise_comments(raw_comments: List[Dict]) -> List[Dict]:
    result = []
    for c in raw_comments:
        if not isinstance(c, dict):
            continue
        # X/Twitter pakai "reply_text", TikTok pakai "comment_text", lain pakai "content"/"text"
        _text = (
            c.get("reply_text") or
            c.get("comment_text") or
            c.get("content") or
            c.get("text") or ""
        )
        # Normalise sentiment — bisa dict atau string
        _sent = c.get("sentiment") or {"label": "NEUTRAL", "score": 0.5}
        if isinstance(_sent, str):
            _sent = {"label": _sent.upper(), "score": 0.5}
        result.append({
            "post_url":         c.get("post_url")          or "",
            "tweet_url":        c.get("tweet_url")         or c.get("post_url") or "",
            "post_caption":     c.get("post_caption")      or "",
            "comment_text":     _text,   # unified key
            "reply_text":       _text,   # X/Twitter compat
            "content":          _text,   # backward compat
            "likes":            int(c.get("likes")   or 0),
            "replies":          int(c.get("replies") or 0),
            "quotes":           int(c.get("quotes")  or 0),
            "is_reply":         bool(c.get("is_reply", False)),
            "reply_to":         c.get("reply_to")          or c.get("in_reply_to_user") or "",
            "in_reply_to_user": c.get("in_reply_to_user")  or c.get("reply_to") or "",
            "created_at":       str(c.get("created_at") or ""),
            "lang":             c.get("lang")         or "",
            "source":           c.get("source")       or "",
            "comment_url":      c.get("comment_url")  or "",
            "sentiment":        _sent,
            # X/Twitter: content_analysis diisi fetch_tweet.py
            "content_analysis": c.get("content_analysis") or {},
        })
    return result


def _build_result(profile, activities, user_comments, reposts, scrape_errors, status_str, quotes_list=None):
    return {
        "profile":       profile,
        "activities":    activities,
        "user_comments": user_comments,   # komentar target di postingan sendiri
        "reposts":       reposts,
        "quotes_list":   quotes_list or [],
        "scrape_errors": scrape_errors
    }, status_str


# ─────────────────────────────────────────────────────────────────────────────
# MAIN: run_crawler — sekarang ASYNC
# ─────────────────────────────────────────────────────────────────────────────
async def run_crawler(
    platform: str,
    target: str,
    scan_type: str = "USER_PROFILE"
) -> Tuple[Dict[str, Any], str]:
    """
    Scraper Engine v12.0 — async, tidak pakai asyncio.run().
    Dipanggil dengan: await run_crawler(...)
    """
    p = platform.lower().strip()
    clean_target = target.replace("@", "").strip()

    logger.info(f"🚀 [{p.upper()}] Mulai scraping @{clean_target}")

    profile = _empty_profile(clean_target, p)

    try:
        # ── Pilih & panggil scraper ────────────────────────────────────────
        raw: Dict = {}

        if p == "tiktok":
            from fetch_tiktok import _tiktok_scrape_real
            raw = await _tiktok_scrape_real(clean_target, APIFY_TOKEN)

        elif p == "instagram":
            from fetch_instagram import _instagram_scrape_real
            raw = await _instagram_scrape_real(clean_target, APIFY_TOKEN)

        elif p in ("x", "twitter"):
            # Langsung pakai fetch_tweet.py (Apify cryptosignals) — proven stabil.
            # fetch_twitter_oauth (Tweepy Bearer) selalu 401 karena token expired.
            # fetch_twitter_final belum tersedia / tidak reliable.
            raw = None
            # Coba fetch_tweet (Apify) — primary path
            try:
                from fetch_tweet import _twitter_scrape_real
                raw = await _twitter_scrape_real(clean_target, APIFY_TOKEN)
            except ImportError:
                raw = None
            # Fallback ke oauth hanya kalau fetch_tweet gagal total
            if raw is None or (raw.get("status") == "error" and not raw.get("posts")):
                _bt = os.getenv("TWITTER_BEARER_TOKEN", "").strip()
                if _bt:
                    try:
                        from fetch_twitter_oauth import twitter_scrape_oauth
                        _oauth_raw = await twitter_scrape_oauth(clean_target)
                        if _oauth_raw.get("status") == "success" and _oauth_raw.get("posts"):
                            raw = _oauth_raw
                    except Exception:
                        pass

        elif p == "facebook":
            try:
                from fetch_facebook import _facebook_scrape_real
                raw = await _facebook_scrape_real(clean_target, APIFY_TOKEN)
            except ImportError:
                raw = {"status": "error", "scrape_errors": ["fetch_facebook tidak tersedia"]}

        elif p == "linkedin":
            try:
                from fetch_linkedin import _linkedin_scrape_real
                raw = await _linkedin_scrape_real(clean_target, APIFY_TOKEN)
            except ImportError:
                raw = {"status": "error", "scrape_errors": ["fetch_linkedin tidak tersedia"]}

        else:
            return _build_result(profile, [], [], [], [f"Platform '{p}' tidak didukung"], "UNSUPPORTED_PLATFORM")

        # ── Cek status ────────────────────────────────────────────────────
        scrape_errors = raw.get("scrape_errors") or []

        if raw.get("status") == "error":
            logger.error(f"❌ Scrape error: {scrape_errors}")
            return _build_result(profile, [], [], [], scrape_errors, "SCRAPE_ERROR")

        # ── Isi profile ───────────────────────────────────────────────────
        profile["username"]     = raw.get("username")    or clean_target
        profile["full_name"]    = raw.get("full_name")   or clean_target
        profile["bio"]          = raw.get("bio")         or ""
        profile["followers"]    = int(raw.get("followers") or 0)
        profile["following"]    = int(raw.get("following") or 0)
        profile["verified"]     = bool(raw.get("verified") or False)
        profile["profile_pic"]  = raw.get("profile_pic") or ""
        profile["total_posts"]  = int(raw.get("total_posts") or len(raw.get("posts") or []))
        profile["total_likes"]  = int(raw.get("total_likes") or 0)
        profile["platform"]     = p
        profile["last_updated"] = time.strftime("%Y-%m-%d")

        # ── Field tambahan per platform ───────────────────────────────────
        if p == "tiktok":
            profile["likes"]    = int(raw.get("likes") or 0)   # total hearts
            profile["user_id"]  = raw.get("user_id",  "") or ""
            profile["location"] = raw.get("location", "") or ""
            profile["website"]  = raw.get("website",  "") or ""

        elif p == "instagram":
            profile["user_id"]    = raw.get("user_id",    "") or ""
            profile["profile_url"]= raw.get("profile_url","") or ""
            profile["website"]    = raw.get("website",    "") or ""
            profile["category"]   = raw.get("category",   "") or ""
            profile["is_private"] = bool(raw.get("is_private",  False))
            profile["is_business"]= bool(raw.get("is_business", False))

        elif p == "facebook":
            profile["user_id"]      = raw.get("user_id",      "") or ""
            profile["profile_url"]  = raw.get("profile_url",  "") or ""
            profile["cover_photo"]  = raw.get("cover_photo",  "") or ""
            profile["about_me"]     = raw.get("about_me",     "") or ""
            profile["location"]     = raw.get("location") or raw.get("address") or ""
            profile["address"]      = raw.get("address",      "") or ""
            profile["website"]      = raw.get("website",      "") or ""
            profile["email"]        = raw.get("email",        "") or ""
            profile["phone"]        = raw.get("phone",        "") or ""
            profile["categories"]   = raw.get("categories",   [])
            profile["rating"]       = raw.get("rating",       "") or ""
            profile["rating_count"] = int(raw.get("rating_count") or 0)
            profile["page_likes"]   = int(raw.get("page_likes")   or 0)
            profile["join_date"]    = raw.get("join_date",    "") or ""

        elif p in ("x", "twitter"):
            profile["user_id"]      = raw.get("user_id",      "") or ""
            profile["profile_url"]  = f"https://x.com/{clean_target}"
            profile["banner_image"] = raw.get("banner_image", "") or ""
            profile["location"]     = raw.get("location",     "") or ""
            profile["website"]      = raw.get("website",      "") or ""
            profile["join_date"]    = raw.get("join_date",    "") or ""
            profile["tweet_count"]  = int(raw.get("tweet_count") or 0)
            profile["data_limitations"] = raw.get("data_limitations") or []

        elif p == "linkedin":
            profile["headline"]          = raw.get("headline",          "") or ""
            profile["about"]             = raw.get("about",             "") or ""
            profile["background_image"]  = raw.get("background_image",  "") or ""
            profile["linkedin_url"]      = raw.get("linkedin_url",      "") or ""
            profile["website"]           = raw.get("website",           "") or ""
            profile["website_label"]     = raw.get("website_label",     "") or ""
            profile["location"]          = raw.get("location",          "") or ""
            profile["industry"]          = raw.get("industry",          "") or ""
            profile["connections"]       = raw.get("connections",       "") or ""
            profile["connections_count"] = int(raw.get("connections_count") or 0)
            profile["is_creator"]        = bool(raw.get("is_creator",   False))
            profile["is_premium"]        = bool(raw.get("is_premium",   False))
            profile["is_influencer"]     = bool(raw.get("is_influencer",False))
            profile["is_open_to_work"]   = bool(raw.get("is_open_to_work",False))
            profile["is_hiring"]         = bool(raw.get("is_hiring",   False))
            profile["join_date"]         = raw.get("join_date",         "") or ""
            profile["current_company"]   = raw.get("current_company",   "") or ""
            profile["current_title"]     = raw.get("current_title",     "") or ""
            profile["experience"]        = raw.get("experience",        [])
            profile["education"]         = raw.get("education",         [])
            profile["skills"]            = raw.get("skills",            [])
            profile["certifications"]    = raw.get("certifications",    [])
            profile["languages"]         = raw.get("languages",         [])
            profile["interests"]         = raw.get("interests",         [])
            profile["volunteering"]      = raw.get("volunteering",      [])
            profile["projects"]          = raw.get("projects",          [])
            profile["publications"]      = raw.get("publications",      [])
            profile["honors"]            = raw.get("honors",            [])
            profile["courses"]           = raw.get("courses",           [])
            profile["organizations"]     = raw.get("organizations",     [])
            profile["contact_email"]     = raw.get("contact_email",     "") or ""
            profile["contact_phone"]     = raw.get("contact_phone",     "") or ""
            profile["data_limitations"]  = raw.get("data_limitations",  [])

        logger.info(
            f"✅ {profile['full_name']} | "
            f"Followers: {profile['followers']:,} | "
            f"Verified: {profile['verified']}"
        )

        # ── Normalise posts ───────────────────────────────────────────────
        raw_posts  = raw.get("posts") or []
        activities = [_normalise_post(rp, p, clean_target) for rp in raw_posts[:80]]

        logger.info(f"📊 Activities: {len(activities)}")

        if profile["total_likes"] == 0 and activities:
            profile["total_likes"] = sum(a["metrics"]["likes"] for a in activities)

        user_comments   = _normalise_comments(raw.get("user_comments") or [])
        reposts         = raw.get("reposts") or []
        quotes_list     = raw.get("quotes_list") or []
        platform_photos = raw.get("photos")  or []

        # ── OSINT scan (maigret) — jalan untuk semua platform ─────────────
        osint_result: Dict = {}
        try:
            from osint_tools import run_osint_scan
            print(f"   ↳ OSINT scan @{clean_target}...")
            osint_result = run_osint_scan(clean_target, "username", timeout=30)
            print(f"   ↳ OSINT: {osint_result.get('total_found', 0)} situs | status={osint_result.get('status')}")
        except ImportError:
            osint_result = {"status": "NOT_INSTALLED", "message": "osint_tools.py tidak ditemukan"}
        except Exception as e_osint:
            osint_result = {"status": "ERROR", "message": str(e_osint)[:100]}

        status_str = "LIVE_DATA" if activities else "NO_POSTS_FOUND"
        logger.info(f"🎉 Selesai | {status_str}")

        result_data, status = _build_result(
            profile, activities,
            user_comments,
            reposts, scrape_errors, status_str,
            quotes_list=quotes_list
        )
        if platform_photos:
            result_data["photos"] = platform_photos
        # Teruskan reels dari facebook scraper (dedicated reels list)
        raw_reels = raw.get("reels") or []
        if raw_reels:
            result_data["reels"] = raw_reels
        if osint_result:
            result_data["osint_findings"] = osint_result
        return result_data, status

    except Exception as e:
        import traceback
        logger.error(f"🚨 run_crawler error: {e}\n{traceback.format_exc()}")
        return _build_result(profile, [], [], [], [str(e)], "ERROR")