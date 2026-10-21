"""
fetch_tweet.py - Twitter/X Scraper via Apify v5.0
Actor: apidojo/twitter-profile-scraper

YANG DIAMBIL:
  Profile   : user_id, username, full_name, bio, followers, following,
              verified, profile_pic, banner_image, location, website,
              join_date, tweet_count
  Activities: text, metrics (likes/retweets/replies/quotes/views/bookmarks),
              media, hashtags, mentions, urls, created_at, lang
  Tipe tweet: POST / REPLY / RETWEET / QUOTE
  user_comments: HANYA reply yang ditulis oleh target user sendiri
  retweets  : tweet yang di-RT oleh target
  quotes    : tweet yang di-QT oleh target

content_analysis per tweet (diisi di fetch level):
  topic, mood, objects, activity, content_summary,
  ai_description (SANGAT DETAIL), key_themes, engagement_level
"""

import re
import asyncio
from typing import Dict, List, Any, Optional, Tuple
from functools import partial


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────
def _safe_int(v: Any, d: int = 0) -> int:
    try:
        return int(v) if v is not None else d
    except (ValueError, TypeError):
        return d


def _safe_str(v: Any, d: str = "") -> str:
    return d if v is None else str(v).strip()


def _parse_date(raw: Any) -> str:
    """Parse berbagai format tanggal ke YYYY-MM-DD."""
    if not raw:
        return ""
    s = str(raw).strip()
    # RFC 2822: "Wed Mar 05 14:23:01 +0000 2026"
    try:
        import email.utils
        return email.utils.parsedate_to_datetime(s).strftime("%Y-%m-%d")
    except Exception:
        pass
    if len(s) >= 10:
        return s[:10]
    return s


def _build_empty(username: str, error: str) -> Dict:
    return {
        "status": "error", "platform": "x", "username": username,
        "full_name": "", "bio": "", "location": "", "website": "",
        "followers": 0, "following": 0, "tweet_count": 0,
        "verified": False, "join_date": "", "profile_pic": "",
        "banner_image": "", "user_id": "",
        "total_posts": 0, "total_likes": 0, "total_comments": 0, "total_shares": 0,
        "has_text": False,
        "posts": [], "user_comments": [], "reposts": [], "quotes_list": [],
        "scrape_errors": [error], "data_limitations": [error],
    }


# ─────────────────────────────────────────────────────────────────────────────
# CONTENT ANALYSIS ENGINE — Twitter/X aware
# ─────────────────────────────────────────────────────────────────────────────

# Topic keywords — X/Twitter biased (lebih ke isu global, tech, politik, dll)
_TWITTER_TOPICS: Dict[str, List[str]] = {
    "teknologi_ai":   ["ai", "artificial intelligence", "machine learning", "gpt", "openai",
                       "robot", "automation", "neural", "llm", "chatgpt", "deepmind", "agi"],
    "teknologi_umum": ["tech", "software", "hardware", "coding", "programming", "developer",
                       "startup", "silicon valley", "apple", "google", "microsoft", "tesla",
                       "spacex", "elon", "meta", "algorithm", "data", "cloud", "cyber"],
    "politik":        ["politics", "government", "president", "election", "vote", "policy",
                       "democracy", "freedom", "congress", "senate", "trump", "biden", "harris",
                       "liberal", "conservative", "left", "right", "political", "law", "bill",
                       "senate", "house", "federal", "state", "country", "nation"],
    "bisnis_ekonomi": ["business", "economy", "market", "stock", "bitcoin", "crypto", "finance",
                       "invest", "money", "bank", "trade", "gdp", "inflation", "company", "ceo",
                       "startup", "entrepreneur", "revenue", "profit"],
    "olahraga":       ["football", "soccer", "sport", "goal", "match", "game", "win", "champion",
                       "nfl", "nba", "fifa", "world cup", "league", "player", "team", "coach",
                       "bola", "sepak", "olahraga", "gol", "juara"],
    "hiburan":        ["funny", "fun", "comedy", "laugh", "meme", "viral", "entertainment",
                       "movie", "film", "music", "song", "artist", "celeb", "celebrity",
                       "lucu", "komedi", "hiburan", "seru"],
    "sains_alam":     ["science", "climate", "environment", "planet", "universe", "nasa",
                       "space", "research", "study", "data", "facts", "biology", "physics",
                       "nature", "earth", "ocean", "global warming", "energy"],
    "sosial_budaya":  ["culture", "society", "social", "community", "rights", "equality",
                       "education", "health", "mental health", "wellbeing", "charity",
                       "budaya", "masyarakat", "sosial", "pendidikan", "kesehatan"],
    "motivasi":       ["believe", "dream", "work hard", "never give up", "inspire", "legend",
                       "success", "goal", "mindset", "positive", "growth",
                       "percaya", "mimpi", "semangat", "inspirasi", "sukses"],
    "opini_kritik":   ["think", "opinion", "believe", "argue", "wrong", "right", "actually",
                       "honestly", "truth", "fact", "real talk", "thread", "unpopular opinion",
                       "hot take", "controversial", "overrated", "underrated"],
    "berita_terkini": ["breaking", "news", "update", "just in", "report", "confirmed",
                       "announced", "happened", "today", "now", "latest", "exclusive"],
    "humor_meme":     ["lol", "lmao", "lmfao", "bruh", "bro", "babe", "omg", "wtf", "fr",
                       "ngl", "imo", "tbh", "no cap", "based", "slay", "vibe", "mood",
                       "haha", "wkwk", "wkwkwk", "ngakak", "receh"],
    "personal":       ["today", "morning", "night", "feel", "feeling", "life", "day", "week",
                       "love", "miss", "grateful", "tired", "happy", "sad", "excited",
                       "hari ini", "pagi", "malam", "rasanya", "ngerasa", "kangen", "senang"],
    "travel":         ["travel", "trip", "visit", "city", "country", "vacation", "hotel",
                       "flight", "airport", "beach", "mountain", "explore",
                       "liburan", "perjalanan", "wisata", "jalan-jalan"],
    "kuliner":        ["food", "eat", "restaurant", "cafe", "coffee", "dinner", "lunch",
                       "breakfast", "recipe", "cook", "taste", "delicious",
                       "makan", "makanan", "restoran", "kopi", "enak", "lezat"],
}

# Mood mapping berdasarkan topik + sentimen
_MOOD_MAP: Dict[str, str] = {
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
    "berita_terkini": "informatif, urgent, faktual",
    "humor_meme":     "lucu, ringan, relatable",
    "personal":       "personal, reflektif, autentik",
    "travel":         "adventurous, eksploratif, refreshing",
    "kuliner":        "nikmat, apresiatif, ekspresif",
}

# Objects / elemen konten per topik
_OBJECTS_MAP: Dict[str, str] = {
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
    "berita_terkini": "peristiwa, fakta, konfirmasi, sumber berita",
    "humor_meme":     "meme, lelucon, situasi lucu, referensi budaya pop",
    "personal":       "pengalaman sehari-hari, perasaan, momen pribadi",
    "travel":         "destinasi, suasana tempat, pengalaman perjalanan",
    "kuliner":        "makanan, minuman, suasana tempat makan",
}

# Activity per topik
_ACTIVITY_MAP: Dict[str, str] = {
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
    "berita_terkini": "berbagi atau merespons berita terkini",
    "humor_meme":     "berbagi humor dan konten ringan",
    "personal":       "berbagi momen dan perasaan pribadi",
    "travel":         "berbagi pengalaman perjalanan",
    "kuliner":        "berbagi pengalaman kuliner",
}


def _detect_topic(text: str, hashtags: List[str]) -> Tuple[str, str, str, str]:
    """Return (topic, mood, objects, activity)."""
    all_lower = (text + " " + " ".join(hashtags)).lower()
    scores: Dict[str, int] = {}
    for topic, keywords in _TWITTER_TOPICS.items():
        hits = sum(1 for kw in keywords if kw in all_lower)
        if hits:
            scores[topic] = hits
    if scores:
        top = max(scores, key=lambda k: scores[k])
        return (
            top,
            _MOOD_MAP.get(top, "ekspresif, informatif"),
            _OBJECTS_MAP.get(top, "konten teks, opini, informasi"),
            _ACTIVITY_MAP.get(top, "berbagi informasi atau opini"),
        )
    # Fallback
    return "umum", "ekspresif, natural", "teks, opini", "berbagi pemikiran"


def _engagement_level(likes: int, retweets: int, replies: int, views: int) -> str:
    total = likes + (retweets * 2) + (replies * 3) + (views // 1000 if views else 0)
    if total >= 100_000:
        return "SANGAT TINGGI"
    if total >= 10_000:
        return "TINGGI"
    if total >= 1_000:
        return "SEDANG"
    return "RENDAH"


def _gen_ai_description(
    text: str,
    tweet_type: str,       # "POST" / "REPLY" / "RETWEET" / "QUOTE"
    topic: str,
    mood: str,
    hashtags: List[str],
    mentions: List[str],
    metrics: Dict[str, int],
    created_at: str,
    lang: str,
    reply_to: str = "",
    original_author: str = "",
    original_text: str = "",
    media_type: str = "text",
) -> str:
    """
    Generate ai_description yang SANGAT DETAIL dan deskriptif.
    Menjelaskan isi tweet, nada, makna, konteks, dan dampaknya.
    """
    clean_text = re.sub(r"https?://\S+", "", text).strip()
    clean_text = re.sub(r"\s+", " ", clean_text).strip()
    word_count = len(clean_text.split())

    likes     = metrics.get("likes", 0)
    retweets  = metrics.get("retweets", 0)
    replies   = metrics.get("replies", 0)
    views     = metrics.get("views", 0)
    quotes    = metrics.get("quotes", 0)
    bookmarks = metrics.get("bookmarks", 0)

    eng_level = _engagement_level(likes, retweets, replies, views)
    lang_str  = "Bahasa Indonesia" if lang in ("id", "in") else ("Bahasa Inggris" if lang == "en" else f"bahasa {lang or 'tidak diketahui'}")

    parts: List[str] = []

    # ── 1. Pembuka berdasarkan tipe tweet ──────────────────────────────────
    if tweet_type == "RETWEET":
        parts.append(
            f"Ini adalah RETWEET dari tweet milik @{original_author}. "
            f"Dengan me-retweet konten ini, pengguna secara eksplisit menyetujui "
            f"dan ingin menyebarluaskan pesan berikut kepada follower-nya. "
            f"Tindakan retweet menunjukkan keselarasan nilai atau kepentingan terhadap topik yang diangkat."
        )
        if original_text:
            clean_orig = re.sub(r"https?://\S+", "", original_text).strip()
            parts.append(f'Konten yang di-retweet berbunyi: "{clean_orig[:300]}".')
    elif tweet_type == "QUOTE":
        parts.append(
            f"Ini adalah QUOTE TWEET — pengguna mengutip tweet "
            f"{'dari @' + original_author if original_author else 'orang lain'} "
            f"sambil menambahkan komentar atau perspektif pribadinya. "
            f"Berbeda dengan retweet pasif, quote tweet menunjukkan bahwa pengguna "
            f"punya sesuatu yang ingin disampaikan terkait konten yang dikutip."
        )
        if clean_text:
            parts.append(f'Komentar yang ditambahkan pengguna: "{clean_text[:300]}".')
        if original_text:
            clean_orig = re.sub(r"https?://\S+", "", original_text).strip()
            parts.append(f'Tweet yang dikutip: "{clean_orig[:200]}".')
    elif tweet_type == "REPLY":
        reply_ctx = f"membalas @{reply_to}" if reply_to else "membalas tweet orang lain"
        parts.append(
            f"Ini adalah REPLY — pengguna sedang {reply_ctx}. "
            f"Reply menunjukkan keterlibatan aktif dalam percakapan, "
            f"baik sebagai respons terhadap pertanyaan, argumen, dukungan, "
            f"maupun koreksi terhadap konten yang dibalas."
        )
        if clean_text:
            parts.append(f'Isi balasan: "{clean_text[:300]}".')
    else:  # POST original
        parts.append(
            f"Ini adalah TWEET ORIGINAL — konten orisinal yang dibuat dan diterbitkan "
            f"langsung oleh pengguna, mencerminkan pikiran, opini, atau informasi "
            f"yang ingin dibagikan kepada audiens."
        )
        if clean_text:
            if word_count >= 20:
                parts.append(f'Pesan lengkap: "{clean_text[:500]}".')
            elif word_count >= 5:
                parts.append(f'Tweet berbunyi: "{clean_text}".')
            else:
                parts.append(f'Tweet singkat: "{clean_text}".')

    # ── 2. Analisis topik & konteks ────────────────────────────────────────
    _topic_context = {
        "teknologi_ai":   "terkait perkembangan kecerdasan buatan (AI) dan dampaknya",
        "teknologi_umum": "membahas teknologi, inovasi, atau industri tech",
        "politik":        "menyentuh ranah politik, kebijakan, atau isu kenegaraan",
        "bisnis_ekonomi": "berkaitan dengan bisnis, ekonomi, atau pasar keuangan",
        "olahraga":       "berhubungan dengan olahraga atau kompetisi",
        "hiburan":        "berisi konten hiburan, meme, atau referensi budaya pop",
        "sains_alam":     "membahas sains, lingkungan, atau fenomena alam",
        "sosial_budaya":  "menyentuh isu sosial atau nilai budaya",
        "motivasi":       "mengandung pesan motivasi atau inspirasi",
        "opini_kritik":   "mengekspresikan opini kritis atau hot take",
        "berita_terkini": "berisi atau merespons berita dan informasi terkini",
        "humor_meme":     "bersifat humoristis dengan referensi internet culture",
        "personal":       "berbagi pengalaman atau perasaan yang bersifat personal",
        "travel":         "berkaitan dengan perjalanan atau eksplorasi tempat",
        "kuliner":        "membahas makanan, minuman, atau pengalaman kuliner",
    }
    ctx = _topic_context.get(topic, "bersifat informatif atau ekspresif")
    parts.append(f"Konten ini {ctx}, dengan topik utama terdeteksi sebagai '{topic}'.")

    # ── 3. Nada & gaya bahasa ──────────────────────────────────────────────
    parts.append(
        f"Suasana (mood) konten: {mood}. "
        f"Ditulis dalam {lang_str} dengan "
        f"{'gaya panjang dan elaboratif' if word_count >= 30 else 'gaya singkat dan padat' if word_count <= 5 else 'gaya kasual dan ekspresif'}."
    )

    # ── 4. Elemen konten ──────────────────────────────────────────────────
    if media_type != "text":
        media_label = {"image": "gambar/foto", "video": "video", "gif": "GIF animasi"}.get(media_type, media_type)
        parts.append(f"Tweet ini menyertakan {media_label} yang memperkuat pesan teks.")
    if hashtags:
        parts.append(
            f"Hashtag yang digunakan ({', '.join('#' + h for h in hashtags[:8])}) "
            f"menunjukkan konteks dan komunitas yang dituju pengguna."
        )
    if mentions:
        parts.append(
            f"Pengguna menyebut akun {', '.join('@' + m for m in mentions[:5])}, "
            f"menandakan interaksi atau referensi terhadap pihak tertentu."
        )

    # ── 5. Interpretasi makna & konteks ───────────────────────────────────
    if tweet_type == "POST":
        if topic == "opini_kritik":
            parts.append(
                "Dari sudut pandang perilaku digital, tweet opini seperti ini mencerminkan "
                "keinginan pengguna untuk mempengaruhi narasi publik atau mendapatkan validasi "
                "dari komunitas atas pandangannya."
            )
        elif topic in ("teknologi_ai", "teknologi_umum"):
            parts.append(
                "Tweet bertemakan teknologi ini menunjukkan bahwa pengguna aktif mengikuti "
                "perkembangan industri tech, kemungkinan memiliki latar belakang atau ketertarikan "
                "profesional di bidang tersebut."
            )
        elif topic == "motivasi":
            parts.append(
                "Konten motivasional seperti ini sering digunakan untuk membangun personal branding "
                "sebagai sosok inspiratif, atau sekadar mengekspresikan optimisme dan dorongan "
                "yang tulus kepada audiens."
            )
        elif topic == "humor_meme":
            parts.append(
                "Tweet humor/meme ini menunjukkan pengguna aktif di internet culture "
                "dan ingin menciptakan koneksi dengan audiens melalui tawa dan referensi yang relatable."
            )
        elif topic == "personal":
            parts.append(
                "Cuitan personal ini memperlihatkan sisi autentik pengguna — "
                "keinginan untuk berbagi momen atau perasaan secara terbuka, "
                "membangun kedekatan dengan follower melalui kejujuran."
            )

    elif tweet_type == "REPLY":
        parts.append(
            "Reply ini merupakan bukti bahwa pengguna aktif terlibat dalam percakapan "
            "dan tidak hanya menjadi 'silent observer'. Frekuensi reply menggambarkan "
            "tingkat sosialisasi digital dan kecenderungan untuk berinteraksi langsung."
        )

    # ── 6. Konteks engagement ──────────────────────────────────────────────
    if eng_level == "SANGAT TINGGI":
        parts.append(
            f"Engagement tweet ini SANGAT TINGGI dengan {likes:,} likes, "
            f"{retweets:,} retweets, dan {replies:,} replies"
            + (f" dari {views:,} views" if views else "")
            + f". Ini menandakan konten ini resonan kuat dengan audiens luas "
            f"dan berpotensi viral atau sudah viral."
        )
    elif eng_level == "TINGGI":
        parts.append(
            f"Tweet ini mendapat engagement tinggi: {likes:,} likes, "
            f"{retweets:,} retweets, {replies:,} replies"
            + (f" ({views:,} views)" if views else "")
            + ". Konten ini cukup populer di kalangan audiens."
        )
    elif eng_level == "SEDANG":
        parts.append(
            f"Engagement sedang: {likes:,} likes, {retweets:,} retweets, "
            f"{replies:,} replies — performa normal untuk akun ini."
        )
    else:
        if likes > 0 or retweets > 0:
            parts.append(
                f"Engagement rendah: {likes:,} likes, {retweets:,} retweets. "
                f"Tweet ini belum mendapat banyak perhatian dari audiens."
            )
    if bookmarks > 0:
        parts.append(
            f"Tweet ini di-bookmark sebanyak {bookmarks:,} kali, "
            f"menandakan audiens menganggap konten ini bernilai untuk disimpan."
        )
    if quotes > 0:
        parts.append(
            f"Sebanyak {quotes:,} akun mengutip tweet ini dengan komentar mereka sendiri, "
            f"menunjukkan tweet ini memicu diskusi lebih lanjut."
        )

    # ── 7. Tanggal konteks ──────────────────────────────────────────────────
    if created_at:
        parts.append(f"Tweet ini diterbitkan pada {created_at}.")

    return " ".join(parts)


# ─────────────────────────────────────────────────────────────────────────────
# MEDIA + ENTITIES PARSERS
# ─────────────────────────────────────────────────────────────────────────────
def _parse_media(media_raw: Any) -> Dict[str, Any]:
    urls = media_raw if isinstance(media_raw, list) else []
    image_url = video_url = gif_url = ""
    all_media: List[Dict] = []
    for m in urls:
        # Support both string URL and dict {url, type} from apidojo
        if isinstance(m, dict):
            ms  = _safe_str(m.get("url") or m.get("mediaUrl") or m.get("src") or "")
            mtp = _safe_str(m.get("type") or m.get("mediaType") or "").lower()
        else:
            ms  = _safe_str(m)
            mtp = ""
        if not ms:
            continue
        ml = ms.lower()
        # Determine type from dict field first, then URL patterns
        if mtp in ("video", "animated_gif"):
            mtype = "gif" if mtp == "animated_gif" else "video"
        elif any(x in ml for x in (".mp4", ".m3u8", "video", "ext_tw_video", "amplify_video")):
            mtype = "video"
        elif ".gif" in ml or "tweet_video" in ml or "animated" in ml:
            mtype = "gif"
        else:
            mtype = "image"
        if mtype == "video":   video_url = video_url or ms
        elif mtype == "gif":   gif_url   = gif_url   or ms
        else:                  image_url = image_url or ms
        all_media.append({"url": ms, "type": mtype})
    return {
        "image_url": image_url, "video_url": video_url,
        "gif_url": gif_url, "all_media": all_media,
        "media_type": ("video" if video_url else "gif" if gif_url
                       else "image" if image_url else "text"),
    }


def _extract_entities(item: Dict) -> Dict[str, List[str]]:
    entities = item.get("entities") or {}
    text = _safe_str(item.get("fullText") or item.get("text"))
    # Hashtags
    raw_tags = entities.get("hashtags") or []
    if raw_tags and isinstance(raw_tags[0], dict):
        hashtags = [_safe_str(h.get("text") or h.get("tag") or "") for h in raw_tags]
    elif raw_tags:
        hashtags = [_safe_str(h) for h in raw_tags]
    else:
        hashtags = re.findall(r"#(\w+)", text)
    # Mentions
    raw_men = entities.get("user_mentions") or []
    if raw_men and isinstance(raw_men[0], dict):
        mentions = [_safe_str(m.get("screen_name") or m.get("username") or "") for m in raw_men]
    elif raw_men:
        mentions = [_safe_str(m) for m in raw_men]
    else:
        mentions = re.findall(r"@(\w+)", text)
    # URLs
    raw_urls = entities.get("urls") or []
    urls = []
    for u in raw_urls:
        if isinstance(u, dict):
            exp = _safe_str(u.get("expanded_url") or u.get("url"))
            if exp and "t.co" not in exp:
                urls.append(exp)
        elif isinstance(u, str) and "t.co" not in u:
            urls.append(u)
    if not urls:
        urls = [u for u in re.findall(r"https?://\S+", text) if "t.co" not in u]
    return {
        "hashtags": [h for h in hashtags if h],
        "mentions": [m for m in mentions if m],
        "urls": urls,
    }


# ─────────────────────────────────────────────────────────────────────────────
# SYNC SCRAPER
# ─────────────────────────────────────────────────────────────────────────────
# Field mapping terkonfirmasi dari apidojo/twitter-profile-scraper docs:
#   item root  : id, url, twitterUrl, text, fullText, type, isReply,
#                likeCount, retweetCount, replyCount, quoteCount,
#                viewCount, bookmarkCount, createdAt, lang, source,
#                conversationId, inReplyToStatusId, media[], entities{}
#   author     : userName, name, id, isVerified, isBlueVerified,
#                profilePicture, description, followers, following
#   author.about (hanya jika getAboutData=True):
#                accountCreatedAt, accountBasedIn, locationAccurate,
#                avatarUrl, verifiedSince
#
# Free tier cap: 10 item per run
# Strategy cascade: Actor1 (apidojo) → Actor2 (crawlerbros) → Actor3 (clockworks search)
# ─────────────────────────────────────────────────────────────────────────────


def _extract_profile_from_items(items: List[Dict], clean: str) -> Dict:
    """
    Ekstrak data profile dari array tweet items.
    apidojo: author block ada di setiap item.
    Cari item pertama yang author.userName == target.
    Fallback ke item[0] kalau tidak ketemu.
    """
    target_lower = clean.lower()
    author: Dict = {}

    # Cari item milik target (bukan reply dari orang lain)
    for it in items:
        a = it.get("author") or {}
        uname = _safe_str(a.get("userName") or a.get("username") or "").lower()
        if uname == target_lower:
            author = a
            break

    # Fallback ke item pertama
    if not author and items:
        author = items[0].get("author") or {}

    # about block hanya ada kalau getAboutData=True
    about = author.get("about") or {}

    return {
        "user_id":      _safe_str(author.get("id") or author.get("userId") or ""),
        "full_name":    _safe_str(author.get("name") or clean),
        "bio":          _safe_str(author.get("description") or author.get("bio") or ""),
        "followers":    _safe_int(author.get("followers") or author.get("followersCount") or 0),
        "following":    _safe_int(author.get("following") or author.get("friendsCount") or 0),
        "verified":     bool(
            author.get("isBlueVerified") or author.get("isVerified") or
            author.get("verified") or False
        ),
        "profile_pic":  _safe_str(
            author.get("profilePicture") or author.get("profile_image_url") or
            author.get("profilePicUrl") or ""
        ),
        "banner_image": _safe_str(
            author.get("profileBanner") or author.get("profile_banner_url") or
            author.get("bannerUrl") or ""
        ),
        "join_date":    _parse_date(
            about.get("accountCreatedAt") or author.get("created_at") or
            author.get("accountCreatedAt") or ""
        ),
        "location":     _safe_str(
            about.get("accountBasedIn") or author.get("location") or
            about.get("location") or ""
        ),
        "website":      _safe_str(
            author.get("url") or author.get("website") or
            author.get("entities_url") or ""
        ),
        "tweet_count":  _safe_int(
            author.get("statusesCount") or author.get("tweetsCount") or
            author.get("tweet_count") or 0
        ),
    }


def _normalise_item(tw: Dict, clean: str) -> Dict:
    """
    Normalise satu raw tweet item dari actor apapun ke schema internal.
    Dipanggil setelah inject author block, sebelum _parse_tweet_item.
    """
    # id
    tw.setdefault("id", tw.get("tweetId") or tw.get("tweet_id") or "")
    # text
    tw.setdefault("fullText", tw.get("full_text") or tw.get("tweet_text") or tw.get("text") or "")
    # metrics
    tw.setdefault("likeCount",     tw.get("likes")     or tw.get("favorite_count")  or 0)
    tw.setdefault("retweetCount",  tw.get("retweets")  or tw.get("retweet_count")   or 0)
    tw.setdefault("replyCount",    tw.get("replies")   or tw.get("reply_count")     or 0)
    tw.setdefault("quoteCount",    tw.get("quotes")    or tw.get("quote_count")     or 0)
    tw.setdefault("viewCount",     tw.get("views")     or tw.get("view_count")      or 0)
    tw.setdefault("bookmarkCount", tw.get("bookmarks") or tw.get("bookmark_count")  or 0)
    # meta
    tw.setdefault("createdAt", tw.get("created_at") or "")
    tw.setdefault("lang",      tw.get("language")   or "")
    # type flags — support both camelCase (apidojo) dan snake_case (cryptosignals)
    # Prioritas: kalau snake_case True → override camelCase
    _cs_rt = bool(tw.get("is_retweet"))
    _cs_rp = bool(tw.get("is_reply"))
    _cs_qt = bool(tw.get("is_quote"))
    # Set camelCase — kalau snake_case True, paksa override
    if _cs_rt:
        tw["isRetweet"] = True
    elif "isRetweet" not in tw:
        tw["isRetweet"] = False
    if _cs_rp:
        tw["isReply"] = True
    elif "isReply" not in tw:
        tw["isReply"] = False
    if _cs_qt:
        tw["isQuote"] = True
    elif "isQuote" not in tw:
        tw["isQuote"] = False
    # apidojo reply fields — inReplyToUsername → inReplyToUser
    if tw.get("inReplyToUsername") and not tw.get("inReplyToUser"):
        tw["inReplyToUser"] = tw["inReplyToUsername"]
    # reply metadata — cryptosignals uses snake_case field names
    _irt_id = (tw.get("inReplyToStatusId") or
               tw.get("in_reply_to_tweet_id") or
               tw.get("in_reply_to_status_id") or
               tw.get("inReplyToId") or
               tw.get("in_reply_to_user_id") or "")
    # JANGAN pakai conversation_id untuk deteksi reply —
    # cryptosignals mengisi conv_id = tweet pertama thread, bukan tweet yang di-reply
    if _irt_id:
        tw["inReplyToStatusId"] = str(_irt_id)
        tw["isReply"] = True
    _irt_user = (tw.get("inReplyToUser") or
                 tw.get("in_reply_to_handle") or        # cryptosignals field
                 tw.get("in_reply_to_username") or
                 tw.get("in_reply_to_screen_name") or
                 tw.get("in_reply_to_user") or "")
    if _irt_user:
        tw["inReplyToUser"] = _irt_user
    # quote metadata
    _qt_id  = tw.get("quoted_tweet_id") or ""
    _qt_txt = tw.get("quoted_tweet_text") or ""
    _qt_url = (tw.get("quotedTweetUrl") or tw.get("quoted_tweet_url") or
               (f"https://x.com/i/status/{_qt_id}" if _qt_id else ""))
    if _qt_url:
        tw["quotedTweetUrl"] = _qt_url
    if _qt_txt and not tw.get("quotedTweet"):
        tw["quotedTweet"] = {"fullText": _qt_txt, "author": {}}
    # media
    if tw.get("media_urls") and not tw.get("media"):
        tw["media"] = tw["media_urls"]
    return tw


def _parse_tweet_item(
    item: Dict,
    clean: str,
    clean_lower: str,
) -> Optional[Dict]:
    """
    Parse satu raw item dari actor output ke format internal.
    Return None kalau item tidak valid (tidak ada id/text).
    Kompatibel dengan output schema apidojo, crawlerbros, clockworks.
    """
    item_id = _safe_str(
        item.get("id") or item.get("tweetId") or item.get("tweet_id") or ""
    )
    if not item_id:
        return None

    # ── Teks tweet ────────────────────────────────────────────────────────
    text = _safe_str(
        item.get("fullText") or item.get("full_text") or
        item.get("text") or item.get("content") or ""
    )
    if not text:
        return None

    # ── Metrics — apidojo pakai camelCase *Count ──────────────────────────
    likes      = _safe_int(item.get("likeCount")     or item.get("likes")      or item.get("favorite_count") or 0)
    retweets_n = _safe_int(item.get("retweetCount")  or item.get("retweets")   or item.get("retweet_count")  or 0)
    replies_n  = _safe_int(item.get("replyCount")    or item.get("replies")    or item.get("reply_count")    or 0)
    quotes_n   = _safe_int(item.get("quoteCount")    or item.get("quotes")     or item.get("quote_count")    or 0)
    bookmarks  = _safe_int(item.get("bookmarkCount") or item.get("bookmarks")  or item.get("bookmark_count") or 0)
    views      = _safe_int(item.get("viewCount")     or item.get("views")      or item.get("view_count")     or 0)

    # ── Meta ──────────────────────────────────────────────────────────────
    created_at = _parse_date(item.get("createdAt") or item.get("created_at") or "")
    lang       = _safe_str(item.get("lang") or item.get("language") or "")
    source     = _safe_str(item.get("source") or "")
    conv_id    = _safe_str(item.get("conversationId") or item.get("conversation_id") or "")

    tweet_url = _safe_str(
        item.get("url") or item.get("twitterUrl") or item.get("tweet_url") or
        f"https://x.com/{clean}/status/{item_id}"
    )

    # ── Author handle dari item (untuk filter reply dari orang lain) ──────
    item_author = item.get("author") or {}
    item_handle = _safe_str(
        item_author.get("userName") or item_author.get("username") or
        item.get("user_handle") or item.get("screen_name") or ""
    ).lower().lstrip("@")

    # ── Media + Entities ──────────────────────────────────────────────────
    media_raw  = item.get("media") or item.get("media_urls") or item.get("mediaUrls") or []
    media_info = _parse_media(media_raw)
    ents       = _extract_entities(item)
    hashtags   = ents["hashtags"]
    mentions   = ents["mentions"]
    urls_list  = ents["urls"]

    # ── Reply / quote references ──────────────────────────────────────────
    in_reply_to_id = _safe_str(
        item.get("inReplyToStatusId") or item.get("in_reply_to_status_id") or
        item.get("in_reply_to_tweet_id") or item.get("inReplyToId") or ""
    )
    irt_raw = (item.get("inReplyToUser") or item.get("in_reply_to_user") or
               item.get("in_reply_to_handle") or item.get("in_reply_to_screen_name") or
               item.get("inReplyToUsername") or "")   # apidojo field!
    if isinstance(irt_raw, dict):
        in_reply_to_user = _safe_str(
            irt_raw.get("userName") or irt_raw.get("username") or ""
        )
    else:
        in_reply_to_user = _safe_str(
            irt_raw or item.get("in_reply_to_screen_name") or ""
        )

    referenced_url = _safe_str(
        item.get("quotedTweetUrl") or item.get("quoted_tweet_url") or
        item.get("referenced_tweet_url") or item.get("quoteTweetUrl") or
        # cryptosignals: build URL dari quoted_tweet_id
        (f"https://x.com/i/status/{item.get('quoted_tweet_id')}" if item.get("quoted_tweet_id") else "") or ""
    )

    # ── Tipe tweet ────────────────────────────────────────────────────────
    item_type = _safe_str(item.get("type") or "").lower()
    text_up   = (text or "").strip()

    # Precompute reply signals
    _has_irt = bool(
        item.get("inReplyToStatusId") or item.get("in_reply_to_tweet_id") or
        item.get("in_reply_to_status_id") or item.get("inReplyToId") or
        item.get("in_reply_to_user_id")
    )
    _has_reply_flag = bool(item.get("isReply") or item.get("is_reply"))
    # Teks dimulai "@handle " (bukan RT @) → reply
    _text_at_mention = bool(
        text_up.startswith("@") and
        not text_up.startswith("RT @") and
        len(text_up.split()) > 1
    )
    # CATATAN: conversation_id != tweet_id TIDAK reliable untuk deteksi reply
    # karena cryptosignals mengisi conversation_id = ID tweet pertama dalam thread
    # untuk semua tweet dalam thread (termasuk tweet original si user sendiri)

    # 1. RETWEET
    if text_up.startswith("RT @") or item_type == "retweet" or bool(item.get("isRetweet") or item.get("is_retweet")):
        tweet_type = "RETWEET"
    # 2. REPLY
    elif (_has_irt or _has_reply_flag or _text_at_mention or
          item_type in ("reply", "tweet_reply")):
        tweet_type = "REPLY"
    # 3. QUOTE
    elif (bool(item.get("isQuote") or item.get("is_quote")) or
          bool(item.get("quotedTweetUrl") or item.get("quoted_tweet_id")) or
          item_type == "quote"):
        tweet_type = "QUOTE"
    # 4. POST — default
    else:
        tweet_type = "POST"

    is_retweet = (tweet_type == "RETWEET")
    is_reply   = (tweet_type == "REPLY")
    is_quote   = (tweet_type == "QUOTE")

    # ── Content analysis ──────────────────────────────────────────────────
    topic, mood, objects, activity = _detect_topic(text, hashtags)
    eng_level = _engagement_level(likes, retweets_n, replies_n, views)

    clean_text_short = re.sub(r"https?://\S+", "", text).strip()
    clean_text_short = re.sub(r"[#@]\w+", "", clean_text_short).strip()
    clean_text_short = re.sub(r"\s+", " ", clean_text_short).strip()

    # Ekstrak original author + text untuk RT/QT
    orig_author = orig_text = ""
    if tweet_type == "RETWEET":
        # apidojo: retweetedTweet block berisi tweet asli
        rt_block = item.get("retweetedTweet") or {}
        if rt_block:
            orig_author = _safe_str((rt_block.get("author") or {}).get("userName") or "")
            orig_text   = _safe_str(rt_block.get("fullText") or rt_block.get("text") or "")
        if not orig_author:
            # Fallback: parse dari "RT @username: ..." format
            rt_m = re.match(r"RT @(\w+):\s*", text)
            orig_author = rt_m.group(1) if rt_m else ""
            orig_text   = orig_text or re.sub(r"^RT @\w+:\s*", "", text).strip()
    elif tweet_type == "QUOTE":
        qt = item.get("quotedTweet") or {}
        orig_author = _safe_str((qt.get("author") or {}).get("userName") or "")
        orig_text   = _safe_str(
            qt.get("fullText") or qt.get("text") or
            item.get("quoted_tweet_text") or ""   # cryptosignals field
        )

    metrics_dict = {
        "likes": likes, "retweets": retweets_n, "replies": replies_n,
        "quotes": quotes_n, "bookmarks": bookmarks, "views": views,
    }

    ai_desc = _gen_ai_description(
        text=text, tweet_type=tweet_type, topic=topic, mood=mood,
        hashtags=hashtags, mentions=mentions, metrics=metrics_dict,
        created_at=created_at, lang=lang,
        reply_to=in_reply_to_user, original_author=orig_author,
        original_text=orig_text, media_type=media_info["media_type"],
    )

    content_analysis = {
        "topic":            topic,
        "mood":             mood,
        "objects":          objects,
        "activity":         activity,
        "content_summary":  clean_text_short[:200] if clean_text_short else (hashtags[0] if hashtags else ""),
        "ai_description":   ai_desc,
        "key_themes":       [topic] + hashtags[:3],
        "engagement_level": eng_level,
    }

    base = {
        "id":              item_id,
        "post_id":         item_id,
        "content":         text,
        "tweet_url":       tweet_url,
        "post_url":        tweet_url,
        "conversation_id": conv_id,
        "created_at":      created_at,
        "lang":            lang,
        "source":          source,
        "likes":           likes,
        "comments":        replies_n,
        "shares":          retweets_n,
        "plays":           views,
        "quotes":          quotes_n,
        "bookmarks":       bookmarks,
        "image_url":       media_info["image_url"],
        "video_url":       media_info["video_url"],
        "gif_url":         media_info["gif_url"],
        "cover_url":       media_info["image_url"] or media_info["video_url"],
        "all_media":       media_info["all_media"],
        "media_type":      media_info["media_type"],
        "duration_sec":    0,
        "hashtags":        hashtags,
        "mentions":        mentions,
        "urls":            urls_list,
        "is_reply":        is_reply,
        "is_repost":       is_retweet,
        "is_quote":        is_quote,
        "tweet_type":      tweet_type,
        "action_type":     tweet_type,
        "referenced_tweet_url": referenced_url,
        "in_reply_to_user":     in_reply_to_user,
        "in_reply_to_id":       in_reply_to_id,
        "item_handle":          item_handle,
        "orig_author":          orig_author,
        "orig_text":            orig_text[:300],
        "sentiment":            {"label": "NEUTRAL", "score": 0.5},
        "content_analysis":     content_analysis,
        "comments_data":        [],
        "music":                {"title": "", "author": ""},
        "visual_description":   ai_desc,
        "topic":                topic,
        "mood":                 mood,
        "objects":              objects,
        "activity":             activity,
        "metrics_dict":         metrics_dict,
    }
    return base


def _twitter_scrape_sync(username: str, apify_token: str) -> Dict:
    """
    3-actor cascade untuk X/Twitter scraping di Apify free plan.

    Actor 1 — apidojo/twitter-profile-scraper  (primary, confirmed field schema)
      Input : twitterHandles, maxItems, includeNativeRetweets, getAboutData
      Limit : free plan max 10 item/run
      Output: fullText, likeCount, retweetCount, replyCount, quoteCount,
              viewCount, bookmarkCount, createdAt, lang, isReply, type,
              conversationId, inReplyToStatusId, media[], entities{},
              author.{userName,name,id,isBlueVerified,profilePicture,
                      description,followers,following,about}

    Actor 2 — crawlerbros/twitter-profile-scraper  (fallback jika Actor1 < 3 tweet)
      Input : username, maxTweets, includeReplies, proxyConfiguration
      Schema mirip apidojo tapi beberapa field berbeda nama

    Actor 3 — clockworks/tweet-scraper  (last resort via search query)
      Input : searchTerms ["from:username"], maxItems, addUserInfo
      Paling stabil karena pakai search endpoint bukan profile endpoint
    """
    import os
    from dotenv import load_dotenv
    load_dotenv()

    if not apify_token:
        apify_token = os.getenv("APIFY_TOKEN", "")
    if not apify_token:
        return _build_empty(username, "APIFY_TOKEN tidak ditemukan di .env")
    try:
        from apify_client import ApifyClient
    except ImportError:
        return _build_empty(username, "apify_client tidak terinstall — pip install apify-client")

    clean       = username.replace("@", "").strip()
    clean_lower = clean.lower()
    print(f"\n{'='*60}")
    print(f"📡 [X/Twitter v6.0] Scraping @{clean}")
    print(f"{'='*60}")

    client       = ApifyClient(apify_token)
    items:         List[Dict] = []
    actor_used   = ""
    scrape_errors: List[str] = []

    # ── ACTOR 1: cryptosignals/twitter-scraper — posts + replies + quotes + retweets ──
    print(f"\n[1/4] cryptosignals/twitter-scraper (posts+replies)...")
    try:
        r1 = client.actor("cryptosignals/twitter-scraper").call(run_input={
            "username":   clean,
            "action":     "both",
            "maxResults": 100,   # 100 = stable, 200 causes timeout
        })
        ds1 = getattr(r1, "default_dataset_id", None)
        if ds1:
            raw1 = client.dataset(ds1).list_items().items or []
            items1_tweets  = [i for i in raw1 if i.get("tweet_text") or i.get("tweet_id")]
            items1_profile = [i for i in raw1 if i.get("followers") is not None
                              and not i.get("tweet_text")]
            print(f"   ↳ {len(raw1)} raw → {len(items1_tweets)} tweets, {len(items1_profile)} profile")

            # Inject author block
            if items1_profile:
                pdata = items1_profile[0]
                for tw in items1_tweets:
                    tw["author"] = {
                        "userName": pdata.get("user_handle") or clean,
                        "name":     pdata.get("user_name")   or clean,
                        "id":       str(pdata.get("user_id") or ""),
                        "isBlueVerified": bool(pdata.get("verified", False)),
                        "profilePicture": pdata.get("profile_image") or "",
                        "description":    pdata.get("bio") or "",
                        "followers":      pdata.get("followers", 0),
                        "following":      pdata.get("following", 0),
                        "about": {
                            "accountCreatedAt": pdata.get("created_at") or "",
                            "accountBasedIn":   pdata.get("location") or "",
                        },
                    }
                    tw["bannerUrl"] = pdata.get("banner_image") or ""
            else:
                for tw in items1_tweets:
                    if not tw.get("author"):
                        tw["author"] = {
                            "userName": tw.get("user_handle") or clean,
                            "name":     tw.get("user_name") or clean,
                            "id":       str(tw.get("user_id") or ""),
                            "isBlueVerified": bool(tw.get("user_verified", False)),
                            "profilePicture": "",
                            "description":    "",
                            "followers":      int(tw.get("user_followers") or 0),
                            "following":      0,
                            "about":          {},
                        }

            # Normalise cryptosignals snake_case → camelCase
            for tw in items1_tweets:
                # Cryptosignals return snake_case flags — set camelCase SEBELUM _normalise_item
                # supaya deteksi di _parse_tweet_item benar
                if tw.get("is_retweet"):  tw["isRetweet"] = True
                if tw.get("is_reply"):    tw["isReply"]   = True
                if tw.get("is_quote"):    tw["isQuote"]   = True
                # cryptosignals juga punya in_reply_to_tweet_id — map ke inReplyToStatusId
                _irt = (tw.get("in_reply_to_tweet_id") or tw.get("in_reply_to_status_id") or
                        tw.get("in_reply_to_id") or "")
                if _irt:
                    tw["inReplyToStatusId"] = str(_irt)
                    tw["isReply"] = True
                _normalise_item(tw, clean)

            if items1_tweets:
                items = items1_tweets
                actor_used = "cryptosignals/twitter-scraper"
    except Exception as e1:
        msg = f"Actor1 (cryptosignals) error: {e1}"
        print(f"   ⚠️  {msg}")
        scrape_errors.append(msg)

    # ══════════════════════════════════════════════════════════════
    # ACTOR 1.5 — Scrape Reposts/Retweets
    # Strategy: cryptosignals action=tweets → filter is_retweet=True
    # Fallback: apidojo/tweet-scraper include:retweets search
    # Note: X native retweet tidak terindeks di search publik,
    #       hanya bisa dapat kalau user memang melakukan RT baru-baru ini.
    # ══════════════════════════════════════════════════════════════
    print(f"\n[1.5/4] Scraping reposts @{clean}...")
    reposts: List[Dict] = []

    def _is_retweet(item: Dict) -> bool:
        if item.get("isRetweet") or item.get("is_retweet"): return True
        if bool(item.get("retweetedTweet")): return True
        if _safe_str(item.get("type") or "").lower() == "retweet": return True
        return _safe_str(item.get("fullText") or item.get("text") or "").startswith("RT @")

    def _build_repost(author, text, url, date, metrics=None):
        return {
            "tweet_url":           url,
            "original_author":     author,
            "original_author_url": f"https://x.com/{author}",
            "original_tweet_url":  url,
            "original_caption":    text[:300],
            "repost_date":         date,
            "created_at":          date,
            "hashtags":            re.findall(r"#(\w+)", text),
            "metrics":             metrics or {"likes": 0, "retweets": 0, "views": 0, "replies": 0},
            "sentiment":           {"label": "NEUTRAL", "score": 0.5},
            "content_analysis":    {},
        }

    def _parse_rt_item(item):
        """Extract repost dari satu raw item — return dict atau None."""
        _tx   = _safe_str(item.get("fullText") or item.get("text") or item.get("tweet_text") or "")
        _dt   = _parse_date(item.get("createdAt") or item.get("created_at") or item.get("date") or "")
        _id   = _safe_str(item.get("id") or item.get("tweet_id") or "")
        _me   = _safe_str((item.get("author") or {}).get("userName") or item.get("user_handle") or clean)
        # Original author dari retweetedTweet block
        _rt_blk  = item.get("retweetedTweet") or item.get("retweeted_status") or {}
        _rt_auth = (_rt_blk.get("author") or _rt_blk.get("user") or {})
        _orig_u  = _safe_str(_rt_auth.get("userName") or _rt_auth.get("screen_name") or
                             item.get("retweeted_user_handle") or item.get("retweeted_user") or "")
        _orig_tx = _safe_str(_rt_blk.get("fullText") or _rt_blk.get("full_text") or _rt_blk.get("text") or "")
        _orig_id = _safe_str(_rt_blk.get("id") or _rt_blk.get("id_str") or "")
        # Fallback: parse "RT @user: text"
        if not _orig_u and _tx.startswith("RT @"):
            import re as _rert
            _m = _rert.match(r'^RT @(\w+):\s*(.*)', _tx, _rert.DOTALL)
            if _m:
                _orig_u  = _m.group(1)
                _orig_tx = _m.group(2)[:300]
        if not _orig_u:
            return None
        _ul      = _safe_str(item.get("twitterUrl") or item.get("tweet_url") or
                             (f"https://x.com/{_me}/status/{_id}" if _id else ""))
        _orig_ul = (f"https://x.com/{_orig_u}/status/{_orig_id}" if _orig_id else
                    f"https://x.com/{_orig_u}")
        _mt = item.get("public_metrics") or {}
        return _build_repost(_orig_u, _orig_tx or _tx[:300], _orig_ul, _dt, {
            "likes":    _safe_int(_mt.get("like_count") or item.get("likeCount") or item.get("likes") or 0),
            "retweets": _safe_int(_mt.get("retweet_count") or item.get("retweetCount") or item.get("retweets") or 0),
            "views":    _safe_int(item.get("viewCount") or item.get("views") or 0),
            "replies":  _safe_int(_mt.get("reply_count") or item.get("replyCount") or item.get("replies") or 0),
        })

    # ── S1: cryptosignals action=tweets → filter is_retweet ──────
    # Ini yang paling stabil karena cryptosignals sudah proven bekerja
    try:
        print(f"   ↳ S1: cryptosignals/twitter-scraper action=tweets...")
        _rs1 = client.actor("cryptosignals/twitter-scraper").call(run_input={
            "username":   clean,
            "action":     "tweets",
            "maxResults": 50,
        })
        _ds1r = getattr(_rs1, "default_dataset_id", None)
        if _ds1r:
            _raw1r    = client.dataset(_ds1r).list_items().items or []
            _tweets1r = [i for i in _raw1r if i.get("tweet_text") or i.get("tweet_id")]
            # Debug: print sample fields dari 3 item pertama untuk tahu struktur retweet
            _all_keys1r = set()
            for _dk in _tweets1r[:3]:
                _all_keys1r.update(_dk.keys())
            _rt_fields = {k: _tweets1r[0].get(k) for k in sorted(_all_keys1r)
                          if any(x in k for x in ("retw","retweet","rt","repost"))} if _tweets1r else {}
            print(f"   ↳ S1: {len(_raw1r)} raw → {len(_tweets1r)} tweets | RT-related keys: {list(_rt_fields.keys())}")
            # Count berapa yang punya is_retweet=True
            _rt_count1r = sum(1 for i in _tweets1r if bool(i.get("is_retweet")))
            _rt_text1r  = sum(1 for i in _tweets1r if (i.get("tweet_text") or "").startswith("RT @"))
            print(f"   ↳ S1 breakdown: is_retweet=True: {_rt_count1r} | starts 'RT @': {_rt_text1r}")
            for _i1r in _tweets1r:
                # Cek is_retweet flag ATAU teks dimulai "RT @"
                _tx1r = _safe_str(_i1r.get("tweet_text") or "")
                _is_rt1r = bool(_i1r.get("is_retweet")) or _tx1r.startswith("RT @")
                if _is_rt1r:
                    # Parse original author dari retweeted_user_handle atau dari teks
                    _orig_u1r = _safe_str(_i1r.get("retweeted_user_handle") or
                                          _i1r.get("retweeted_user") or "")
                    _orig_t1r = ""
                    if not _orig_u1r and _tx1r.startswith("RT @"):
                        import re as _re1r
                        _m1r = _re1r.match(r'^RT @(\w+):\s*(.*)', _tx1r, _re1r.DOTALL)
                        if _m1r:
                            _orig_u1r = _m1r.group(1)
                            _orig_t1r = _m1r.group(2)[:300]
                    _rp = _parse_rt_item({
                        "tweet_text":            _tx1r,
                        "fullText":              _tx1r,
                        "date":                  _i1r.get("date") or "",
                        "tweet_id":              _i1r.get("tweet_id") or "",
                        "user_handle":           _i1r.get("user_handle") or clean,
                        "retweeted_user_handle": _orig_u1r,
                        "retweeted_user":        _orig_u1r,
                        "orig_text":             _orig_t1r,
                        "likes":                 _i1r.get("likes") or 0,
                        "retweets":              _i1r.get("retweets") or 0,
                        "replies":               _i1r.get("replies") or 0,
                    })
                    if _rp:
                        reposts.append(_rp)
            if reposts:
                print(f"   ✅ S1: {len(reposts)} reposts")
            else:
                print(f"   ↳ S1: 0 RT — user tidak melakukan retweet dalam 50 tweet terakhir")
    except Exception as _es1:
        print(f"   ⚠️  S1 error: {str(_es1)[:70]}")

    # ── S2: apidojo/tweet-scraper search include:retweets ────────
    if not reposts:
        try:
            print(f"   ↳ S2: apidojo/tweet-scraper 'from:{clean} include:retweets'...")
            _rs2 = client.actor("apidojo/tweet-scraper").call(run_input={
                "searchTerms": [f"from:{clean} include:retweets"],
                "maxItems":    10,
                "addUserInfo": True,
                "sort":        "Latest",
            })
            _ds2r = getattr(_rs2, "default_dataset_id", None)
            if _ds2r:
                _raw2r = client.dataset(_ds2r).list_items().items or []
                # Detect monthly limit — item pertama hanya punya error key
                if _raw2r and not (_raw2r[0].get("fullText") or _raw2r[0].get("text") or _raw2r[0].get("id")):
                    print(f"   ↳ S2: monthly limit — skip")
                else:
                    _valid2r = [i for i in _raw2r if i.get("fullText") or i.get("text")]
                    print(f"   ↳ S2: {len(_raw2r)} raw → {len(_valid2r)} valid")
                    for _i2r in _valid2r:
                        if _is_retweet(_i2r):
                            _rp2 = _parse_rt_item(_i2r)
                            if _rp2:
                                reposts.append(_rp2)
                    if reposts:
                        print(f"   ✅ S2: {len(reposts)} reposts")
                    else:
                        print(f"   ↳ S2: 0 RT dari {len(_valid2r)} valid items")
        except Exception as _es2:
            print(f"   ⚠️  S2 error: {str(_es2)[:70]}")

    # ── S3: scan items dari Actor 1 untuk RT yang terlewat ───────
    if not reposts:
        for _i3 in items:
            if _is_retweet(_i3):
                _rp3 = _parse_rt_item(_i3)
                if _rp3:
                    reposts.append(_rp3)
        if reposts:
            print(f"   ↳ S3 timeline fallback: {len(reposts)} RT dari Actor 1 items")
        else:
            print(f"   ↳ Reposts: 0 — @{clean} tidak melakukan retweet yang dapat dideteksi")



    def _is_retweet(item: Dict) -> bool:
        if item.get("isRetweet") or item.get("is_retweet"): return True
        if bool(item.get("retweet")) or bool(item.get("retweetedTweet")): return True
        if _safe_str(item.get("type") or "").lower() == "retweet": return True
        return _safe_str(item.get("fullText") or item.get("text") or "").startswith("RT @")

    def _extract_retweets(raw_items: List[Dict]) -> List[Dict]:
        return [i for i in raw_items if _is_retweet(i)]

    def _merge_new_items(new_items: List[Dict], existing: List[Dict]) -> int:
        existing_ids = {_safe_str(x.get("id") or x.get("tweet_id") or "") for x in existing}
        merged = 0
        for item in new_items:
            item_id = _safe_str(item.get("id") or item.get("tweet_id") or "")
            if item_id and item_id not in existing_ids:
                _normalise_item(item, clean)
                existing.append(item)
                existing_ids.add(item_id)
                merged += 1
        return merged

    def _build_repost(author, text, url, date, metrics=None):
        return {
            "tweet_url":           url,
            "original_author":     author,
            "original_author_url": f"https://x.com/{author}",
            "original_tweet_url":  url,
            "original_caption":    text[:300],
            "repost_date":         date,
            "created_at":          date,
            "hashtags":            re.findall(r"#(\w+)", text),
            "metrics":             metrics or {"likes": 0, "retweets": 0, "views": 0, "replies": 0},
            "sentiment":           {"label": "NEUTRAL", "score": 0.5},
            "content_analysis":    {},
        }

    # Gunakan Tweepy langsung, lebih reliable dari Apify yang sering limit
    print(f"\n[2/4] Tweepy Twitter API v2 (replies + retweets)...")
    _bearer = os.getenv("TWITTER_BEARER_TOKEN", "").strip()
    if _bearer:
        try:
            from urllib.parse import unquote as _uq_tw
            import tweepy as _tweepy
            _bearer_dec = _uq_tw(_bearer)
            _tw_cli = _tweepy.Client(bearer_token=_bearer_dec, wait_on_rate_limit=False)
            print(f"   ↳ ✅ Connected to Twitter API v2")

            # Ambil user ID
            _tw_user = _tw_cli.get_user(username=clean)
            if _tw_user.data:
                _tw_uid = _tw_user.data.id
                print(f"   ↳ User ID: {_tw_uid}")

                # Ambil timeline tweets dengan semua field yang dibutuhkan
                _tw_resp = _tw_cli.get_users_tweets(
                    id=_tw_uid,
                    max_results=20,
                    tweet_fields=["referenced_tweets","public_metrics","created_at","lang",
                                  "conversation_id","in_reply_to_user_id","entities"],
                    expansions=["referenced_tweets.id","referenced_tweets.id.author_id",
                                "in_reply_to_user_id","author_id"],
                    user_fields=["username","name","verified","public_metrics"],
                )

                _tw_counts = {"REPLY": 0, "RETWEET": 0, "QUOTE": 0, "POST": 0}
                if _tw_resp.data:
                    # Build user map dari includes
                    _tw_users = {}
                    if _tw_resp.includes and "users" in _tw_resp.includes:
                        for _u in _tw_resp.includes["users"]:
                            _tw_users[str(_u.id)] = getattr(_u, "username", "")

                    # Build referenced tweets map
                    _tw_refs = {}
                    if _tw_resp.includes and "tweets" in _tw_resp.includes:
                        for _rt in _tw_resp.includes["tweets"]:
                            _tw_refs[str(_rt.id)] = {
                                "text": getattr(_rt, "text", ""),
                                "author": _tw_users.get(str(getattr(_rt, "author_id", "")), ""),
                            }

                    for _tw_t in _tw_resp.data:
                        _tx   = _tw_t.text or ""
                        _twid = str(_tw_t.id)
                        _mt   = _tw_t.public_metrics or {}
                        _dt   = str(_tw_t.created_at or "")[:10]

                        # Deteksi tipe tweet
                        _t_reply = False; _t_rt = False; _t_qt = False
                        _ref_id = ""; _ref_author = ""; _ref_text = ""
                        if _tw_t.referenced_tweets:
                            for _ref in _tw_t.referenced_tweets:
                                _ref_sid = str(_ref.id)
                                _ref_info = _tw_refs.get(_ref_sid, {})
                                if _ref.type == "replied_to":
                                    _t_reply = True; _ref_id = _ref_sid
                                elif _ref.type == "retweeted":
                                    _t_rt = True; _ref_id = _ref_sid
                                    _ref_author = _ref_info.get("author", "")
                                    _ref_text   = _ref_info.get("text", "")
                                elif _ref.type == "quoted":
                                    _t_qt = True; _ref_id = _ref_sid
                                    _ref_author = _ref_info.get("author", "")
                                    _ref_text   = _ref_info.get("text", "")

                        # Juga cek text prefix "RT @"
                        if _tx.startswith("RT @") and not _t_rt:
                            _t_rt = True
                            import re as _re_tw
                            _rtm = _re_tw.match(r'^RT @(\w+):\s*(.*)', _tx, _re_tw.DOTALL)
                            if _rtm:
                                _ref_author = _rtm.group(1)
                                _ref_text   = _rtm.group(2)[:300]

                        if _t_rt:
                            _tw_type = "RETWEET"; _tw_counts["RETWEET"] += 1
                        elif _t_reply:
                            _tw_type = "REPLY";   _tw_counts["REPLY"] += 1
                        elif _t_qt:
                            _tw_type = "QUOTE";   _tw_counts["QUOTE"] += 1
                        else:
                            _tw_type = "POST";    _tw_counts["POST"] += 1

                        if _tw_type == "POST":
                            continue  # POST sudah ada dari Actor 1, skip

                        # Build item untuk merge
                        _tw_item = {
                            "id":              _twid,
                            "fullText":        _tx,
                            "text":            _tx,
                            "createdAt":       _dt,
                            "lang":            getattr(_tw_t, "lang", "") or "",
                            "likeCount":       _mt.get("like_count", 0),
                            "retweetCount":    _mt.get("retweet_count", 0),
                            "replyCount":      _mt.get("reply_count", 0),
                            "quoteCount":      _mt.get("quote_count", 0),
                            "isReply":         _t_reply,
                            "isRetweet":       _t_rt,
                            "isQuote":         _t_qt,
                            "inReplyToStatusId": _ref_id if _t_reply else "",
                            "inReplyToUsername": "",
                            "twitterUrl":      f"https://x.com/{clean}/status/{_twid}",
                            "tweet_type":      _tw_type,
                            "action_type":     _tw_type,
                            "author":          {"userName": clean, "name": clean},
                        }
                        # Untuk RT: tambah info original
                        if _t_rt and _ref_author:
                            _tw_item["orig_author"] = _ref_author
                            _tw_item["orig_text"]   = _ref_text[:300]
                        _normalise_item(_tw_item, clean)

                        # Merge ke items
                        _eidx = next((i for i,x in enumerate(items)
                                      if (x.get("id") or x.get("tweetId") or "") == _twid), None)
                        if _eidx is not None:
                            cur_t = (items[_eidx].get("tweet_type") or "POST").upper()
                            if cur_t == "POST" and _tw_type != "POST":
                                items[_eidx].update({
                                    "tweet_type":        _tw_type,
                                    "action_type":       _tw_type,
                                    "isReply":           _t_reply,
                                    "isRetweet":         _t_rt,
                                    "isQuote":           _t_qt,
                                    "inReplyToStatusId": _ref_id if _t_reply else "",
                                })
                                if _t_rt and _ref_author:
                                    items[_eidx]["orig_author"] = _ref_author
                                    items[_eidx]["orig_text"]   = _ref_text[:300]
                                print(f"   ↳ [tweepy] Update {_twid[:12]}: POST → {_tw_type}")
                        else:
                            items.append(_tw_item)

                    print(f"   ↳ ✅ Tweepy breakdown: {_tw_counts} | total items: {len(items)}")
                else:
                    print(f"   ↳ ⚠️  Tweepy: tidak ada data tweets")
            else:
                print(f"   ↳ ⚠️  Tweepy: user @{clean} tidak ditemukan")
        except Exception as _etw_all:
            print(f"   ⚠️  Tweepy error: {_etw_all}")
            scrape_errors.append(f"Tweepy error: {_etw_all}")
    else:
        print(f"   ⚠️  TWITTER_BEARER_TOKEN tidak ada di .env — skip Tweepy")

    # ── ACTOR 3: apidojo/twitter-profile-scraper — replies + reposts ────────
    # Pakai apidojo/twitter-profile-scraper yang proven bekerja dengan includeNativeRetweets
    _cur_replies = [i for i in items if (i.get("tweet_type") or i.get("action_type") or "").upper() == "REPLY"]
    if len(_cur_replies) < 5:
        print(f"\n[3/4] apidojo/twitter-profile-scraper replies (saat ini {len(_cur_replies)} reply)...")
        # 3a: apidojo/twitter-profile-scraper
        try:
            r3a = client.actor("apidojo/twitter-profile-scraper").call(run_input={
                "twitterHandles":        [clean],
                "maxTweets":             30,
                "includeNativeRetweets": False,
                "getAboutData":          False,
            })
            ds3a = getattr(r3a, "default_dataset_id", None)
            if ds3a:
                raw3a   = client.dataset(ds3a).list_items().items or []
                valid3a = [i for i in raw3a if i.get("fullText") or i.get("text") or i.get("id")]
                _lim3a  = bool(valid3a and not (valid3a[0].get("fullText") or valid3a[0].get("text") or valid3a[0].get("id")))
                if _lim3a:
                    print(f"   ↳ 3a: monthly limit — skip")
                else:
                    import re as _re3a
                    merged3a = 0
                    existing_ids3 = {x.get("id") or x.get("tweetId") or "" for x in items}
                    print(f"   ↳ 3a apidojo profile: {len(raw3a)} raw → {len(valid3a)} valid")
                    for tw in valid3a:
                        _tx3a    = _safe_str(tw.get("fullText") or tw.get("text") or "").strip()
                        _is_rp3a = bool(tw.get("isReply") or tw.get("in_reply_to_status_id") or tw.get("inReplyToStatusId"))
                        if not _is_rp3a and _tx3a.startswith("@") and not _tx3a.startswith("RT @"):
                            _m3a = _re3a.match(r'^@(\w+)', _tx3a)
                            if _m3a and _m3a.group(1).lower() != clean_lower:
                                _is_rp3a = True
                        if _is_rp3a:
                            tw["isReply"] = True
                            tw["tweet_type"] = "REPLY"
                        if not tw.get("author"):
                            tw["author"] = {"userName": clean, "name": clean}
                        _normalise_item(tw, clean)
                        _twid3a = tw.get("id") or tw.get("tweetId") or ""
                        if not _twid3a or _twid3a in existing_ids3:
                            if _twid3a and _is_rp3a:
                                for _xi in items:
                                    if (_xi.get("id") or _xi.get("tweetId") or "") == _twid3a:
                                        if (_xi.get("tweet_type") or "POST").upper() == "POST":
                                            _xi.update({"tweet_type":"REPLY","action_type":"REPLY","isReply":True})
                                            merged3a += 1
                                        break
                            continue
                        items.append(tw)
                        existing_ids3.add(_twid3a)
                        if _is_rp3a:
                            merged3a += 1
                    print(f"   ↳ ✅ 3a merged {merged3a} replies")
        except Exception as e3a:
            print(f"   ⚠️  3a apidojo profile error: {str(e3a)[:70]}")

        # 3b: fallback ke cryptosignals action=both dengan @mention detection
        _cur_replies2 = [i for i in items
                         if (i.get("tweet_type") or i.get("action_type") or "").upper() == "REPLY"
                         or bool(i.get("isReply") or i.get("is_reply"))]
        if len(_cur_replies2) < 3:
            print(f"   ↳ 3b: cryptosignals fallback ({len(_cur_replies2)} reply)...")
            try:
                r3b = client.actor("cryptosignals/twitter-scraper").call(run_input={
                    "username":   clean,
                    "action":     "both",
                    "maxResults": 100,
                })
                ds3b = getattr(r3b, "default_dataset_id", None)
                if ds3b:
                    raw3b    = client.dataset(ds3b).list_items().items or []
                    tweets3b = [i for i in raw3b if i.get("tweet_text") or i.get("tweet_id")]
                    import re as _re3b
                    existing_ids3b = {x.get("id") or x.get("tweetId") or x.get("tweet_id") or "" for x in items}
                    merged3b = 0
                    for tw in tweets3b:
                        if tw.get("is_reply"):   tw["isReply"]   = True
                        if tw.get("is_retweet"): tw["isRetweet"] = True
                        if tw.get("is_quote"):   tw["isQuote"]   = True
                        _irt3b = tw.get("in_reply_to_tweet_id") or tw.get("in_reply_to_status_id") or ""
                        if _irt3b:
                            tw["inReplyToStatusId"] = str(_irt3b)
                            tw["isReply"] = True
                        _txt3b = _safe_str(tw.get("tweet_text") or tw.get("text") or "").strip()
                        if (not tw.get("isReply") and not tw.get("is_reply") and
                                _txt3b.startswith("@") and not _txt3b.startswith("RT @")):
                            _m3b = _re3b.match(r'^@(\w+)', _txt3b)
                            if _m3b and _m3b.group(1).lower() != clean_lower:
                                tw["isReply"] = True
                        _normalise_item(tw, clean)
                        _twid3b = tw.get("id") or tw.get("tweetId") or ""
                        _is_r3b = bool(tw.get("isReply") or tw.get("is_reply"))
                        if not _twid3b or _twid3b in existing_ids3b:
                            if _twid3b and _is_r3b:
                                for _xi in items:
                                    if (_xi.get("id") or _xi.get("tweetId") or "") == _twid3b:
                                        if (_xi.get("tweet_type") or "POST").upper() == "POST":
                                            _xi.update({"tweet_type":"REPLY","action_type":"REPLY","isReply":True})
                                            merged3b += 1
                                        break
                            continue
                        items.append(tw)
                        existing_ids3b.add(_twid3b)
                        if _is_r3b:
                            merged3b += 1
                    _tot3b = sum(1 for i in items if
                        (i.get("tweet_type") or i.get("action_type") or "").upper() == "REPLY" or
                        bool(i.get("isReply") or i.get("is_reply")))
                    print(f"   ↳ ✅ 3b merged {merged3b} | Total replies: {_tot3b}")
            except Exception as e3b:
                print(f"   ⚠️  3b cryptosignals error: {str(e3b)[:70]}")
    else:
        print(f"\n[3/4] Skip replies scraper — sudah ada {len(_cur_replies)} replies")

    # ── ACTOR 3c: apidojo/twitter-profile-scraper — native retweets ──────────
    if not reposts:
        print(f"\n[3c] apidojo/twitter-profile-scraper includeNativeRetweets...")
        try:
            r3c = client.actor("apidojo/twitter-profile-scraper").call(run_input={
                "twitterHandles":        [clean],
                "maxTweets":             20,
                "includeNativeRetweets": True,
                "getAboutData":          False,
            })
            ds3c = getattr(r3c, "default_dataset_id", None)
            if ds3c:
                raw3c   = client.dataset(ds3c).list_items().items or []
                valid3c = [i for i in raw3c if i.get("fullText") or i.get("text") or i.get("id")]
                _lim3c  = bool(valid3c and not (valid3c[0].get("fullText") or valid3c[0].get("text") or valid3c[0].get("id")))
                if _lim3c:
                    print(f"   ↳ 3c: monthly limit — skip")
                else:
                    rt3c = [i for i in valid3c if _is_retweet(i)]
                    print(f"   ↳ 3c: {len(raw3c)} raw → {len(rt3c)} RT")
                    for _i3c in rt3c:
                        _rp3c = _parse_rt_item(_i3c)
                        if _rp3c:
                            reposts.append(_rp3c)
                    if reposts:
                        print(f"   ✅ 3c: {len(reposts)} reposts")
                    else:
                        print(f"   ↳ 3c: 0 RT dari {len(rt3c)} items")
        except Exception as e3c:
            print(f"   ⚠️  3c native retweets error: {str(e3c)[:70]}")

    # ── ACTOR 4: apidojo/tweet-scraper — fallback jika masih sedikit ──────
    valid_so_far = [i for i in items if i.get("fullText") or i.get("tweet_text") or i.get("text")]
    if len(valid_so_far) < 5:
        print(f"\n[4/4] cryptosignals fallback (saat ini hanya {len(valid_so_far)} tweet)...")
        try:
            r4 = client.actor("cryptosignals/twitter-scraper").call(run_input={
                "username":   clean,
                "action":     "tweets",
                "maxResults": 30,
            })
            ds4 = getattr(r4, "default_dataset_id", None)
            if ds4:
                raw4   = client.dataset(ds4).list_items().items or []
                items4 = [i for i in raw4 if i.get("tweet_text") or i.get("tweet_id")]
                print(f"   ↳ {len(raw4)} raw → {len(items4)} valid")
                for tw in items4:
                    if tw.get("is_reply"):   tw["isReply"]   = True
                    if tw.get("is_retweet"): tw["isRetweet"] = True
                    _normalise_item(tw, clean)
                existing_ids = {i.get("id") or i.get("tweetId") or "" for i in items}
                new_items4 = [i for i in items4 if (i.get("id") or i.get("tweetId") or "") not in existing_ids]
                if new_items4:
                    items = items + new_items4
                    if not actor_used:
                        actor_used = "cryptosignals/twitter-scraper"
        except Exception as e4:
            msg = f"Actor4 (fallback) error: {e4}"
            print(f"   ⚠️  {msg}")
            scrape_errors.append(msg)
    else:
        print(f"\n[4/4] Skip fallback — sudah ada {len(valid_so_far)} tweet")

    # ── Summary actors ────────────────────────────────────────────────────
    print(f"\n   Actor dipakai : {actor_used or 'tidak ada'}")
    print(f"   Total item    : {len(items)}")

    if not items:
        return {
            **_build_empty(
                clean,
                f"Semua 3 actor gagal untuk @{clean}. "
                f"Kemungkinan: akun privat, Apify free plan rate limit, "
                f"atau Twitter anti-scraping. Coba akun lain atau upgrade plan."
            ),
            "actor_used":       actor_used,
            "scrape_errors":    scrape_errors,
            "data_limitations": [
                "apidojo free tier: max 10 item/run",
                "Akun besar (>1M followers) sering di-block semua actor",
                "Solusi: upgrade Apify plan atau pakai tweepy + Bearer Token",
            ],
        }

    # ── Parse profile ─────────────────────────────────────────────────────
    profile      = _extract_profile_from_items(items, clean)
    user_id      = profile["user_id"]
    full_name    = profile["full_name"]
    bio          = profile["bio"]
    followers    = profile["followers"]
    following    = profile["following"]
    verified     = profile["verified"]
    profile_pic  = profile["profile_pic"]
    banner_image = profile["banner_image"]
    join_date    = profile["join_date"]
    location     = profile["location"]
    website      = profile["website"]
    tweet_count  = profile["tweet_count"]

    print(
        f"\n   Profile: {full_name} | Followers: {followers:,} | "
        f"Verified: {verified} | Join: {join_date or '?'}"
    )

    # ── Parse tweets ──────────────────────────────────────────────────────
    print(f"   Parsing {len(items)} items...")
    posts:         List[Dict] = []
    # reposts sudah diinisialisasi di Actor 1.5 — jangan reset di sini
    quotes_list:   List[Dict] = []
    user_comments: List[Dict] = []
    seen_ids:      set        = set()
    tweet_index:   Dict[str, str] = {}

    _STRIP = {"item_handle", "orig_author", "orig_text", "metrics_dict"}
    _type_counts = {"POST": 0, "REPLY": 0, "RETWEET": 0, "QUOTE": 0}
    # Map id → tweet_type yang sudah diproses, untuk hindari duplikat
    _processed: Dict[str, str] = {}

    for item in items:
        parsed = _parse_tweet_item(item, clean, clean_lower)
        if not parsed:
            continue
        item_id   = parsed["id"]
        this_type = parsed["tweet_type"]

        # Kalau sudah diproses dengan type yang SAMA atau lebih spesifik → skip
        prev_type = _processed.get(item_id)
        if prev_type is not None:
            # Sudah ada — skip kalau prev lebih spesifik atau sama
            if prev_type != "POST" or this_type == "POST":
                continue
            # prev=POST, this=REPLY/RETWEET/QUOTE → re-process, hapus entry POST lama
            posts[:] = [p for p in posts if p.get("id") != item_id]
            tweet_index.pop(item_id, None)
        _processed[item_id] = this_type
        seen_ids.add(item_id)
        tweet_type       = parsed["tweet_type"]
        item_handle      = parsed["item_handle"]
        orig_author      = parsed["orig_author"]
        orig_text        = parsed["orig_text"]
        metrics_dict     = parsed["metrics_dict"]
        content_analysis = parsed["content_analysis"]
        ai_description   = content_analysis["ai_description"]
        base             = {k: v for k, v in parsed.items() if k not in _STRIP}
        _type_counts[tweet_type] = _type_counts.get(tweet_type, 0) + 1

        if tweet_type == "RETWEET":
            if not orig_author:
                rt_blk = item.get("retweetedTweet") or {}
                orig_author = _safe_str((rt_blk.get("author") or {}).get("userName") or "")
                orig_text   = _safe_str(rt_blk.get("fullText") or rt_blk.get("text") or orig_text or "")
            # original_tweet_url: dari retweetedTweet.url atau referenced_tweet_url
            _orig_url = (_safe_str((item.get("retweetedTweet") or {}).get("url") or "") or
                         parsed.get("referenced_tweet_url") or "")
            reposts.append({
                "video_url":           parsed["tweet_url"],
                "tweet_url":           parsed["tweet_url"],
                "original_author":     orig_author,
                "original_author_url": f"https://x.com/{orig_author}" if orig_author else "",
                "original_tweet_url":  _orig_url,
                "original_caption":    orig_text[:300],
                "orig_text":           orig_text[:300],
                "repost_date":         parsed["created_at"],
                "created_at":          parsed["created_at"],
                "hashtags":            parsed["hashtags"],
                "mentions":            parsed["mentions"],
                "content_analysis":    content_analysis,
                "metrics":             metrics_dict,
                "sentiment":           {"label": "NEUTRAL", "score": 0.5},
                "content_description": ai_description,
            })
            # RT juga masuk posts agar tampil di Posts tab
            posts.append(base)

        elif tweet_type == "QUOTE":
            qt = item.get("quotedTweet") or {}
            q_orig_author = orig_author or _safe_str((qt.get("author") or {}).get("userName") or "")
            q_orig_text   = (orig_text or
                             _safe_str(qt.get("fullText") or qt.get("text") or "") or
                             _safe_str(item.get("quoted_tweet_text") or ""))
            _ref_url      = parsed.get("referenced_tweet_url") or ""
            quotes_list.append({
                "tweet_id":         item_id,
                "tweet_url":        parsed["tweet_url"],
                "post_url":         parsed["tweet_url"],
                "quote_comment":    parsed["content"],
                "text":             parsed["content"],
                "original_author":  q_orig_author,
                "original_text":    q_orig_text[:300],
                "quoted_tweet_url": _ref_url,
                "referenced_tweet_url": _ref_url,
                "created_at":       parsed["created_at"],
                "hashtags":         parsed["hashtags"],
                "mentions":         parsed["mentions"],
                "metrics":          metrics_dict,
                "sentiment":        {"label": "NEUTRAL", "score": 0.5},
                "content_analysis": content_analysis,
            })
            posts.append(base)

        elif tweet_type == "REPLY":
            # user_comments = reply yang ditulis TARGET sendiri
            # item_handle kosong = actor tidak set author field, asumsikan milik target
            author_handle = _safe_str(
                (item.get("author") or {}).get("userName") or
                (item.get("author") or {}).get("username") or
                item.get("user_handle") or item_handle or ""
            ).lower().lstrip("@")
            is_target_reply = (not author_handle) or (author_handle == clean_lower)
            if is_target_reply:
                user_comments.append({
                    "post_url":         parsed["tweet_url"],
                    "tweet_url":        parsed["tweet_url"],
                    "post_caption":     "",
                    "post_owner":       clean,
                    "reply_text":       parsed["content"],
                    "content":          parsed["content"],
                    "likes":            parsed["likes"],
                    "replies":          parsed["comments"],
                    "quotes":           parsed["quotes"],
                    "is_reply":         True,
                    "reply_to":         parsed["in_reply_to_user"],
                    "in_reply_to_user": parsed["in_reply_to_user"],
                    "in_reply_to_id":   parsed["in_reply_to_id"],
                    "created_at":       parsed["created_at"],
                    "lang":             parsed["lang"],
                    "sentiment":        {"label": "NEUTRAL", "score": 0.5},
                    "content_analysis": content_analysis,
                })
            posts.append(base)

        else:  # POST
            tweet_index[item_id] = parsed["content"][:150]
            posts.append(base)

    # Enrich user_comments
    for uc in user_comments:
        uc["post_caption"] = tweet_index.get(uc.get("in_reply_to_id") or "", "")

    # ── Guaranteed RT scanner dari teks "RT @" — exclude self-retweet ───
    if not reposts:
        import re as _re_rt
        for p in posts:
            tx = p.get("content") or p.get("text") or ""
            rt_m = _re_rt.match(r'^RT @(\w+):\s*(.*)', tx, _re_rt.DOTALL)
            if rt_m:
                _rt_author = rt_m.group(1)
                # Skip self-retweet (RT dari akun sendiri)
                if _rt_author.lower() == clean_lower:
                    continue
                _rt_text = rt_m.group(2).strip()[:300]
                reposts.append({
                    "video_url":           p.get("tweet_url", ""),
                    "tweet_url":           p.get("tweet_url", ""),
                    "original_author":     _rt_author,
                    "original_author_url": f"https://x.com/{_rt_author}",
                    "original_tweet_url":  p.get("referenced_tweet_url", ""),
                    "original_caption":    _rt_text,
                    "orig_text":           _rt_text,
                    "repost_date":         p.get("created_at", ""),
                    "created_at":          p.get("created_at", ""),
                    "hashtags":            p.get("hashtags", []),
                    "mentions":            p.get("mentions", []),
                    "metrics": {
                        "likes":    p.get("likes", 0),
                        "retweets": p.get("shares", 0),
                        "replies":  p.get("comments", 0),
                        "quotes":   p.get("quotes", 0),
                        "views":    p.get("plays", 0),
                    },
                    "sentiment":        {"label": "NEUTRAL", "score": 0.5},
                    "content_analysis": p.get("content_analysis", {}),
                })
        if reposts:
            print(f"   ✅ Guaranteed RT scanner: {len(reposts)} retweet dari teks RT @")

    print(f"\n   📊 Tweet type breakdown: {_type_counts}")
    print(f"   📊 posts={len(posts)} reposts={len(reposts)} quotes={len(quotes_list)} user_comments={len(user_comments)}")

    # Sort semua list dari terbaru ke terlama
    def _sort_key(x):
        return x.get("created_at") or x.get("repost_date") or ""

    posts         = sorted(posts,         key=_sort_key, reverse=True)
    reposts       = sorted(reposts,        key=_sort_key, reverse=True)
    quotes_list   = sorted(quotes_list,    key=_sort_key, reverse=True)
    user_comments = sorted(user_comments,  key=_sort_key, reverse=True)

    user_comments  = user_comments[:5]
    reposts        = reposts[:10]
    quotes_list    = quotes_list[:5]
    final_posts    = [p for p in posts if not p.get("is_repost")][:10]
    orig_posts     = [p for p in final_posts if p.get("tweet_type") == "POST"]
    total_likes    = sum(p.get("likes",    0) for p in final_posts)
    total_comments = sum(p.get("comments", 0) for p in final_posts)
    total_shares   = sum(p.get("shares",   0) for p in final_posts)

    print(
        f"\n   ✅ Posts: {len(final_posts)} (original: {len(orig_posts)}) | "
        f"user_comments: {len(user_comments)} | "
        f"reposts: {len(reposts)} | quotes: {len(quotes_list)}"
    )
    print(f"   ✅ Likes: {total_likes:,} | Shares: {total_shares:,}")

    return {
        "status":         "success",
        "platform":       "x",
        "username":       clean,
        "user_id":        user_id,
        "full_name":      full_name,
        "bio":            bio,
        "location":       location,
        "website":        website,
        "followers":      followers,
        "following":      following,
        "tweet_count":    tweet_count,
        "verified":       verified,
        "join_date":      join_date,
        "profile_pic":    profile_pic,
        "banner_image":   banner_image,
        "total_posts":    len(final_posts),
        "total_likes":    total_likes,
        "total_comments": total_comments,
        "total_shares":   total_shares,
        "has_text":       any(p.get("content") for p in final_posts),
        "posts":          final_posts,
        "user_comments":  user_comments,
        "reposts":        reposts,
        "quotes_list":    quotes_list,
        "actor_used":     actor_used,
        "scrape_errors":  scrape_errors,
        "data_limitations": [
            "apidojo free tier: max 10 item/run — upgrade Apify untuk lebih banyak tweet",
            "Akun besar (>1M followers) sering kena rate limit dari semua actor",
            "view_count: bisa 0 (pembatasan Twitter)",
            "getReplies dinonaktifkan untuk hemat kuota free plan",
            "Solusi jika masih kosong: pakai tweepy + Twitter Bearer Token",
        ],
    }
async def _twitter_scrape_real(username: str, apify_token: str = "") -> Dict:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None, partial(_twitter_scrape_sync, username, apify_token)
    )
