"""
fetch_twitter_oauth.py  —  Twitter/X Scraper via tweepy API v2
================================================================
Auth: App-only (Bearer Token) — untuk baca timeline publik siapapun.

KENAPA BEARER TOKEN, BUKAN OAUTH 1.0A:
  - OAuth 1.0a membutuhkan Access Token + Secret milik akun yang login.
    Itu untuk menulis tweet atau akses data akun sendiri, bukan baca
    timeline orang lain.
  - Bearer Token (App-only) adalah cara yang benar untuk GET user info
    dan GET user tweets dari akun publik manapun.
  - Endpoint v1.1 (statuses/user_timeline) sudah deprecated sejak 2023.
    Semua request baru harus pakai API v2.

SETUP (sekali saja):
  1. Buka https://developer.twitter.com → masuk dengan akun Twitter
  2. Create Project → Create App (gratis)
  3. Dashboard App → Keys and Tokens → Bearer Token → Copy
  4. Tambahkan ke .env:
       TWITTER_BEARER_TOKEN=AAAAAAAAAAAAAA...
     (nilai sudah ada di .env project ini)

FREE TIER LIMITS (Essential Access):
  - 500.000 tweet reads per bulan
  - 10 GET requests per 15 menit per endpoint
  - Max 100 tweets per request

DEPENDENCIES:
  pip install tweepy python-dotenv  (sudah terinstall)
"""

import os
import re
import sys
from typing import Dict, List, Any, Optional, Tuple
from dotenv import load_dotenv

load_dotenv()


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────
def _safe_int(v: Any, d: int = 0) -> int:
    try:
        return int(v) if v is not None else d
    except (ValueError, TypeError):
        return d


def _parse_date(raw: Any) -> str:
    if not raw:
        return ""
    s = str(raw).strip()
    try:
        import email.utils
        return email.utils.parsedate_to_datetime(s).strftime("%Y-%m-%d")
    except Exception:
        pass
    if "T" in s:          # ISO: "2026-07-26T10:30:00.000Z"
        return s[:10]
    if len(s) >= 10:
        return s[:10]
    return s


def _build_empty(username: str, error: str) -> Dict:
    return {
        "status": "error", "platform": "x", "username": username,
        "full_name": "", "bio": "", "location": "", "website": "",
        "followers": 0, "following": 0, "tweet_count": 0,
        "verified": False, "join_date": "", "profile_pic": "", "banner_image": "",
        "user_id": "", "total_posts": 0, "total_likes": 0,
        "total_comments": 0, "total_shares": 0, "has_text": False,
        "posts": [], "user_comments": [], "reposts": [], "quotes_list": [],
        "scrape_errors": [error], "data_limitations": [],
    }


# ─────────────────────────────────────────────────────────────────────────────
# CONTENT ANALYSIS HELPERS
# ─────────────────────────────────────────────────────────────────────────────
_TOPIC_KW: Dict[str, List[str]] = {
    "teknologi_ai":   ["ai","artificial intelligence","machine learning","gpt",
                       "chatgpt","openai","llm","neural","deepmind","agi","robot","automation"],
    "teknologi_umum": ["tech","software","hardware","coding","programming","developer",
                       "startup","apple","google","microsoft","tesla","spacex","elon",
                       "meta","algorithm","data","cloud","cyber","silicon valley"],
    "politik":        ["politics","government","president","election","vote","policy",
                       "democracy","congress","senate","trump","biden","harris",
                       "liberal","conservative","law","political"],
    "bisnis_ekonomi": ["business","economy","market","stock","bitcoin","crypto",
                       "finance","invest","money","bank","trade","inflation","ceo"],
    "olahraga":       ["football","soccer","sport","goal","match","game","win",
                       "champion","nfl","nba","fifa","world cup","league","player"],
    "hiburan":        ["funny","fun","comedy","laugh","meme","viral","entertainment",
                       "movie","film","music","song","artist","celebrity"],
    "sains_alam":     ["science","climate","environment","planet","universe","nasa",
                       "space","research","biology","physics","nature","earth"],
    "sosial_budaya":  ["culture","society","community","rights","equality",
                       "education","health","mental health","wellbeing"],
    "motivasi":       ["believe","dream","work hard","never give up","inspire",
                       "success","goal","mindset","positive","growth"],
    "opini_kritik":   ["think","opinion","believe","argue","wrong","right",
                       "truth","fact","hot take","controversial","thread"],
    "humor_meme":     ["lol","lmao","bruh","bro","omg","wtf","fr","ngl","no cap",
                       "based","vibe","mood","wkwk","ngakak"],
    "personal":       ["today","morning","night","feel","feeling","life","day",
                       "love","miss","grateful","tired","happy","sad"],
}

_MOOD: Dict[str, str] = {
    "teknologi_ai":   "antusias, analitis, visioner",
    "teknologi_umum": "informatif, teknikal, forward-looking",
    "politik":        "kritis, opiniatif, passionate",
    "bisnis_ekonomi": "strategis, analitis, ambisius",
    "olahraga":       "bersemangat, kompetitif, supportif",
    "hiburan":        "santai, menghibur, ekspresif",
    "sains_alam":     "intelektual, kritis, peduli lingkungan",
    "sosial_budaya":  "empatik, reflektif, sosial",
    "motivasi":       "inspiratif, positif, memotivasi",
    "opini_kritik":   "tegas, kritis, berani",
    "humor_meme":     "lucu, ringan, relatable",
    "personal":       "personal, reflektif, autentik",
}

_OBJECTS: Dict[str, str] = {
    "teknologi_ai":   "model AI, algoritma, chatbot, robot, data",
    "teknologi_umum": "gadget, software, platform, perusahaan tech",
    "politik":        "kebijakan, kandidat, isu sosial, institusi",
    "bisnis_ekonomi": "pasar, aset, perusahaan, angka ekonomi",
    "olahraga":       "pemain, tim, stadion, kompetisi, skor",
    "hiburan":        "artis, konten, meme, video, quotes",
    "sains_alam":     "data ilmiah, lingkungan, fenomena alam",
    "sosial_budaya":  "komunitas, isu sosial, nilai budaya",
    "motivasi":       "kata-kata inspiratif, pengalaman, pencapaian",
    "opini_kritik":   "argumen, fakta, sudut pandang, perdebatan",
    "humor_meme":     "meme, lelucon, situasi lucu, referensi internet",
    "personal":       "pengalaman sehari-hari, perasaan, momen pribadi",
}

_ACTIVITY: Dict[str, str] = {
    "teknologi_ai":   "mendiskusikan perkembangan AI dan teknologi",
    "teknologi_umum": "berbagi insight teknologi dan inovasi",
    "politik":        "menyampaikan opini atau merespons isu politik",
    "bisnis_ekonomi": "mendiskusikan tren bisnis dan ekonomi",
    "olahraga":       "merespons atau mendiskusikan event olahraga",
    "hiburan":        "berbagi konten hiburan dan meme",
    "sains_alam":     "mendiskusikan temuan atau isu sains",
    "sosial_budaya":  "berbagi pandangan tentang isu sosial",
    "motivasi":       "memberi inspirasi dan motivasi",
    "opini_kritik":   "menyampaikan opini dan kritik",
    "humor_meme":     "berbagi humor dan konten ringan",
    "personal":       "berbagi momen dan perasaan pribadi",
}


def _detect_topic(text: str, hashtags: List[str] = None) -> str:
    """Deteksi topik dominan dari teks tweet + hashtags."""
    all_lower = (text + " " + " ".join(hashtags or [])).lower()
    scores: Dict[str, int] = {}
    for topic, kws in _TOPIC_KW.items():
        hits = sum(1 for kw in kws if kw in all_lower)
        if hits:
            scores[topic] = hits
    return max(scores, key=lambda k: scores[k]) if scores else "umum"


def _detect_mood(text: str, topic: str) -> str:
    """Deteksi mood dari topik."""
    return _MOOD.get(topic, "ekspresif, informatif")


def _detect_objects(text: str, topic: str) -> str:
    """Deteksi objek konten dari topik."""
    return _OBJECTS.get(topic, "teks, opini, informasi")


def _detect_activity(text: str, topic: str) -> str:
    """Deteksi aktivitas dari topik."""
    return _ACTIVITY.get(topic, "berbagi informasi atau opini")


def _engagement_level(likes: int, retweets: int,
                       replies: int, views: int = 0) -> str:
    """Hitung level engagement berdasarkan semua metrik."""
    total = likes + (retweets * 2) + (replies * 3) + (views // 1000 if views else 0)
    if total >= 100_000: return "SANGAT TINGGI"
    if total >= 10_000:  return "TINGGI"
    if total >= 1_000:   return "SEDANG"
    return "RENDAH"


def _build_ai_description(
    text: str,
    likes: int, retweets: int, replies: int, views: int,
    hashtags: List[str],
    mentions: List[str],
    topic: str,
    mood: str,
    tweet_type: str = "POST",
    reply_to: str = "",
    orig_author: str = "",
    orig_text: str = "",
    created_at: str = "",
    lang: str = "en",
    source: str = "Twitter API",
) -> str:
    """
    Generate ai_description yang detail dan deskriptif.
    Menjelaskan tipe tweet, isi, topik, engagement, dan konteks.
    """
    clean = re.sub(r"\s+", " ", re.sub(r"https?://\S+", "", text)).strip()
    wc    = len(clean.split())
    lang_str = ("Bahasa Indonesia" if lang in ("id", "in")
                else "Bahasa Inggris" if lang == "en"
                else f"bahasa {lang}" if lang else "tidak diketahui")

    parts: List[str] = []

    # Pembuka berdasarkan tipe
    if tweet_type == "RETWEET":
        parts.append(
            f"Ini adalah RETWEET dari tweet milik @{orig_author}. "
            f"Dengan me-retweet, pengguna menyebarluaskan konten ini kepada follower-nya, "
            f"menunjukkan keselarasan nilai atau ketertarikan terhadap topik yang diangkat."
        )
        if orig_text:
            parts.append(f'Konten yang di-retweet: "{orig_text[:250]}".')
    elif tweet_type == "QUOTE":
        parts.append(
            f"Ini adalah QUOTE TWEET — pengguna mengutip tweet "
            f"{'dari @' + orig_author if orig_author else 'orang lain'} "
            f"sambil menambahkan perspektif pribadi."
        )
        if clean:
            parts.append(f'Komentar yang ditambahkan: "{clean[:250]}".')
    elif tweet_type == "REPLY":
        ctx = f"membalas @{reply_to}" if reply_to else "membalas tweet orang lain"
        parts.append(
            f"Ini adalah REPLY — pengguna sedang {ctx}, "
            f"menunjukkan keterlibatan aktif dalam percakapan."
        )
        if clean:
            parts.append(f'Isi balasan: "{clean[:250]}".')
    else:
        gaya = ("panjang dan elaboratif" if wc >= 30
                else "sangat singkat" if wc <= 5
                else "kasual dan ekspresif")
        parts.append(
            f"Ini adalah TWEET ORIGINAL yang dibuat dan diterbitkan langsung oleh pengguna. "
            f'Isi tweet: "{clean[:400]}". '
            f"Ditulis dalam {lang_str} dengan gaya {gaya}."
        )

    # Konteks topik
    _ctx = {
        "teknologi_ai":   "terkait perkembangan AI dan dampaknya",
        "teknologi_umum": "membahas teknologi atau inovasi",
        "politik":        "menyentuh isu politik atau kebijakan",
        "bisnis_ekonomi": "berkaitan dengan bisnis atau ekonomi",
        "olahraga":       "berhubungan dengan olahraga atau kompetisi",
        "hiburan":        "berisi konten hiburan atau meme",
        "sains_alam":     "membahas sains atau lingkungan",
        "sosial_budaya":  "menyentuh isu sosial atau budaya",
        "motivasi":       "mengandung pesan motivasi atau inspirasi",
        "opini_kritik":   "mengekspresikan opini kritis",
        "humor_meme":     "bersifat humoristis dengan referensi internet culture",
        "personal":       "berbagi pengalaman atau perasaan personal",
    }
    parts.append(
        f"Konten ini {_ctx.get(topic, 'bersifat informatif')}, "
        f"topik utama terdeteksi sebagai '{topic}'. Suasana (mood): {mood}."
    )

    # Elemen konten
    if hashtags:
        parts.append(f"Hashtag: {' '.join('#' + h for h in hashtags[:8])}.")
    if mentions:
        parts.append(f"Menyebut akun: {' '.join('@' + m for m in mentions[:5])}.")

    # Engagement
    eng = _engagement_level(likes, retweets, replies, views)
    if eng == "SANGAT TINGGI":
        parts.append(
            f"Engagement tweet ini SANGAT TINGGI dengan {likes:,} likes, "
            f"{retweets:,} retweets, dan {replies:,} replies"
            + (f" dari {views:,} views" if views else "")
            + ". Konten ini resonan kuat dengan audiens luas."
        )
    elif eng == "TINGGI":
        parts.append(
            f"Engagement TINGGI: {likes:,} likes, {retweets:,} retweets, {replies:,} replies."
        )
    elif likes > 0 or retweets > 0:
        parts.append(f"Engagement: {likes:,} likes, {retweets:,} retweets.")

    if created_at:
        parts.append(f"Diterbitkan pada {created_at}.")
    if source:
        parts.append(f"Data diambil via {source}.")

    return " ".join(parts)


# ─────────────────────────────────────────────────────────────────────────────
# POST BUILDER
# ─────────────────────────────────────────────────────────────────────────────
def _make_post(
    tweet_id: str, text: str, created_at: str,
    likes: int, retweets: int, replies: int,
    quotes: int, views: int, bookmarks: int,
    lang: str, hashtags: List[str], mentions: List[str], urls: List[str],
    is_reply: bool, is_retweet: bool, is_quote: bool,
    in_reply_to_user: str, in_reply_to_id: str, referenced_url: str,
    orig_author: str, orig_text: str,
    image_url: str, video_url: str,
    username: str,
) -> Dict:
    tweet_url = (
        f"https://twitter.com/{username}/status/{tweet_id}"
        if tweet_id.isdigit()
        else f"https://twitter.com/{username}"
    )

    if is_retweet:   tweet_type = "RETWEET"
    elif is_quote:   tweet_type = "QUOTE"
    elif is_reply:   tweet_type = "REPLY"
    else:            tweet_type = "POST"

    topic    = _detect_topic(text, hashtags)
    mood     = _detect_mood(text, topic)
    objects  = _detect_objects(text, topic)
    activity = _detect_activity(text, topic)
    eng_lvl  = _engagement_level(likes, retweets, replies, views)

    summary = re.sub(r"\s+", " ",
               re.sub(r"[#@]\w+", "",
               re.sub(r"https?://\S+", "", text))).strip()

    ai_desc = _build_ai_description(
        text=text, likes=likes, retweets=retweets,
        replies=replies, views=views,
        hashtags=hashtags, mentions=mentions,
        topic=topic, mood=mood, tweet_type=tweet_type,
        reply_to=in_reply_to_user, orig_author=orig_author,
        orig_text=orig_text[:300], created_at=created_at, lang=lang,
        source="Twitter API v2",
    )

    media_type = "video" if video_url else "image" if image_url else "text"

    return {
        "id":              tweet_id,
        "post_id":         tweet_id,
        "content":         text,
        "tweet_url":       tweet_url,
        "post_url":        tweet_url,
        "created_at":      created_at,
        "lang":            lang,
        "source":          "Twitter API OAuth",
        "likes":           likes,
        "comments":        replies,
        "shares":          retweets,
        "plays":           views,
        "quotes":          quotes,
        "bookmarks":       bookmarks,
        "image_url":       image_url,
        "video_url":       video_url,
        "gif_url":         "",
        "cover_url":       image_url or video_url,
        "all_media":       ([{"url": image_url, "type": "image"}] if image_url else
                            [{"url": video_url, "type": "video"}] if video_url else []),
        "media_type":      media_type,
        "duration_sec":    0,
        "hashtags":        hashtags,
        "mentions":        mentions,
        "urls":            urls,
        "is_reply":        is_reply,
        "is_repost":       is_retweet,
        "is_quote":        is_quote,
        "tweet_type":      tweet_type,
        "action_type":     tweet_type,
        "referenced_tweet_url": referenced_url,
        "in_reply_to_user":     in_reply_to_user,
        "in_reply_to_id":       in_reply_to_id,
        "sentiment":            {"label": "NEUTRAL", "score": 0.5},
        "content_analysis": {
            "topic":            topic,
            "mood":             mood,
            "objects":          objects,
            "activity":         activity,
            "content_summary":  summary[:200],
            "ai_description":   ai_desc,
            "key_themes":       [topic] + hashtags[:3],
            "engagement_level": eng_lvl,
        },
        "comments_data":      [],
        "music":              {"title": "", "author": ""},
        "visual_description": ai_desc,
        "topic":    topic,
        "mood":     mood,
        "objects":  objects,
        "activity": activity,
        "metrics_dict": {
            "likes": likes, "retweets": retweets,
            "replies": replies, "quotes": quotes,
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
# MAIN SCRAPER
# ─────────────────────────────────────────────────────────────────────────────
def _twitter_scrape_oauth(username: str, max_tweets: int = 20) -> Dict:
    """
    Scrape Twitter/X via tweepy + Twitter API v2 (Bearer Token / App-only).

    Auth: Bearer Token — dipakai untuk GET user info & GET user tweets.
    Tidak perlu Access Token. Tidak perlu login.
    Works untuk semua akun publik.

    Args:
        username:   Twitter handle tanpa @
        max_tweets: Jumlah tweet yang diambil (max 100 per request, default 20)

    Returns:
        Dict dengan struktur lengkap sesuai project standard.
    """
    bearer_token = os.getenv("TWITTER_BEARER_TOKEN", "").strip()
    # URL-decode jika perlu (kadang Bearer Token tersimpan dengan %2B dll)
    if "%" in bearer_token:
        from urllib.parse import unquote
        bearer_token = unquote(bearer_token)

    if not bearer_token:
        msg = (
            "TWITTER_BEARER_TOKEN tidak ada di .env. "
            "Setup: developer.twitter.com → App → Keys and Tokens → Bearer Token"
        )
        print(f"   ❌ {msg}")
        return _build_empty(username, msg)

    try:
        import tweepy
    except ImportError:
        return _build_empty(username, "tweepy tidak terinstall — pip install tweepy")

    clean = username.replace("@", "").strip()
    print(f"\n{'='*60}")
    print(f"📡 [Twitter OAuth] Scraping @{clean} via Twitter API v2")
    print(f"{'='*60}")

    # ── Init client ───────────────────────────────────────────────────────
    try:
        client = tweepy.Client(
            bearer_token=bearer_token,
            wait_on_rate_limit=True,    # auto-wait saat rate limit
        )
        print(f"   ✅ Client initialized")
    except Exception as e:
        return _build_empty(clean, f"tweepy Client error: {e}")

    # ── GET user info ─────────────────────────────────────────────────────
    print(f"   ↳ [1/2] GET user info untuk @{clean}...")
    try:
        user_resp = client.get_user(
            username=clean,
            user_fields=[
                "description", "location", "url", "public_metrics",
                "verified", "created_at", "profile_image_url",
                "name", "id", "pinned_tweet_id", "entities",
            ],
        )
    except tweepy.errors.Unauthorized:
        return _build_empty(
            clean,
            "401 Unauthorized — Bearer Token tidak valid atau sudah expired. "
            "Generate ulang di developer.twitter.com → App → Keys and Tokens"
        )
    except tweepy.errors.Forbidden:
        return _build_empty(
            clean,
            "403 Forbidden — App belum punya izin 'Read' permission. "
            "Cek di developer.twitter.com → App Settings → App permissions"
        )
    except tweepy.errors.NotFound:
        return _build_empty(clean, f"404 — User @{clean} tidak ditemukan")
    except tweepy.errors.TooManyRequests:
        return _build_empty(
            clean,
            "429 Rate limit — terlalu banyak request. Tunggu 15 menit lalu coba lagi."
        )
    except tweepy.errors.TweepyException as e:
        return _build_empty(clean, f"tweepy error GET user: {e}")

    if not user_resp or not user_resp.data:
        return _build_empty(clean, f"User @{clean} tidak ditemukan atau akun private")

    u  = user_resp.data
    pm = u.public_metrics or {}

    # Ambil website dari entities jika ada
    website = ""
    if u.entities and u.entities.get("url"):
        for url_obj in (u.entities["url"].get("urls") or []):
            exp = url_obj.get("expanded_url") or url_obj.get("url") or ""
            if exp and "t.co" not in exp:
                website = exp
                break
    if not website:
        website = str(u.url or "")

    profile = {
        "user_id":     str(u.id),
        "full_name":   u.name or clean,
        "bio":         u.description or "",
        "location":    u.location or "",
        "website":     website,
        "followers":   pm.get("followers_count", 0),
        "following":   pm.get("following_count", 0),
        "tweet_count": pm.get("tweet_count", 0),
        "verified":    bool(u.verified or False),
        "join_date":   _parse_date(u.created_at),
        "profile_pic": str(u.profile_image_url or "").replace("_normal", "_400x400"),
        "banner_image": "",
    }

    print(
        f"   ✅ Profile: {profile['full_name']} | "
        f"Followers: {profile['followers']:,} | "
        f"Verified: {profile['verified']} | "
        f"Join: {profile['join_date'] or '?'}"
    )

    # ── GET tweets ────────────────────────────────────────────────────────
    print(f"   ↳ [2/2] GET {max_tweets} tweets untuk @{clean}...")
    try:
        tweets_resp = client.get_users_tweets(
            id=profile["user_id"],
            max_results=min(max(5, max_tweets), 100),   # API min=5, max=100
            tweet_fields=[
                "created_at", "public_metrics", "lang",
                "referenced_tweets", "entities", "attachments",
                "conversation_id", "in_reply_to_user_id",
                "possibly_sensitive",
            ],
            media_fields=["url", "preview_image_url", "type"],
            expansions=[
                "attachments.media_keys",
                "referenced_tweets.id",
                "referenced_tweets.id.author_id",
                "in_reply_to_user_id",
            ],
            # exclude=["retweets"] — comment ini jika mau ambil RT juga
        )
    except tweepy.errors.Unauthorized:
        return _build_empty(
            clean,
            "401 saat GET tweets — Bearer Token tidak valid. "
            "Regenerate di developer.twitter.com"
        )
    except tweepy.errors.Forbidden as e:
        return _build_empty(
            clean,
            f"403 saat GET tweets — kemungkinan akun private atau app permission: {e}"
        )
    except tweepy.errors.TooManyRequests:
        return _build_empty(
            clean,
            "429 Rate limit saat GET tweets. Tunggu 15 menit."
        )
    except tweepy.errors.TweepyException as e:
        return _build_empty(clean, f"tweepy error GET tweets: {e}")

    if not tweets_resp or not tweets_resp.data:
        # Akun ada tapi 0 tweet (bisa karena exclude filters)
        print(f"   ⚠️  Tidak ada tweet untuk @{clean} (akun private atau belum tweet)")
        return {
            **_build_empty(clean, ""),
            "status":   "success",
            "full_name": profile["full_name"],
            "bio":       profile["bio"],
            "followers": profile["followers"],
            "following": profile["following"],
            "tweet_count": profile["tweet_count"],
            "verified":  profile["verified"],
            "join_date": profile["join_date"],
            "profile_pic": profile["profile_pic"],
            "user_id":   profile["user_id"],
            "scrape_errors": [],
            "data_limitations": ["Tidak ada tweet — mungkin akun private atau 0 tweet"],
        }

    # Build lookup tables dari includes
    media_lookup: Dict[str, Any] = {}
    ref_lookup:   Dict[str, Any] = {}
    user_lookup:  Dict[str, str] = {}  # user_id → username

    if tweets_resp.includes:
        for m in (tweets_resp.includes.get("media") or []):
            mk = m.get("media_key") if isinstance(m, dict) else getattr(m, "media_key", "")
            if mk:
                media_lookup[mk] = m

        for rt in (tweets_resp.includes.get("tweets") or []):
            rt_id = str(rt.id) if hasattr(rt, "id") else str(rt.get("id", ""))
            if rt_id:
                ref_lookup[rt_id] = rt

        for pu in (tweets_resp.includes.get("users") or []):
            pu_id  = str(pu.id) if hasattr(pu, "id") else str(pu.get("id", ""))
            pu_usr = pu.username if hasattr(pu, "username") else pu.get("username", "")
            if pu_id and pu_usr:
                user_lookup[pu_id] = pu_usr

    print(f"   ✅ {len(tweets_resp.data)} tweets diterima")

    # ── Parse tweets ──────────────────────────────────────────────────────
    posts:         List[Dict] = []
    user_comments: List[Dict] = []
    reposts:       List[Dict] = []
    quotes_list:   List[Dict] = []

    for tw in tweets_resp.data:
        tw_id  = str(tw.id)
        text   = tw.text or ""
        pm_tw  = tw.public_metrics or {}
        likes      = pm_tw.get("like_count", 0)
        retweets_n = pm_tw.get("retweet_count", 0)
        replies_n  = pm_tw.get("reply_count", 0)
        quotes_n   = pm_tw.get("quote_count", 0)
        bookmarks  = pm_tw.get("bookmark_count", 0)
        views      = pm_tw.get("impression_count", 0)
        created_at = _parse_date(tw.created_at)
        lang       = tw.lang or "en"

        # Entities
        ents     = tw.entities or {}
        hashtags = [h.get("tag", "") or h.get("text", "")
                    for h in ents.get("hashtags", []) if isinstance(h, dict)]
        mentions = [m.get("username", "") for m in ents.get("mentions", []) if isinstance(m, dict)]
        urls_raw = [u.get("expanded_url") or u.get("url", "")
                    for u in ents.get("urls", []) if isinstance(u, dict)]
        urls     = [u for u in urls_raw if u and "t.co" not in u and "twitter.com/i/" not in u]
        if not hashtags: hashtags = re.findall(r"#(\w+)", text)
        if not mentions: mentions = re.findall(r"@(\w+)", text)

        # Media
        image_url = video_url = ""
        attach_data = tw.attachments or {}
        media_keys  = (attach_data.get("media_keys")
                       if isinstance(attach_data, dict)
                       else getattr(attach_data, "media_keys", []) or [])
        for mk in (media_keys or []):
            m_data = media_lookup.get(mk)
            if not m_data:
                continue
            mtype = (m_data.get("type") if isinstance(m_data, dict)
                     else getattr(m_data, "type", ""))
            murl  = (m_data.get("url") or m_data.get("preview_image_url", "")
                     if isinstance(m_data, dict)
                     else getattr(m_data, "url", "") or getattr(m_data, "preview_image_url", ""))
            murl  = str(murl or "")
            if mtype == "video":
                video_url = video_url or murl
            elif murl:
                image_url = image_url or murl

        # Referenced tweets → tipe RT / Quote / Reply
        refs = tw.referenced_tweets or []
        if isinstance(refs, list) and refs and not isinstance(refs[0], dict):
            refs = [{"type": getattr(r, "type", ""), "id": str(getattr(r, "id", ""))}
                    for r in refs]

        is_retweet = any(r.get("type") == "retweeted" for r in refs if isinstance(r, dict))
        is_quote   = any(r.get("type") == "quoted"    for r in refs if isinstance(r, dict))
        is_reply   = any(r.get("type") == "replied_to" for r in refs if isinstance(r, dict))
        # Fallback: cek in_reply_to_user_id
        if not is_reply and getattr(tw, "in_reply_to_user_id", None):
            is_reply = True

        in_reply_to_user = ""
        in_reply_to_id   = ""
        orig_author = orig_text = referenced_url = ""

        for ref in refs:
            if not isinstance(ref, dict):
                continue
            ref_id   = str(ref.get("id", ""))
            ref_type = ref.get("type", "")
            ref_tw   = ref_lookup.get(ref_id)

            if ref_type == "replied_to":
                in_reply_to_id = ref_id
                if ref_tw:
                    irt_uid = str(getattr(ref_tw, "author_id", "") or "")
                    in_reply_to_user = user_lookup.get(irt_uid, irt_uid)

            if ref_type in ("retweeted", "quoted") and ref_tw:
                orig_text = getattr(ref_tw, "text", "") or ""
                rt_uid    = str(getattr(ref_tw, "author_id", "") or "")
                orig_author = user_lookup.get(rt_uid, rt_uid)
                referenced_url = f"https://twitter.com/i/status/{ref_id}"

        post = _make_post(
            tweet_id=tw_id, text=text, created_at=created_at,
            likes=likes, retweets=retweets_n, replies=replies_n,
            quotes=quotes_n, views=views, bookmarks=bookmarks,
            lang=lang, hashtags=hashtags, mentions=mentions, urls=urls,
            is_reply=is_reply, is_retweet=is_retweet, is_quote=is_quote,
            in_reply_to_user=in_reply_to_user, in_reply_to_id=in_reply_to_id,
            referenced_url=referenced_url, orig_author=orig_author,
            orig_text=orig_text[:300],
            image_url=image_url, video_url=video_url,
            username=clean,
        )

        tweet_type = post["tweet_type"]

        if tweet_type == "RETWEET":
            reposts.append({
                "video_url":           post["tweet_url"],
                "original_author":     orig_author,
                "original_author_url": f"https://twitter.com/{orig_author}" if orig_author else "",
                "original_tweet_url":  referenced_url,
                "original_caption":    orig_text[:300],
                "repost_date":         created_at,
                "hashtags":            hashtags,
                "mentions":            mentions,
                "content_analysis":    post["content_analysis"],
                "metrics":             post["metrics_dict"],
                "sentiment":           {"label": "NEUTRAL", "score": 0.5},
                "content_description": post["visual_description"],
            })
            # RETWEET tidak masuk posts/activities

        elif tweet_type == "QUOTE":
            quotes_list.append({
                **post,
                "original_author": orig_author,
                "original_text":   orig_text[:300],
                "quote_comment":   text,
            })
            posts.append(post)

        elif tweet_type == "REPLY":
            user_comments.append({
                "post_url":         post["tweet_url"],
                "post_caption":     "",
                "post_owner":       clean,
                "content":          text,
                "likes":            likes,
                "replies":          replies_n,
                "quotes":           quotes_n,
                "is_reply":         True,
                "reply_to":         in_reply_to_user,
                "in_reply_to_id":   in_reply_to_id,
                "created_at":       created_at,
                "lang":             lang,
                "source":           "Twitter API OAuth",
                "sentiment":        {"label": "NEUTRAL", "score": 0.5},
                "content_analysis": post["content_analysis"],
            })
            posts.append(post)

        else:  # POST original
            posts.append(post)

    # Batasi output
    posts         = posts[:20]
    user_comments = user_comments[:15]
    reposts       = reposts[:10]
    quotes_list   = quotes_list[:10]

    total_likes    = sum(p.get("likes",    0) for p in posts)
    total_comments = sum(p.get("comments", 0) for p in posts)
    total_shares   = sum(p.get("shares",   0) for p in posts)

    print(
        f"\n   ✅ Posts: {len(posts)} | user_comments: {len(user_comments)} | "
        f"reposts: {len(reposts)} | quotes: {len(quotes_list)}"
    )
    print(f"   ✅ Total likes: {total_likes:,} | shares: {total_shares:,}")

    return {
        "status":         "success",
        "platform":       "x",
        "username":       clean,
        "user_id":        profile["user_id"],
        "full_name":      profile["full_name"],
        "bio":            profile["bio"],
        "location":       profile["location"],
        "website":        profile["website"],
        "followers":      profile["followers"],
        "following":      profile["following"],
        "tweet_count":    profile["tweet_count"],
        "verified":       profile["verified"],
        "join_date":      profile["join_date"],
        "profile_pic":    profile["profile_pic"],
        "banner_image":   profile["banner_image"],
        "total_posts":    len(posts),
        "total_likes":    total_likes,
        "total_comments": total_comments,
        "total_shares":   total_shares,
        "has_text":       any(p.get("content") for p in posts),
        "posts":          posts,
        "user_comments":  user_comments,
        "reposts":        reposts,
        "quotes_list":    quotes_list,
        "scrape_errors":  [],
        "data_limitations": [
            "Twitter API v2 Essential — max 100 tweets per request, 10 req/15min",
            "view_count (impression_count): hanya tersedia untuk tweet sendiri di free tier",
            "bookmarks: hanya tersedia untuk tweet sendiri di free tier",
            "exclude retweets: matikan exclude=['retweets'] di kode jika butuh RT",
        ],
    }


# ─────────────────────────────────────────────────────────────────────────────
# PUBLIC API — async wrapper untuk scraper_engine + sync alias
# ─────────────────────────────────────────────────────────────────────────────
import asyncio
from functools import partial


async def twitter_scrape_oauth(username: str, max_tweets: int = 20) -> Dict:
    """Async entry point — dipakai scraper_engine dan FastAPI."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None, partial(_twitter_scrape_oauth, username, max_tweets)
    )


# Alias untuk integrasi ke fetch_twitter_final.py dan scraper_engine.py
_twitter_scrape_oauth_sync = _twitter_scrape_oauth


# ─────────────────────────────────────────────────────────────────────────────
# TEST BLOCK
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import json

    target = sys.argv[1] if len(sys.argv) > 1 else "elonmusk"
    print(f"Test fetch_twitter_oauth.py → @{target}\n")

    result = _twitter_scrape_oauth(target, max_tweets=10)

    print(f"\n{'='*60}")
    print(f"HASIL:")
    print(f"  status        : {result.get('status')}")
    print(f"  username      : @{result.get('username')}")
    print(f"  full_name     : {result.get('full_name')}")
    print(f"  followers     : {result.get('followers', 0):,}")
    print(f"  following     : {result.get('following', 0):,}")
    print(f"  verified      : {result.get('verified')}")
    print(f"  join_date     : {result.get('join_date')}")
    print(f"  total_posts   : {result.get('total_posts')}")
    print(f"  user_comments : {len(result.get('user_comments', []))}")
    print(f"  reposts       : {len(result.get('reposts', []))}")
    print(f"  quotes        : {len(result.get('quotes_list', []))}")
    print(f"  errors        : {result.get('scrape_errors', [])}")

    posts = result.get("posts", [])
    if posts:
        print(f"\nSample Tweet:")
        p  = posts[0]
        ca = p.get("content_analysis", {})
        print(f"  tweet_type    : {p.get('tweet_type')}")
        print(f"  created_at    : {p.get('created_at')}")
        print(f"  likes         : {p.get('likes', 0):,}")
        print(f"  retweets      : {p.get('shares', 0):,}")
        print(f"  content       : {p.get('content', '')[:100]}...")
        print(f"  topic         : {ca.get('topic')}")
        print(f"  mood          : {ca.get('mood')}")
        print(f"  engagement    : {ca.get('engagement_level')}")
        print(f"  ai_description: {ca.get('ai_description', '')[:200]}...")
    else:
        print(f"\n⚠️  Tidak ada posts. Status: {result.get('status')}")
        for e in result.get("scrape_errors", []):
            print(f"  Error: {e}")
        print(f"\n  Data limitations:")
        for lim in result.get("data_limitations", []):
            print(f"  - {lim}")

    # Simpan output ke file untuk inspect
    out_file = f"_result_oauth_{target}.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n✅ Full output → {out_file}")
