"""
fetch_instagram.py - Instagram Scraper via Apify v4.0
Fix: user_comments (replies + all posts) & repost (URL validation + data-slayer always)

Actor utama : apify/instagram-scraper
Actor komentar fallback: apify/instagram-comment-scraper
Actor repost dedicated: data-slayer/instagram-reposts
"""

import re
import time
import random
import asyncio
from typing import Dict, List, Any, Tuple
from functools import partial
from urllib.parse import unquote


# ── Helpers ───────────────────────────────────────────────────────────────────
def _safe_int(v: Any, d: int = 0) -> int:
    try:
        return int(v) if v is not None else d
    except (ValueError, TypeError):
        return d


def _safe_str(v: Any, d: str = "") -> str:
    return d if v is None else str(v).strip()


def _parse_ts(ts: Any) -> str:
    if not ts:
        return ""
    s = str(ts)
    if s.isdigit():
        try:
            return time.strftime("%Y-%m-%d", time.localtime(int(s)))
        except Exception:
            return s
    return s[:10] if len(s) >= 10 else s


def _build_empty(username: str, error: str) -> Dict:
    return {
        "status": "error", "platform": "instagram", "username": username,
        "full_name": "", "bio": "", "followers": 0, "following": 0,
        "likes": 0, "verified": False, "join_date": "",
        "profile_pic": "", "user_id": "", "profile_url": "",
        "website": "", "category": "", "is_private": False,
        "is_business": False, "cover_image": "", "total_posts": 0,
        "posts": [], "user_comments": [], "reposts": [],
        "total_likes": 0, "total_comments": 0, "total_shares": 0,
        "has_text": False, "scrape_errors": [error],
    }


# ── Visual Description Engine ─────────────────────────────────────────────────
_IG_RULES = [
    # Alam, gunung, outdoor, travel alam
    (["gunung","mountain","mountains","merbabu","sumbing","slamet","rinjani","semeru","prau",
      "ranukumbolo","pendaki","pendakian","hiking","hike","summit","camping","puncak",
      "edelweis","alam","nature","hutan","forest","waterfall","air terjun","curug",
      "canada","kanada","swiss","norway","alpine","outdoor","breathtaking","scenic",
      "landscape","valley","canyon","cliff","peak","trail","trek","backpack"],
     "Petualangan Alam & Pendakian",
     "damai, syukur, reflektif, menenangkan, penuh kebahagiaan",
     "pemandangan pegunungan spektakuler, puncak gunung, langit, awan, hamparan hijau, jalanan berkelok",
     "pendakian gunung, menikmati pemandangan alam, refleksi diri di alam terbuka"),

    # Pantai, laut, wisata air
    (["pantai","beach","laut","ocean","sea","sunset","sunrise","ombak","pasir","pulau",
      "island","diving","snorkel","surfing","waves","coastal","siargao","bali","lombok",
      "underwater","coral","reef","mentawai","nusa","gili"],
     "Wisata Pantai & Bahari",
     "santai, bahagia, refreshing, bebas, menikmati hidup",
     "pantai berpasir, laut biru, ombak, sunset/sunrise, pulau tropis",
     "liburan pantai, surfing, snorkeling, menikmati keindahan laut"),

    # Olahraga & fitness
    (["futsal","football","soccer","bola","goal","sport","basket","badminton",
      "gym","workout","fitness","olahraga","latihan","voli","lari","run","marathon",
      "training","exercise","muscle","lifting","crossfit","yoga","pilates"],
     "Olahraga & Kebugaran",
     "energik, semangat, kompetitif, penuh tekad, bersemangat",
     "lapangan olahraga, kostum atlet, alat gym, tubuh aktif bergerak",
     "latihan olahraga, pertandingan, workout intensif"),

    # Sekolah & kampus
    (["smk","sma","sekolah","kampus","mahasiswa","siswa","kuliah","pelajar","wisuda",
      "graduation","student","university","college","akademik","skripsi","ujian",
      "kelas","perpustakaan","laboratorium"],
     "Kehidupan Sekolah & Kampus",
     "ceria, bersemangat, penuh harapan, muda, ambisius",
     "lingkungan sekolah/kampus, seragam, buku, teman sekelas",
     "kegiatan belajar, wisuda, kehidupan kampus"),

    # Kuliner & makanan
    (["makan","food","kuliner","cafe","kopi","coffee","masak","nasi","bakso",
      "restaurant","resto","minuman","drink","eating","breakfast","lunch","dinner",
      "dessert","cake","pizza","sushi","boba","matcha","aesthetic food","foodie"],
     "Kuliner & Food Vlog",
     "menggugah selera, hangat, nikmat, menyenangkan, cozy",
     "hidangan lezat, plating cantik, suasana kafe yang nyaman, minuman berwarna",
     "mencicipi makanan, review kuliner, masak bersama"),

    # Musik & entertainment
    (["musik","music","dance","nyanyi","lagu","song","cover","konser","joget",
      "dj","beat","rap","pop","guitar","piano","violin","perform","stage","live"],
     "Musik & Hiburan",
     "meriah, ekspresif, penuh energi, bersemangat, menghibur",
     "alat musik, panggung, ekspresi wajah emosional, cahaya panggung",
     "bernyanyi, menari, perform musik live"),

    # Komedi & hiburan
    (["lucu","funny","comedy","humor","meme","prank","challenge","ngakak","ketawa",
      "gokil","kocak","parody","skit","react","reaction"],
     "Konten Hiburan & Komedi",
     "riang, menghibur, santai, spontan, penuh tawa",
     "ekspresi wajah kocak, situasi lucu sehari-hari, momen tak terduga",
     "konten komedi, prank, challenge seru"),

    # Travel umum
    (["travel","wisata","liburan","vacation","trip","explore","destinasi","vlog",
      "backpacker","nomad","roadtrip","journey","adventure","wanderlust","visiting",
      "tourism","holiday","getaway","abroad","overseas","japan","korea","europe",
      "relatable","memories","memory","miss","gone","throwback"],
     "Travel & Petualangan",
     "nostalgik, bebas, gembira, penuh kenangan, menginspirasi",
     "destinasi wisata indah, momen perjalanan, pemandangan kota/alam",
     "perjalanan wisata, eksplorasi tempat baru, berbagi kenangan"),

    # Fashion & beauty
    (["ootd","outfit","fashion","style","makeup","beauty","skincare","aesthetic",
      "selfie","portrait","foto","lookbook","haul","grwm","get ready","baju",
      "dress","sneakers","accessories","brand","luxury"],
     "Fashion & Gaya Hidup",
     "percaya diri, stylish, elegan, estetik, modis",
     "outfit lengkap, aksesori fashion, latar belakang estetik, ekspresi percaya diri",
     "foto outfit harian, review produk fashion/beauty, GRWM"),

    # Keluarga & momen personal
    (["keluarga","family","anak","ibu","ayah","sahabat","teman","pacar","couple",
      "birthday","ulang tahun","wedding","anniversary","reunion","together","love",
      "friendship","bestfriend","bff","squad","togetherness"],
     "Momen Personal & Keluarga",
     "hangat, penuh kasih, bahagia, terharu, bersyukur",
     "anggota keluarga/teman, momen spesial, dekorasi perayaan, ekspresi gembira",
     "merayakan momen bersama, foto keluarga, kenangan persahabatan"),

    # Motivasi & edukasi
    (["motivasi","motivation","quotes","belajar","edukasi","tutorial","tips",
      "inspirasi","semangat","sukses","growth","mindset","productivity","hustle",
      "grind","achieve","goals","dream","vision","self improvement","knowledge"],
     "Motivasi & Pengembangan Diri",
     "inspiring, positif, penuh semangat, memotivasi, memberdayakan",
     "teks inspiratif, suasana produktif, orang sedang bekerja keras",
     "berbagi motivasi, tips produktivitas, edukasi"),
]


def _sentiment_from_caption(caption: str, hashtags: list) -> dict:
    """
    Deteksi sentimen dari caption + hashtag secara rule-based.
    Return: {"label": "POSITIVE"|"NEGATIVE"|"NEUTRAL", "score": 0.0-1.0}
    """
    text = (caption + " " + " ".join(hashtags)).lower()

    pos_words = [
        "happy","happiness","love","amazing","beautiful","wonderful","blessed",
        "grateful","thankful","joy","joyful","smile","fun","best","great","awesome",
        "perfect","incredible","fantastic","enjoy","enjoying","excited","proud",
        "success","win","victory","achieve","beautiful","stunning","gorgeous",
        "bahagia","senang","cinta","indah","syukur","bersyukur","gembira","seru",
        "keren","bagus","mantap","asik","asyik","bangga","sukses","menang",
        "semangat","hebat","luar biasa","terbaik","berhasil","cantik","tampan",
        "love","memories","miss","heart","❤","💕","😊","😍","🥰","✨","🔥","💪",
        "do it all over","worth it","paid off","grateful","blessed"
    ]
    neg_words = [
        "sad","sadness","pain","hurt","cry","crying","broken","lost","alone",
        "lonely","miss","missing","hate","angry","anger","upset","disappoint",
        "fail","failure","stress","anxiety","tired","exhausted","depressed",
        "sedih","sakit","kehilangan","sendirian","benci","marah","kecewa",
        "gagal","lelah","stres","capek","susah","sulit","menyesal","galau",
        "broken","gone","empty","wallet","dirty","pain","leg pain","leg","struggle"
    ]

    pos_score = sum(1 for w in pos_words if w in text)
    neg_score = sum(1 for w in neg_words if w in text)

    # Cek emoji sentiment
    pos_emojis = ["❤","💕","😊","😍","🥰","✨","🔥","💪","🏆","🎉","🌟","💯","😁","🤩"]
    neg_emojis = ["😢","😭","💔","😔","😞","😩","😫","🥺","😥","😿"]
    import re as _re_s
    emojis_found = _re_s.findall(
        r"[\U0001F300-\U0001F9FF\U00002702-\U000027B0]+", caption
    )
    for e in emojis_found:
        if any(p in e for p in pos_emojis): pos_score += 1
        if any(n in e for n in neg_emojis): neg_score += 1

    total = pos_score + neg_score
    if total == 0:
        return {"label": "NEUTRAL", "score": 0.5}
    pos_ratio = pos_score / total
    if pos_ratio >= 0.6:
        score = min(0.5 + (pos_ratio - 0.5) * 1.2, 0.98)
        return {"label": "POSITIVE", "score": round(score, 2)}
    elif pos_ratio <= 0.4:
        score = min(0.5 + (0.5 - pos_ratio) * 1.2, 0.98)
        return {"label": "NEGATIVE", "score": round(score, 2)}
    else:
        return {"label": "NEUTRAL", "score": 0.5}


def _gen_vd(caption: str, hashtags: List[str],
            media_type: str = "image", mentions: List[str] = None,
            username: str = "", duration_sec: int = 0,
            views: int = 0, likes: int = 0, comments: int = 0) -> Dict:
    """
    Generate AI description super-detail untuk konten Instagram.
    Format: emoji sections dengan minimal ~200 kata total.
    """
    all_lower = (caption + " " + " ".join(hashtags)).lower()

    # ── Deteksi topik & mood dari rules ──────────────────────────────────
    topic    = "Konten Umum"
    mood     = "natural, santai, autentik, ekspresif"
    objects  = "aktivitas sehari-hari, ekspresi personal, momen autentik"
    activity = "berbagi momen personal di Instagram"
    meaning  = "Mengekspresikan diri dan berbagi cerita kepada followers"

    for kws, t, m, o, a in _IG_RULES:
        if any(kw in all_lower for kw in kws):
            topic, mood, objects, activity = t, m, o, a
            meaning = f"Berbagi konten {t.lower()} untuk menginspirasi dan terhubung dengan komunitas"
            break

    # ── Bersihkan caption ─────────────────────────────────────────────────
    cap_clean  = re.sub(r"\s+", " ", re.sub(r"[#@]\w+", "", caption)).strip()
    word_count = len(cap_clean.split()) if cap_clean else 0
    tag_str    = " ".join(f"#{h}" for h in hashtags[:10]) if hashtags else ""
    mention_str = ", ".join(f"@{m}" for m in (mentions or [])[:5]) if mentions else ""

    # ── Deteksi emoji di caption ──────────────────────────────────────────
    emoji_list = re.findall(
        r"[\U0001F300-\U0001F9FF\U00002702-\U000027B0\U0000231A-\U0000231B"
        r"\U000025AA-\U000025AB\U000025B6\U000025C0\U000025FB-\U000025FE"
        r"\U00002600-\U000026FF]+",
        caption
    )
    emoji_note = f" Konten ini menggunakan emoji {', '.join(emoji_list[:6])} yang memperkuat ekspresi visual." if emoji_list else ""

    # ── Label media & tipe konten ─────────────────────────────────────────
    mt = (media_type or "image").lower()
    if mt in ("video", "reel", "clips", "igtv"):
        content_type = "REEL"
        content_label = "Reel/Video"
        dur_note = f"Durasi {duration_sec} detik" if duration_sec else "Durasi pendek"
        format_desc = (
            "Format video pendek Reels yang dioptimalkan untuk engagement tinggi. "
            "Video vertikal fullscreen cocok untuk ditonton di mobile."
        )
    elif mt in ("album", "carousel", "sidecar"):
        content_type = "CAROUSEL"
        content_label = "Foto Carousel"
        dur_note = "Multi-slide"
        format_desc = (
            "Disajikan dalam format carousel — beberapa foto/video yang bisa digeser. "
            "Format ini mendorong swipe rate tinggi dan meningkatkan time-on-post."
        )
    else:
        content_type = "FOTO"
        content_label = "Foto"
        dur_note = "Gambar statis"
        format_desc = (
            "Konten foto tunggal dengan komposisi visual yang dirancang untuk "
            "menarik perhatian di feed Instagram."
        )

    creator_ref = f"@{username}" if username else "kreator"

    # ── Bangun AI description dengan semua section ────────────────────────
    sections = []

    # Header
    sections.append(
        f"🎬 [{content_type}] {dur_note}"
    )

    # TEMA
    sections.append(
        f"📌 TEMA: {topic} — "
        + (f'"{cap_clean[:120]}"' if cap_clean and word_count >= 3
           else f"Konten {topic.lower()} yang dibagikan oleh {creator_ref}")
    )

    # SUASANA
    mood_words = [m.strip() for m in mood.split(",")]
    mood_str   = ", ".join(mood_words) if mood_words else mood
    sections.append(
        f"🎭 SUASANA: {mood_str}"
        + (f" — Nuansa keseluruhan konten terasa {mood_words[0]} dan {mood_words[1] if len(mood_words)>1 else 'autentik'},"
           f" membawa perasaan {mood_words[2] if len(mood_words)>2 else 'positif'} bagi siapa pun yang menyaksikannya.")
    )

    # OBJEK
    sections.append(
        f"👀 OBJEK: {objects.capitalize()}"
        + (f" — Elemen-elemen visual ini membangun narasi {topic.lower()} yang kuat dan langsung dapat dirasakan oleh audiens.")
    )

    # AKTIVITAS
    sections.append(
        f"🏃 AKTIVITAS: {activity.capitalize()}"
        + (f" — {creator_ref} aktif menampilkan {activity.lower()} sebagai bagian dari ekspresi diri yang konsisten di platform.")
    )

    # PESAN
    cap_msg = f'"{cap_clean[:200]}"' if cap_clean and word_count >= 5 else f"konten {topic.lower()}"
    sections.append(
        f"💬 PESAN: {meaning}. "
        f"Kreator menyampaikan {cap_msg}."
        + emoji_note
    )

    # VISUAL
    sections.append(
        f"🖼 VISUAL: {content_label} dengan estetika {mood_words[0]} yang menampilkan {objects}. "
        f"{format_desc}"
        + (f" Mention ke {mention_str} menunjukkan konten kolaboratif atau tag komunitas." if mention_str else "")
    )

    # ANALISIS
    engagement_note = ""
    if likes or views or comments:
        if views >= 100000:
            engagement_note = f" Dengan {views:,} views dan {likes:,} likes, konten ini termasuk kategori viral di niche {topic.lower()}."
        elif likes >= 1000:
            engagement_note = f" Engagement {likes:,} likes menunjukkan konten ini resonan kuat dengan audiens."
        elif likes > 0:
            engagement_note = f" Mendapat {likes:,} likes yang mengindikasikan respons positif dari followers."

    hashtag_strategy = ""
    if hashtags:
        ht_count = len(hashtags)
        if ht_count >= 5:
            hashtag_strategy = (
                f" Strategi hashtag menggunakan {ht_count} tag ({tag_str}) "
                f"yang mencakup niche {topic.lower()}, meningkatkan discoverability konten."
            )
        elif ht_count > 0:
            hashtag_strategy = f" Hashtag yang digunakan: {tag_str}."

    sections.append(
        f"📊 ANALISIS: Konten ini adalah representasi {content_label.lower()} dari niche {topic} "
        f"yang diproduksi oleh {creator_ref}. "
        f"Penggunaan format {content_type} menunjukkan pemahaman kreator terhadap algoritma Instagram "
        f"yang memprioritaskan {content_type.lower() if content_type != 'FOTO' else 'foto berkualitas'}. "
        + engagement_note
        + hashtag_strategy
        + f" Konten bertema {topic.lower()} umumnya menarik audiens yang tertarik pada {objects.split(',')[0].strip()},"
        f" dengan tone {mood_words[0]} yang konsisten membangun brand identity kreator."
    )

    ai_description = " | ".join(sections)

    # ── Visual description ringkas ────────────────────────────────────────
    vis_desc = (
        f"{content_label} bertemakan {topic} yang menampilkan {objects}. "
        f'Caption: "{cap_clean[:100]}".' if cap_clean and word_count >= 3
        else f"{content_label} bertemakan {topic} yang menampilkan {objects}."
    )
    vis_desc += f" Suasana: {mood_words[0]}."

    return {
        "visual_description": vis_desc,
        "ai_description":     ai_description,
        "topic":    topic,
        "mood":     mood,
        "objects":  objects,
        "activity": activity,
    }


def _fetch_carousel_photos(post_url: str, sessionid: str = "") -> List[str]:
    """
    Ambil semua foto carousel dari satu post Instagram via instagrapi.
    Return list URL foto. Return [] jika gagal atau bukan carousel.
    """
    if not post_url:
        return []
    try:
        import os as _os_cf
        from dotenv import load_dotenv as _ld_cf
        _ld_cf()
        _sf = _os_cf.getenv("INSTAGRAM_SESSION_FILE", "instagram_session.json")
        _sess = sessionid or _os_cf.getenv("INSTAGRAM_SESSIONID", "")
        _csrf = _os_cf.getenv("INSTAGRAM_CSRFTOKEN", "")
        _mid  = _os_cf.getenv("INSTAGRAM_MID", "")

        from instagrapi import Client as _CL
        cl = _CL()
        cl.request_timeout = 20
        ok = False
        if _os_cf.path.exists(_sf):
            try:
                cl.load_settings(_sf)
                cl.account_info()
                ok = True
            except Exception:
                ok = False
        if not ok and _sess:
            try:
                cl.set_settings({
                    "cookies": {"sessionid": _sess, "csrftoken": _csrf, "mid": _mid},
                    "uuids": {}, "device_settings": {},
                    "user_agent": "Instagram 269.0.0.18.75 Android (26/8.0.0; 480dpi; 1080x1920; OnePlus; 6T Dev; devitron; qcom; en_US; 314665256)",
                })
                ok = True
            except Exception:
                ok = False
        if not ok:
            return []

        pk = cl.media_pk_from_url(post_url)
        info = cl.media_info(pk)
        photos: List[str] = []

        # media_type 8 = CAROUSEL_ALBUM
        if getattr(info, "media_type", 0) == 8:
            # instagrapi stores carousel items in resources[]
            resources = getattr(info, "resources", []) or []
            for res in resources:
                # thumbnail_url for photos, video_url for video slides
                url = str(getattr(res, "thumbnail_url", None) or
                          getattr(res, "video_url", None) or "")
                if url and url not in photos:
                    photos.append(url)

            # Fallback: try .dict() representation
            if not photos:
                try:
                    d = info.dict() if hasattr(info, "dict") else {}
                    for item in (d.get("resources") or d.get("carousel_media") or []):
                        if isinstance(item, dict):
                            u = (item.get("thumbnail_url") or
                                 item.get("video_url") or
                                 item.get("display_url") or "")
                            if u and u not in photos:
                                photos.append(str(u))
                except Exception:
                    pass

        return photos
    except Exception:
        return []


def _detect_repost(text: str) -> Dict:
    if not text:
        return {"is_repost": False, "original_author": ""}
    for pat in [r"credit[:\s]+@(\w+)", r"via\s+@(\w+)", r"repost[:\s]+@(\w+)",
                r"source[:\s]+@(\w+)", r"cr[:\s]+@(\w+)", r"📸\s*@(\w+)", r"©\s*@(\w+)"]:
        m = re.search(pat, text.lower())
        if m:
            return {"is_repost": True, "original_author": m.group(1)}
    return {"is_repost": False, "original_author": ""}


# ── URL validator untuk repost ─────────────────────────────────────────────────
def _is_valid_post_url(url: str) -> bool:
    """Return True hanya jika URL adalah post IG yang valid (/p/ atau /reel/)."""
    if not url:
        return False
    return "/p/" in url or "/reel/" in url


# ── Sync Scraper ──────────────────────────────────────────────────────────────

def _instagram_instagrapi_scrape(username: str) -> Dict:
    """
    Fallback scraper menggunakan instagrapi langsung (tanpa Apify).
    Ambil profile + posts + komentar via session cookie.
    Dipakai ketika Apify gagal atau credit habis.
    """
    import os as _os3
    from dotenv import load_dotenv as _ld3
    _ld3()
    _sess  = _os3.getenv("INSTAGRAM_SESSIONID", "").strip()
    _csrf  = _os3.getenv("INSTAGRAM_CSRFTOKEN", "").strip()
    _mid   = _os3.getenv("INSTAGRAM_MID", "").strip()
    _sf    = _os3.getenv("INSTAGRAM_SESSION_FILE", "instagram_session.json")
    _maxp  = int(_os3.getenv("INSTAGRAM_MAX_POSTS", "20"))

    clean = username.replace("@", "").strip()
    print(f"   ↳ [instagrapi fallback] @{clean}...")

    try:
        from instagrapi import Client as _IGC2
        cl = _IGC2()
        cl.request_timeout = 30
        logged = False

        # Coba session file dulu
        if not logged and _os3.path.exists(_sf):
            try:
                cl.load_settings(_sf)
                cl.account_info()
                logged = True
                print(f"   ✅ [instagrapi] session file OK")
            except Exception:
                logged = False

        # Coba sessionid cookie
        if not logged and _sess:
            try:
                cl.set_settings({
                    "cookies": {"sessionid": _sess, "csrftoken": _csrf, "mid": _mid},
                    "uuids": {}, "device_settings": {},
                    "user_agent": (
                        "Instagram 269.0.0.18.75 Android (26/8.0.0; 480dpi; "
                        "1080x1920; OnePlus; 6T Dev; devitron; qcom; en_US; 314665256)"
                    ),
                })
                _uinfo = cl.user_info_by_username(clean)
                logged = True
                print(f"   ✅ [instagrapi] sessionid OK, uid={_uinfo.pk}")
                try: cl.dump_settings(_sf)
                except Exception: pass
            except Exception as _e4:
                print(f"   ⚠️  [instagrapi] sessionid failed: {_e4}")
                _uinfo = None

        if not logged:
            return _build_empty(clean, "instagrapi: semua login gagal")

        # Ambil user info — pakai yang sudah di-cache kalau ada
        try:
            if "_uinfo" not in dir() or _uinfo is None:
                ui = cl.user_info_by_username(clean)
            else:
                ui = _uinfo
        except Exception as _e5:
            return _build_empty(clean, f"instagrapi user_info: {_e5}")

        full_name   = ui.full_name or clean
        bio         = ui.biography or ""
        followers   = ui.follower_count or 0
        following   = ui.following_count or 0
        verified    = bool(ui.is_verified)
        profile_pic = str(ui.profile_pic_url or "")
        user_id_str = str(ui.pk or "")
        is_private  = bool(ui.is_private)
        total_ig    = ui.media_count or 0
        website     = str(ui.external_url or "")
        category    = str(ui.category or "")
        is_business = bool(ui.is_business)

        print(f"   ✅ [instagrapi] {full_name} | {followers:,} followers | private={is_private}")

        if is_private:
            return _build_empty(clean, "Akun private — tidak bisa akses posts tanpa follow")

        # Ambil posts
        posts: List[Dict] = []
        try:
            import time as _time2
            medias = cl.user_medias(ui.pk, amount=_maxp)
            print(f"   ✅ [instagrapi] {len(medias)} posts")
            for med in medias:
                pid      = str(med.pk or "")
                sc       = med.code or pid
                cap      = med.caption_text or ""
                likes    = med.like_count or 0
                comms    = med.comment_count or 0
                plays    = med.view_count or 0
                dur      = int(med.video_duration or 0) if hasattr(med, "video_duration") else 0
                ts       = med.taken_at.strftime("%Y-%m-%d") if med.taken_at else ""
                purl     = f"https://www.instagram.com/p/{sc}/"
                is_vid   = str(med.media_type) in ("2", "VIDEO")
                is_slide = str(med.media_type) in ("8", "CAROUSEL_ALBUM")
                m_type   = "video" if is_vid else ("carousel" if is_slide else "image")

                # Thumbnail / image URL
                img_url = ""
                try:
                    # Video/Reel: pakai thumbnail_url
                    if hasattr(med, "thumbnail_url") and med.thumbnail_url:
                        img_url = str(med.thumbnail_url)
                    # Foto biasa: pakai image_versions (instagrapi >= 2.0)
                    if not img_url and hasattr(med, "image_versions2"):
                        try:
                            candidates = med.image_versions2.get("candidates", [])
                            if candidates:
                                img_url = candidates[0].get("url", "")
                        except Exception:
                            pass
                    # Carousel: ambil dari resources[0]
                    if not img_url and hasattr(med, "resources") and med.resources:
                        r0 = med.resources[0]
                        if hasattr(r0, "thumbnail_url") and r0.thumbnail_url:
                            img_url = str(r0.thumbnail_url)
                    # Fallback: pakai URL thumbnail via pk
                    if not img_url:
                        img_url = f"https://www.instagram.com/p/{sc}/media/?size=l"
                except Exception:
                    img_url = f"https://www.instagram.com/p/{sc}/media/?size=l"

                vid_url = ""
                try:
                    if hasattr(med, "video_url") and med.video_url:
                        vid_url = str(med.video_url)
                except Exception:
                    pass
                location = ""
                if hasattr(med, "location") and med.location:
                    location = str(getattr(med.location, "name", "") or "")

                hashtags = re.findall(r"#(\w+)", cap)
                mentions = re.findall(r"@(\w+)", cap)

                vd = _gen_vd(caption=cap, hashtags=hashtags, media_type=m_type,
                             mentions=mentions, username=clean,
                             duration_sec=dur, views=plays,
                             likes=likes, comments=comms)

                posts.append({
                    "id": pid, "post_id": pid,
                    "content": cap,      # untuk scraper_engine _normalise_post
                    "caption": cap,      # untuk dashboard renderPosts
                    "text": cap,         # backward compat
                    "visual_description": vd["visual_description"],
                    "ai_description":     vd["ai_description"],
                    "topic":   vd["topic"],   "mood":     vd["mood"],
                    "objects": vd["objects"], "activity": vd["activity"],
                    "analysis_method": "caption_only",
                    "likes": likes, "comments": comms, "shares": 0, "plays": plays,
                    "post_url": purl, "url": purl,
                    "video_url": vid_url, "image_url": img_url, "cover_url": img_url,
                    "displayUrl": img_url,   # Apify compat field
                    "created_at": ts, "hashtags": hashtags, "mentions": mentions,
                    "media_type": m_type, "duration_sec": dur, "location": location,
                    "is_pinned": False, "is_sponsored": False, "is_repost": False,
                    "repost_author": "", "music": {"title": "", "author": ""},
                    "shortCode": sc, "shortcode": sc,
                    "likesCount": likes, "commentsCount": comms,
                    "metrics": {"likes": likes, "comments": comms, "shares": 0, "plays": plays},
                })
        except Exception as _e6:
            print(f"   ⚠️  [instagrapi] user_medias: {_e6}")

        total_likes = sum(p["likes"] for p in posts)

        return {
            "status": "success", "platform": "instagram", "username": clean,
            "user_id": user_id_str, "profile_url": f"https://www.instagram.com/{clean}/",
            "full_name": full_name, "bio": bio,
            "followers": followers, "following": following,
            "likes": 0, "verified": verified,
            "join_date": "", "profile_pic": profile_pic, "cover_image": "",
            "website": website, "category": category,
            "is_private": is_private, "is_business": is_business,
            "location": "", "total_posts": total_ig or len(posts),
            "posts": posts, "user_comments": [], "reposts": [],
            "total_likes": total_likes, "total_comments": 0, "total_shares": 0,
            "has_text": any(p["content"] for p in posts),
            "scrape_errors": ["Data via instagrapi (Apify tidak tersedia)"],
        }

    except ImportError:
        return _build_empty(clean, "instagrapi tidak terinstall: pip install instagrapi")
    except Exception as _e7:
        return _build_empty(clean, f"instagrapi fallback error: {_e7}")


def _instagram_scrape_sync(username: str, apify_token: str = "") -> Dict:
    if not apify_token:
        import os
        from dotenv import load_dotenv
        load_dotenv()
        apify_token = os.getenv("APIFY_TOKEN", "")
    if not apify_token:
        return _build_empty(username, "APIFY_TOKEN tidak ditemukan di .env")
    try:
        from apify_client import ApifyClient
    except ImportError:
        return _build_empty(username, "apify_client tidak terinstall — pip install apify-client")

    clean      = username.replace("@", "").strip()
    clean_lower = clean.lower()
    profile_url = f"https://www.instagram.com/{clean}/"
    print(f"\n{'='*60}")
    print(f"📡 [Instagram v4.0] Scraping @{clean} via Apify")
    print(f"{'='*60}")

    try:
        client = ApifyClient(apify_token)
        items: List[Dict] = []
        profile_raw: Dict = {}

        # ── Run 0: Profile detail (followers/following akurat) ────────────
        print(f"\n[1/4] Profile details via resultsType=details...")
        try:
            r0 = client.actor("apify/instagram-scraper").call(run_input={
                "directUrls":   [profile_url],
                "resultsType":  "details",
                "resultsLimit": 1,
                "proxy": {"useApifyProxy": True, "apifyProxyGroups": ["RESIDENTIAL"]},
            })
            ds0 = getattr(r0, "default_dataset_id", None)
            if ds0:
                d0 = client.dataset(ds0).list_items().items or []
                if d0:
                    profile_raw = d0[0]
                    print(f"   ✅ Profile: followers={profile_raw.get('followersCount',0):,} "
                          f"following={profile_raw.get('followsCount',0):,}")
        except Exception as e0:
            print(f"   ⚠️  Profile run error (non-fatal): {e0}")

        # ── Run 1: Posts ──────────────────────────────────────────────────
        print(f"\n[2/4] Posts via resultsType=posts (limit 20)...")
        try:
            r1 = client.actor("apify/instagram-scraper").call(run_input={
                "directUrls":       [profile_url],
                "resultsType":      "posts",
                "resultsLimit":     10,
                "addParentData":    True,
                "includeChildPosts": True,
                "proxy": {"useApifyProxy": True, "apifyProxyGroups": ["RESIDENTIAL"]},
            })
            ds1 = getattr(r1, "default_dataset_id", None)
            if ds1:
                items = client.dataset(ds1).list_items().items or []
            print(f"   ✅ Posts raw: {len(items)} item")
            # Log field video dari item pertama
            if items:
                _s = items[0]
                _vf = {k: v for k, v in _s.items() if any(x in k.lower() for x in
                       ["video", "reel", "duration", "play", "view", "clip", "type", "isVideo"])}
                print(f"   [info] Video fields item[0]: {_vf}")
        except Exception as e1:
            print(f"   ⚠️  Posts run error: {e1}")

        # Fallback dari profile_raw.latestPosts
        if not items and profile_raw:
            for edge in (profile_raw.get("latestPosts") or
                         (profile_raw.get("edge_owner_to_timeline_media") or {}).get("edges") or []):
                node = (edge.get("node") or edge) if isinstance(edge, dict) else {}
                if isinstance(node, dict):
                    node.update({
                        "ownerUsername":  profile_raw.get("username", clean),
                        "ownerFullName":  profile_raw.get("fullName", ""),
                        "followersCount": profile_raw.get("followersCount", 0),
                        "followsCount":   profile_raw.get("followsCount", 0),
                        "biography":      profile_raw.get("biography", ""),
                        "verified":       profile_raw.get("isVerified", False),
                        "profilePicUrl":  profile_raw.get("profilePicUrl", ""),
                    })
                    items.append(node)
            print(f"   ↳ Fallback latestPosts: {len(items)} item")

        if not items and not profile_raw:
            # Fallback ke instaloader — scrape public profile tanpa login/auth
            print(f"   ↳ Fallback ke instaloader (no login required)...")
            try:
                import instaloader as _IL
                _L = _IL.Instaloader(
                    download_pictures=False,
                    download_videos=False,
                    download_video_thumbnails=False,
                    save_metadata=False,
                    compress_json=False,
                    quiet=True,
                )
                _L.context.request_timeout = 30
                _profile = _IL.Profile.from_username(_L.context, clean)

                profile_raw = {
                    "username":       _profile.username,
                    "fullName":       _profile.full_name,
                    "biography":      _profile.biography,
                    "followersCount": _profile.followers,
                    "followsCount":   _profile.followees,
                    "postsCount":     _profile.mediacount,
                    "isVerified":     _profile.is_verified,
                    "profilePicUrl":  _profile.profile_pic_url,
                    "isPrivate":      _profile.is_private,
                    "externalUrl":    _profile.external_url or "",
                    "businessCategoryName": _profile.business_category_name or "",
                }
                print(f"   ✅ instaloader: {_profile.username} | {_profile.followers:,} followers")

                # Ambil posts jika akun public
                if not _profile.is_private:
                    _count = 0
                    for _post in _profile.get_posts():
                        if _count >= 10: break
                        _imgs = []
                        if _post.typename == "GraphSidecar":
                            for _node in _post.get_sidecar_nodes():
                                if _node.is_video:
                                    _imgs.append({"type": "video", "url": _node.video_url or ""})
                                else:
                                    _imgs.append({"type": "image", "url": _node.display_url or ""})
                        items.append({
                            "shortcode":       _post.shortcode,
                            "id":              _post.shortcode,
                            "captionText":     _post.caption or "",
                            "likesCount":      _post.likes,
                            "commentsCount":   _post.comments,
                            "timestamp":       _post.date_utc.strftime("%Y-%m-%dT%H:%M:%S") if _post.date_utc else "",
                            "displayUrl":      _post.url,
                            "videoUrl":        _post.video_url or "",
                            "isVideo":         _post.is_video,
                            "type":            "GraphVideo" if _post.is_video else ("GraphSidecar" if _post.typename == "GraphSidecar" else "GraphImage"),
                            "images_list":     [n["url"] for n in _imgs if n["url"]],
                            "ownerUsername":   clean,
                            "locationName":    (_post.location.name if _post.location else ""),
                        })
                        _count += 1
                    print(f"   ✅ instaloader posts: {len(items)} posts")
                else:
                    print(f"   ⚠️  Akun private — posts tidak bisa diakses tanpa login")
            except Exception as e_il:
                print(f"   ⚠️  instaloader error: {e_il}")

        if not items and not profile_raw:
            return _build_empty(clean, f"@{clean} tidak ditemukan / akun privat / Instagram memblokir.")

        # ── Parse profile ─────────────────────────────────────────────────
        first = items[0] if items else profile_raw
        for c in items:
            uname = _safe_str((c.get("owner") or {}).get("username") or c.get("ownerUsername") or "")
            if uname.lower() == clean_lower:
                first = c
                break
        owner = first.get("owner") or first.get("ownerProfile") or {}

        def _pf(*keys):
            """Cari nilai pertama yang tidak None dari urutan sumber."""
            for k in keys:
                v = profile_raw.get(k) or first.get(k) or owner.get(k)
                if v is not None and v != "":
                    return v
            return None

        full_name   = _safe_str(_pf("fullName","ownerFullName","full_name") or clean)
        bio         = _safe_str(_pf("biography","bio") or "")
        followers   = _safe_int(_pf("followersCount") or
                                 (owner.get("edge_followed_by") or {}).get("count") or 0)
        following   = _safe_int(_pf("followsCount") or
                                 (owner.get("edge_follow") or {}).get("count") or 0)
        verified    = bool(_pf("isVerified","verified","is_verified") or False)
        profile_pic = _safe_str(_pf("profilePicUrl","profile_pic_url_hd","profilePicUrlHD") or "")
        user_id_str = _safe_str(_pf("id","ownerId","pk") or
                                 (owner.get("id") or owner.get("pk") or ""))
        website     = _safe_str(_pf("externalUrl","external_url") or "")
        category    = _safe_str(_pf("businessCategoryName","categoryName") or "")
        is_private  = bool(_pf("isPrivate","is_private") or False)
        is_business = bool(_pf("isBusiness","is_business") or bool(category) or False)
        total_ig    = _safe_int(_pf("postsCount","mediaCount") or
                                 (owner.get("edge_owner_to_timeline_media") or {}).get("count") or 0)

        # Scan semua items untuk followers jika masih 0
        if followers == 0:
            for _it in items + [first]:
                if not isinstance(_it, dict): continue
                _ow = _it.get("owner") or _it.get("ownerProfile") or {}
                _f  = _safe_int(_it.get("followersCount") or _ow.get("followersCount") or
                                 (_ow.get("edge_followed_by") or {}).get("count"))
                _fw = _safe_int(_it.get("followsCount") or _ow.get("followsCount") or
                                 (_ow.get("edge_follow") or {}).get("count"))
                if _f:  followers = _f
                if _fw: following = _fw
                if followers and following: break

        print(f"   ✅ Profile parsed: {full_name} | "
              f"Followers: {followers:,} | Following: {following:,} | Verified: {verified}")
        print(f"   ↳ user_id={user_id_str} | is_private={is_private} | category={category}")

        # ── Helper: apakah komentar ini dari pemilik akun? ─────────────────
        full_name_tokens = {t.lower() for t in full_name.split() if len(t) > 2} if full_name else set()

        def _is_owner_comment(c_user: str, c_fullname: str = "") -> bool:
            cu = _safe_str(c_user).lower().lstrip("@").strip()
            if not cu:
                return False
            if cu == clean_lower:
                return True
            # Partial match: username bisa return dengan format berbeda (misal underscore vs dot)
            cu_norm = cu.replace(".", "").replace("_", "").replace("-", "")
            cl_norm = clean_lower.replace(".", "").replace("_", "").replace("-", "")
            if cu_norm and cl_norm and cu_norm == cl_norm:
                return True
            if user_id_str and cu == user_id_str.lower():
                return True
            if full_name and c_fullname:
                if c_fullname.lower().strip() == full_name.lower().strip():
                    return True
                if full_name_tokens:
                    cf_tokens = {t.lower() for t in c_fullname.split() if len(t) > 2}
                    if len(full_name_tokens & cf_tokens) >= min(2, len(full_name_tokens)):
                        return True
            return False

        # ── Parse posts ───────────────────────────────────────────────────
        posts:        List[Dict] = []
        reposts_list: List[Dict] = []

        for item in items:
            if item.get("type") == "user" or item.get("itemType") == "user":
                continue
            item_owner = _safe_str(
                (item.get("owner") or {}).get("username") or
                item.get("ownerUsername") or ""
            ).lower()
            if item_owner and item_owner != clean_lower:
                continue

            pid       = _safe_str(item.get("id") or item.get("postId") or "")
            shortcode = _safe_str(item.get("shortCode") or item.get("shortcode") or pid)
            if not pid and not shortcode:
                continue

            # Caption: ambil yang asli dari user, bukan auto-generated "Photo by X on date"
            # Prioritas: caption > text > (skip alt karena itu auto-generated Apify)
            _raw_caption = item.get("caption") or item.get("text") or ""
            _alt = item.get("alt") or item.get("accessibility_caption") or ""
            # Jika caption kosong dan alt terlihat auto-generated, tetap kosong
            _is_autogen = (
                _alt.startswith("Photo by ") or
                _alt.startswith("Video by ") or
                _alt.startswith("Image by ")
            )
            caption = _safe_str(_raw_caption if _raw_caption else ("" if _is_autogen else _alt))

            likes    = _safe_int(item.get("likesCount") or item.get("likes") or item.get("like_count"))
            comments_n = _safe_int(item.get("commentsCount") or item.get("comments") or item.get("comment_count"))
            shares   = _safe_int(item.get("sharesCount") or item.get("shareCount") or
                                  item.get("shares") or item.get("reshareCount") or 0)
            plays    = _safe_int(item.get("videoViewCount") or item.get("viewsCount") or
                                  item.get("videoPlayCount") or item.get("plays") or
                                  item.get("view_count") or 0)
            purl     = _safe_str(item.get("url") or item.get("postUrl") or
                                  (f"https://www.instagram.com/p/{shortcode}/" if shortcode else ""))
            # Image URL — Apify pakai displayUrl sebagai field utama foto
            img_url  = _safe_str(
                item.get("displayUrl") or
                item.get("imageUrl") or
                item.get("thumbnailUrl") or
                item.get("previewUrl") or
                ((item.get("images") or [{}])[0].get("url") if item.get("images") else "") or
                ""
            )

            # ── Carousel: kumpulkan SEMUA foto dari childPosts/images ──────
            images_list: List[str] = []

            # Method 1: childPosts / sidecarMedias (Apify dengan includeChildPosts:true)
            _child = item.get("childPosts") or item.get("sidecarMedias") or []
            if _child and isinstance(_child, list):
                for _cp in _child:
                    if isinstance(_cp, dict):
                        _cp_url = _safe_str(
                            _cp.get("displayUrl") or _cp.get("imageUrl") or
                            _cp.get("thumbnailUrl") or _cp.get("url") or ""
                        )
                        if _cp_url and _cp_url not in images_list:
                            images_list.append(_cp_url)

            # Method 2: "images" / "latestImages" array field
            if not images_list:
                for _arr_key in ["images", "latestImages", "carousel_media", "sidecar_images"]:
                    _imgs = item.get(_arr_key) or []
                    if _imgs and isinstance(_imgs, list):
                        for _im in _imgs:
                            if isinstance(_im, dict):
                                _im_url = _safe_str(
                                    _im.get("url") or _im.get("src") or
                                    _im.get("displayUrl") or _im.get("imageUrl") or ""
                                )
                            elif isinstance(_im, str):
                                _im_url = _im
                            else:
                                _im_url = ""
                            if _im_url and _im_url not in images_list:
                                images_list.append(_im_url)
                        if images_list:
                            break

            # Method 3: edge_sidecar_to_children (GraphQL format dari Apify)
            if not images_list:
                _sidecar = (item.get("edge_sidecar_to_children") or {}).get("edges") or []
                for _edge in _sidecar:
                    _node = (_edge.get("node") or {}) if isinstance(_edge, dict) else {}
                    _n_url = _safe_str(
                        _node.get("display_url") or _node.get("displayUrl") or
                        _node.get("thumbnail_src") or ""
                    )
                    if _n_url and _n_url not in images_list:
                        images_list.append(_n_url)

            # Selalu masukkan foto utama ke index 0 jika belum ada
            if img_url and img_url not in images_list:
                images_list.insert(0, img_url)

            vid_url  = _safe_str(item.get("videoUrl") or item.get("videoSrc") or "")
            created  = _parse_ts(item.get("timestamp") or item.get("takenAtTimestamp"))
            type_raw = _safe_str(item.get("type") or item.get("mediaType") or "")
            type_lower = type_raw.lower()

            # ── Deteksi video/reel: cek SEMUA kemungkinan signal ──────────
            _dur_check = _safe_int(
                item.get("videoDuration") or item.get("duration") or
                item.get("video_duration") or item.get("videoLength") or
                (item.get("videoMeta") or {}).get("duration") or 0
            )
            _view_count = _safe_int(
                item.get("videoViewCount") or item.get("viewsCount") or
                item.get("view_count") or item.get("videoPlayCount") or
                item.get("plays") or 0
            )
            # Brute force: scan semua value integer yang mungkin view count
            if _view_count == 0:
                for _k, _v in item.items():
                    if isinstance(_v, (int, float)) and _v > 0:
                        _kl = _k.lower()
                        if any(x in _kl for x in ["view", "play", "watch"]):
                            _view_count = int(_v)
                            break

            _is_video_signal = (
                "video" in type_lower or "reel" in type_lower or
                item.get("isVideo") is True or
                bool(vid_url) or _dur_check > 0 or _view_count > 0 or
                item.get("productType") in ("clips", "reel", "igtv") or
                "graphvideo" in type_lower
            )
            _is_carousel_signal = (
                type_raw in ("Sidecar", "sidecar", "GraphSidecar") or
                bool(item.get("childPosts")) or
                bool(item.get("sidecarMedias"))
            )

            if _is_video_signal:
                media_type = "video"
            elif _is_carousel_signal:
                media_type = "carousel"
            else:
                media_type = "image"

            duration = _dur_check

            # Kalau carousel signal tapi images_list cuma 1 → tetap tandai carousel
            if _is_carousel_signal and not images_list and img_url:
                images_list = [img_url]

            if len(images_list) > 1:
                print(f"   ↳ Carousel: {len(images_list)} foto di post {shortcode[:12]}")

            # Hashtags: Apify bisa kirim sebagai list of strings ATAU list of dicts
            # Prioritas: dari field hashtags, fallback ke parse dari caption
            hashtags = re.findall(r"#(\w+)", caption)
            raw_ht   = item.get("hashtags") or []
            if raw_ht and isinstance(raw_ht, list) and len(raw_ht) > 0:
                parsed = []
                for h in raw_ht:
                    if isinstance(h, dict):
                        t = h.get("name") or h.get("hashtag") or h.get("tag") or h.get("text") or ""
                    elif isinstance(h, str):
                        t = h.lstrip("#").strip()
                    else:
                        t = ""
                    if t and t.strip():
                        parsed.append(t.strip())
                if parsed:
                    hashtags = parsed
                # Jika raw_ht ada tapi parsed kosong, fallback ke parse dari caption
                elif not hashtags:
                    hashtags = re.findall(r"#(\w+)", caption)

            # Juga cek hashtag di caption jika hashtags masih kosong
            if not hashtags and caption:
                hashtags = re.findall(r"#(\w+)", caption)

            mentions = re.findall(r"@(\w+)", caption)
            location = _safe_str(item.get("locationName") or (item.get("location") or {}).get("name") or "")
            is_pinned = bool(item.get("isPinned") or False)
            is_repost_info = _detect_repost(caption)
            vd = _gen_vd(caption=caption, hashtags=hashtags, media_type=media_type,
                        mentions=mentions, username=clean,
                        duration_sec=duration,
                        views=_view_count,
                        likes=likes,
                        comments=comments_n)
            _sent = _sentiment_from_caption(caption, hashtags)

            entry = {
                "id": pid or shortcode, "content": caption,
                "visual_description": vd["visual_description"],
                "ai_description":     vd["ai_description"],
                "topic": vd["topic"],
                "mood": vd["mood"], "objects": vd["objects"], "activity": vd["activity"],
                "analysis_method": "caption_only",
                "likes": likes, "comments": comments_n, "shares": shares, "plays": plays,
                "post_url": purl, "video_url": vid_url,
                "image_url": img_url or (f"https://www.instagram.com/p/{shortcode}/media/?size=l" if shortcode else ""),
                "cover_url": img_url or (f"https://www.instagram.com/p/{shortcode}/media/?size=l" if shortcode else ""),
                "images_list": images_list,
                "created_at": created, "hashtags": hashtags, "mentions": mentions,
                "media_type": media_type, "duration_sec": duration, "location": location,
                "is_pinned": is_pinned, "is_sponsored": bool(item.get("isSponsored") or False),
                "is_repost": is_repost_info["is_repost"],
                "repost_author": is_repost_info["original_author"],
                "music": {"title": "", "author": ""},
                "sentiment": _sent,
            }
            if is_repost_info["is_repost"]:
                reposts_list.append({
                    "video_url":          purl,
                    "original_author":    is_repost_info["original_author"],
                    "original_caption":   caption[:300],
                    "repost_date":        created,
                    "hashtags":           hashtags,
                    "image_url":          img_url,
                    "video_file_url":     vid_url,
                    "media_type":         media_type,
                    "post_type":          media_type,
                    "visual_description": vd["visual_description"],
                    "ai_description":     vd["ai_description"],
                    "topic":              vd["topic"],
                    "metrics":            {"likes": likes, "comments": comments_n, "shares": shares, "plays": plays},
                    "sentiment":          {"label": "NEUTRAL", "score": 0.5},
                    "content_description": (
                        f"Post dari @{is_repost_info['original_author']} yang di-repost oleh @{clean}."
                    ),
                    "_source": "caption_detect",
                })
            posts.append(entry)

        print(f"   ✅ Posts parsed: {len(posts)} | "
              f"Posts dengan komentar: {sum(1 for p in posts if p.get('comments',0)>0)}")

        # ── Run 1b: Instagrapi enrichment — carousel photos + komentar ───
        # Satu login session untuk dua tujuan:
        #   1. Ambil semua foto carousel (images_list) via media_info
        #   2. Ambil komentar owner per post (dipakai juga di Run 2)
        owner_replies_from_ig: List[Dict] = []
        seen_texts_ig: set = set()
        _ig_login_cl = None  # simpan client untuk dipakai lagi di Run 2
        try:
            import os as _os_ig
            _sf_ig = _os_ig.getenv("INSTAGRAM_SESSION_FILE", "instagram_session.json")
            import urllib.parse as _ulp_ig
            _si_ig = _ulp_ig.unquote(_os_ig.getenv("INSTAGRAM_SESSIONID", ""))
            _cs_ig = _ulp_ig.unquote(_os_ig.getenv("INSTAGRAM_CSRFTOKEN", ""))
            _mi_ig = _ulp_ig.unquote(_os_ig.getenv("INSTAGRAM_MID", ""))
            from instagrapi import Client as _IGCe
            _cle = _IGCe()
            _cle.request_timeout = 20
            _ok_e = False
            if _os_ig.path.exists(_sf_ig):
                try:
                    _cle.load_settings(_sf_ig)
                    _cle.account_info()
                    _ok_e = True
                    print(f"   ✅ [enrich] instagrapi session OK")
                except Exception:
                    _ok_e = False
            if not _ok_e and _si_ig:
                try:
                    _cle.set_settings({
                        "cookies": {"sessionid": _si_ig, "csrftoken": _cs_ig, "mid": _mi_ig},
                        "uuids": {}, "device_settings": {},
                        "user_agent": "Instagram 269.0.0.18.75 Android (26/8.0.0; 480dpi; 1080x1920; OnePlus; 6T Dev; devitron; qcom; en_US; 314665256)",
                    })
                    _cle.user_info_by_username(clean)
                    _ok_e = True
                    print(f"   ✅ [enrich] instagrapi sessionid OK")
                    try: _cle.dump_settings(_sf_ig)
                    except Exception: pass
                except Exception as _ee:
                    print(f"   ⚠️  [enrich] login: {_ee}")
            if _ok_e:
                _ig_login_cl = _cle
                import time as _time_e, random as _rnd_e
                _carousel_enriched = 0
                _comment_enriched = 0

                # ── Ambil semua media sekaligus via user_medias ─────────────
                # user_medias sudah return resources[] untuk carousel tanpa perlu
                # media_info per-post (lebih cepat, tidak kena rate limit)
                try:
                    _ig_user = _cle.user_info_by_username(clean)
                    _ig_medias = _cle.user_medias(_ig_user.pk, amount=20)
                    print(f"   ✅ [enrich] {len(_ig_medias)} medias dari user_medias")

                    # Buat map shortcode/pk → media object
                    _media_map = {}
                    for _med in _ig_medias:
                        _med_code = getattr(_med, "code", "")
                        _med_pk   = str(getattr(_med, "pk", ""))
                        if _med_code: _media_map[_med_code] = _med
                        if _med_pk:   _media_map[_med_pk]   = _med

                    # Enrich setiap post dengan data dari user_medias
                    for _pi, _post in enumerate(posts[:20]):
                        _psc    = _post.get("id") or _post.get("shortcode") or ""
                        _purl   = _post.get("post_url", "")
                        # Cari media yang cocok di map
                        _med_obj = _media_map.get(_psc) or _media_map.get(str(_psc))
                        if not _med_obj and _purl:
                            # Ekstrak shortcode dari URL sebagai key terakhir
                            _sc_m = re.search(r"/p/([A-Za-z0-9_-]+)", _purl)
                            if _sc_m: _med_obj = _media_map.get(_sc_m.group(1))

                        if not _med_obj:
                            continue

                        _mt_ig   = getattr(_med_obj, "media_type", 0)
                        _prod_ig = getattr(_med_obj, "product_type", "")

                        # ── Carousel: type 8 → ambil resources ─────────────
                        if _mt_ig == 8:
                            _resources_ig = getattr(_med_obj, "resources", []) or []
                            _imgs_ig = []
                            for _res in _resources_ig:
                                _u = str(getattr(_res, "thumbnail_url", None) or
                                         getattr(_res, "video_url", None) or "")
                                if _u and _u not in _imgs_ig:
                                    _imgs_ig.append(_u)
                            if len(_imgs_ig) > 1:
                                posts[_pi]["images_list"] = _imgs_ig
                                posts[_pi]["media_type"]  = "carousel"
                                _carousel_enriched += 1
                                print(f"   ✅ Carousel {_psc[:12]}: {len(_imgs_ig)} foto")

                        # ── Video/Reel: type 2 → tandai sebagai video ─────────
                        elif _mt_ig == 2:
                            _vu_ig = str(getattr(_med_obj, "video_url", None) or "")
                            _th_ig = str(getattr(_med_obj, "thumbnail_url", None) or "")
                            if _vu_ig:
                                posts[_pi]["video_url"] = _vu_ig
                            if _th_ig and not posts[_pi].get("image_url"):
                                posts[_pi]["image_url"] = _th_ig
                                posts[_pi]["cover_url"] = _th_ig
                            posts[_pi]["media_type"] = "video"

                except Exception as _e_um:
                    print(f"   ⚠️  [enrich] user_medias: {_e_um}")

                # Komentar diambil di Run 2 dengan fresh client — tidak di sini
                # supaya session tidak "panas" dan kena block di Run 2
                print(f"   ✅ Enrichment done: {_carousel_enriched} carousel (komentar di Run 2)")
        except ImportError:
            print(f"   ⚠️  instagrapi tidak terinstall")
        except Exception as _eenrich:
            print(f"   ⚠️  Enrich error: {_eenrich}")

        # ── Run 2: Komentar ───────────────────────────────────────────────
        # PRIMARY  : futurizerush/instagram-comment-scraper (Apify, sessionId, includeReplies)
        #   → Apify proxy RESIDENTIAL — tidak kena block IP lokal
        #   → sessionId di-encrypt Apify, aman
        #   → Langsung return replies[] nested per comment
        # FALLBACK A: api-empire/instagram-comments-scraper (GraphQL + sessionId)
        # FALLBACK B: herus13/instagram-comment-scraper (no login, parent_id flat)
        # FALLBACK C: instagrapi (kalau semua Apify gagal)
        import urllib.parse as _ulp_r2, os as _osr2
        _si_r2 = _ulp_r2.unquote(_osr2.getenv("INSTAGRAM_SESSIONID", ""))
        _cs_r2 = _ulp_r2.unquote(_osr2.getenv("INSTAGRAM_CSRFTOKEN", ""))
        _mi_r2 = _ulp_r2.unquote(_osr2.getenv("INSTAGRAM_MID",        ""))

        owner_replies: List[Dict] = list(owner_replies_from_ig)
        seen_texts: set = set(seen_texts_ig)

        posts_with_comments = [p for p in posts if p.get("comments", 0) > 0]
        posts_no_comment    = [p for p in posts if p.get("comments", 0) == 0]
        ordered = (posts_with_comments + posts_no_comment)[:5]  # 10→5 hemat waktu
        top_urls = [p["post_url"] for p in ordered if p["post_url"]]

        print(f"\n[3/4] Komentar — {len(top_urls)} post "
              f"({len(posts_with_comments)} ada komentar)...")

        post_by_url: Dict[str, Dict] = {p["post_url"]: p for p in posts if p["post_url"]}

        def _find_post_ctx(c_purl: str) -> Tuple[str, str]:
            if not c_purl:
                return "", ""
            for purl, pe in post_by_url.items():
                if c_purl == purl or purl in c_purl or c_purl in purl:
                    return purl, pe.get("content", "")[:100]
            return c_purl, ""

        def _extract_username(item: Dict) -> str:
            _owner = item.get("owner") or {}
            _owner_uname = ""
            if isinstance(_owner, dict):
                _owner_uname = _safe_str(
                    _owner.get("username") or _owner.get("uniqueId") or ""
                )
            return _safe_str(
                _owner_uname or
                item.get("ownerUsername") or
                item.get("username") or
                item.get("owner_username") or
                item.get("authorUsername") or ""
            )

        def _add_comment(c_user, c_text, c_likes, c_date, c_purl,
                         is_reply=False, reply_to=""):
            """Tambah ke owner_replies kalau match owner dan belum ada."""
            if not c_text or c_text in seen_texts:
                return False
            if not _is_owner_comment(c_user):
                return False
            seen_texts.add(c_text)
            _pctx, _pcap = _find_post_ctx(c_purl)
            owner_replies.append({
                "post_url":     _pctx or c_purl,
                "post_caption": _pcap,
                "post_owner":   clean,
                "content":      c_text,
                "likes":        c_likes,
                "replies":      0,
                "is_reply":     is_reply,
                "reply_to":     reply_to,
                "created_at":   c_date,
                "sentiment":    {"label": "NEUTRAL", "score": 0.5},
            })
            return True

        def _parse_comment_items(items_list, source=""):
            """
            Parse list komentar dari berbagai Apify actor.

            futurizerush format (top-level):
              { username, text, timestamp, postUrl, commentId,
                replies: [{ownerUsername, text, timestamp, likesCount}] }

            herus13 format:
              { comment: {owner_username, text, created_at, parent_id}, post_url }

            api-empire format:
              { ownerUsername, text, timestamp, postUrl, replies: [...] }
            """
            found = 0
            for ci in (items_list or []):
                if not isinstance(ci, dict) or ci.get("errorCode"):
                    continue

                # herus13 wraps komentar di nested "comment" object
                c_obj = ci.get("comment") if isinstance(ci.get("comment"), dict) else ci

                # ── Ekstrak username top-level ────────────────────────────
                # futurizerush: "username" (flat)
                # api-empire / herus13: "ownerUsername" atau "owner_username"
                c_user = _safe_str(
                    c_obj.get("username") or              # futurizerush top-level
                    c_obj.get("ownerUsername") or          # api-empire
                    c_obj.get("owner_username") or         # herus13
                    (c_obj.get("owner") or {}).get("username") or ""
                )
                c_text  = _safe_str(c_obj.get("text") or c_obj.get("comment") or "")
                c_likes = _safe_int(c_obj.get("commentLikeCount") or c_obj.get("likesCount") or
                                    c_obj.get("like_count") or 0)
                c_date  = _parse_ts(c_obj.get("timestamp") or c_obj.get("created_at") or "")
                # postUrl bisa di top-level ci atau di c_obj
                c_purl  = _safe_str(
                    ci.get("postUrl") or ci.get("post_url") or
                    c_obj.get("postUrl") or c_obj.get("post_url") or ""
                )

                # parent_id: herus13 pakai ini untuk tandai reply
                c_pid = c_obj.get("parent_id")
                is_r  = c_pid is not None and str(c_pid) not in ("", "null", "None", "0")

                if _add_comment(c_user, c_text, c_likes, c_date, c_purl,
                                is_reply=is_r, reply_to=str(c_pid) if is_r else ""):
                    found += 1
                    print(f"   ✅ [{source} {'reply' if is_r else 'top'}] "
                          f"@{c_user}: '{c_text[:55]}'")

                # ── Nested replies[] ──────────────────────────────────────
                # futurizerush: replies ada di top-level ci (ci==c_obj, bukan nested)
                # api-empire:   replies ada di c_obj
                # Hindari duplikat: kalau c_obj is ci, jangan ambil dua kali
                _seen_r = set()
                _reply_sources = list(ci.get("replies") or [])
                if c_obj is not ci:
                    _reply_sources += list(c_obj.get("replies") or [])
                _reply_sources += list(c_obj.get("childComments") or [])
                if c_obj is not ci:
                    _reply_sources += list(ci.get("childComments") or [])

                for rep in _reply_sources:
                    if not isinstance(rep, dict):
                        continue
                    r_user = _safe_str(
                        rep.get("ownerUsername") or    # futurizerush replies
                        rep.get("username") or
                        rep.get("owner_username") or
                        (rep.get("owner") or {}).get("username") or ""
                    )
                    r_text  = _safe_str(rep.get("text") or rep.get("comment") or "")
                    r_likes = _safe_int(rep.get("likesCount") or rep.get("like_count") or 0)
                    r_date  = _parse_ts(rep.get("timestamp") or rep.get("created_at") or "")
                    # Skip duplikat
                    _r_key = f"{r_user}:{r_text[:30]}"
                    if _r_key in _seen_r:
                        continue
                    _seen_r.add(_r_key)
                    if _add_comment(r_user, r_text, r_likes, r_date, c_purl,
                                    is_reply=True, reply_to=c_user):
                        found += 1
                        print(f"   ✅ [{source} reply→@{c_user[:12]}] "
                              f"@{r_user}: '{r_text[:50]}'")
            return found

        if top_urls:
            # ── PRIMARY: futurizerush (sessionId, includeReplies=True, NO proxy field) ──
            print(f"   ↳ [P] futurizerush/instagram-comment-scraper...")
            _futu_session_valid = False
            try:
                _inp_p = {
                    "postUrls":       top_urls,
                    "maxComments":    50,
                    "includeReplies": True,
                }
                if _si_r2:
                    _inp_p["sessionId"] = _si_r2
                _run_p = client.actor("futurizerush/instagram-comment-scraper").call(run_input=_inp_p)
                _ds_p  = getattr(_run_p, "default_dataset_id", None)
                if _ds_p:
                    _items_p = client.dataset(_ds_p).list_items().items or []
                    print(f"      {len(_items_p)} item")
                    if _items_p:
                        print(f"      keys[0]: {sorted(_items_p[0].keys())[:12]}")
                    # Cek apakah ada data bermakna (bukan hanya top-level tanpa replies)
                    _has_replies_p = any(
                        (_it.get("comment") or _it).get("parent_id") is not None
                        and str((_it.get("comment") or _it).get("parent_id") or "")
                        not in ("", "null", "None", "0")
                        for _it in _items_p
                    )
                    if _has_replies_p:
                        _futu_session_valid = True
                        print(f"      ✅ Session valid — replies tersedia")
                    else:
                        print(f"      ⚠️  Tidak ada replies — session mungkin expired")
                    n_p = _parse_comment_items(_items_p, source="P")
                    print(f"   {'✅' if n_p else '⚠️ '} futurizerush: {n_p} owner comments/replies")
            except Exception as _e_p:
                print(f"   ⚠️  futurizerush error: {_e_p}")

            # ── FALLBACK A: api-empire (GraphQL + sessionId) ───────────────
            if not owner_replies and top_urls:
                print(f"   ↳ [A] api-empire/instagram-comments-scraper...")
                try:
                    _inp_a = {
                        "urls":        top_urls,
                        "maxComments": 50,
                        "proxy": {"useApifyProxy": True, "apifyProxyGroups": ["RESIDENTIAL"]},
                    }
                    if _si_r2:
                        _inp_a["sessionId"] = _si_r2
                    _run_a = client.actor("api-empire/instagram-comments-scraper").call(run_input=_inp_a)
                    _ds_a  = getattr(_run_a, "default_dataset_id", None)
                    if _ds_a:
                        _items_a = client.dataset(_ds_a).list_items().items or []
                        print(f"      {len(_items_a)} item")
                        if _items_a:
                            print(f"      keys[0]: {sorted(_items_a[0].keys())[:12]}")
                        n_a = _parse_comment_items(_items_a, source="A")
                        print(f"   {'✅' if n_a else '⚠️ '} api-empire: {n_a} owner comments/replies")
                except Exception as _e_a:
                    print(f"   ⚠️  api-empire error: {_e_a}")

            # ── FALLBACK B: herus13 (no login, parent_id, flat output) ─────
            if not owner_replies and top_urls:
                print(f"   ↳ [B] herus13/instagram-comment-scraper (no login, parent_id)...")
                try:
                    _run_b = client.actor("herus13/instagram-comment-scraper").call(run_input={
                        "targets":       top_urls,
                        "max_comments":  500,
                        "max_posts":     20,
                        "proxyProvider": "default",
                    })
                    _ds_b  = getattr(_run_b, "default_dataset_id", None)
                    if _ds_b:
                        _items_b = client.dataset(_ds_b).list_items().items or []
                        print(f"      {len(_items_b)} item")
                        if _items_b:
                            _s0 = _items_b[0]
                            print(f"      keys[0]: {sorted(_s0.keys())[:10]}")
                            _c0 = _s0.get("comment") or _s0
                            if isinstance(_c0, dict):
                                print(f"      comment keys: {sorted(_c0.keys())[:10]}")
                        # Kumpulkan semua username unik untuk debug
                        _all_u = set()
                        for _ib in _items_b:
                            _cb = _ib.get("comment") or _ib
                            if isinstance(_cb, dict):
                                _ub = _safe_str(_cb.get("owner_username") or _cb.get("ownerUsername") or "").lower()
                                if _ub: _all_u.add(_ub)
                        print(f"      Username unik: {sorted(_all_u)[:20]}")
                        print(f"      Target: '{clean_lower}'")
                        n_b = _parse_comment_items(_items_b, source="B")
                        print(f"   {'✅' if n_b else '⚠️ '} herus13: {n_b} owner comments/replies")
                except Exception as _e_b:
                    print(f"   ⚠️  herus13 error: {_e_b}")

            # ── FALLBACK C: instagrapi (fresh client, kalau semua Apify gagal) ─
            if not owner_replies and top_urls and _si_r2:
                print(f"   ↳ [C] instagrapi (fresh client, last resort)...")
                import time as _tc_c, random as _rc_c
                try:
                    from instagrapi import Client as _IGC_c
                    _cl_c = _IGC_c()
                    _cl_c.request_timeout = 30
                    _ok_c = False
                    _sf_c = _osr2.getenv("INSTAGRAM_SESSION_FILE", "instagram_session.json")
                    if _osr2.path.exists(_sf_c):
                        try:
                            _cl_c.load_settings(_sf_c)
                            _cl_c.account_info()
                            _ok_c = True
                            print(f"   ✅ [C] session file OK")
                        except Exception:
                            _ok_c = False
                            try: _osr2.remove(_sf_c)
                            except: pass
                            _cl_c = _IGC_c()
                            _cl_c.request_timeout = 30
                    if not _ok_c:
                        try:
                            _cl_c.set_settings({
                                "cookies": {"sessionid": _si_r2, "csrftoken": _cs_r2, "mid": _mi_r2},
                                "uuids": {}, "device_settings": {},
                                "user_agent": (
                                    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) "
                                    "AppleWebKit/605.1.15 (KHTML, like Gecko) "
                                    "Version/17.4 Mobile/15E148 Safari/604.1"
                                ),
                            })
                            _cl_c.account_info()
                            _ok_c = True
                            print(f"   ✅ [C] cookies OK")
                        except Exception as _ec_login:
                            print(f"   ⚠️  [C] login gagal: {_ec_login}")
                    if _ok_c:
                        _found_c = 0
                        _err_c   = 0
                        _tc_c.sleep(_rc_c.uniform(3.0, 5.0))
                        for _pu_c in top_urls[:6]:
                            if _err_c >= 2: break
                            _tc_c.sleep(_rc_c.uniform(4.0, 7.0))
                            try:
                                _m_c = re.search(r"/(?:p|reel)/([A-Za-z0-9_-]+)", _pu_c)
                                _mpk_c = (_cl_c.media_pk_from_code(_m_c.group(1))
                                          if _m_c else _cl_c.media_pk_from_url(_pu_c))
                                _cmts_c = _cl_c.media_comments(_mpk_c, amount=50)
                                _pc_c = (post_by_url.get(_pu_c) or {}).get("content", "")[:100]
                                print(f"   ↳ {_pu_c[-30:]} → {len(_cmts_c)} komentar")
                                _err_c = 0
                                for _c_c in _cmts_c:
                                    _cu_c = (_c_c.user.username or "").lower()
                                    _ct_c = _c_c.text or ""
                                    _cd_c = (_c_c.created_at_utc.strftime("%Y-%m-%d")
                                             if _c_c.created_at_utc else "")
                                    if _add_comment(_cu_c, _ct_c, _c_c.like_count or 0,
                                                    _cd_c, _pu_c):
                                        _found_c += 1
                                        print(f"   ✅ [C top] '{_ct_c[:55]}'")
                                    _rn_c = getattr(_c_c, "replies_count", 0) or 0
                                    if _rn_c > 0:
                                        _tc_c.sleep(_rc_c.uniform(1.5, 3.0))
                                        try:
                                            for _r_c in (_cl_c.media_comment_replies(_mpk_c, _c_c.pk) or []):
                                                _ru_c = (_r_c.user.username or "").lower()
                                                _rt_c = _r_c.text or ""
                                                _rd_c = (_r_c.created_at_utc.strftime("%Y-%m-%d")
                                                         if _r_c.created_at_utc else "")
                                                if _add_comment(_ru_c, _rt_c, _r_c.like_count or 0,
                                                                _rd_c, _pu_c, is_reply=True,
                                                                reply_to=(_c_c.user.username or "")):
                                                    _found_c += 1
                                                    print(f"   ✅ [C reply] '{_rt_c[:55]}'")
                                        except Exception: pass
                            except Exception as _ec_c:
                                _es_c = str(_ec_c).lower()
                                print(f"   ⚠️  {_pu_c[-25:]}: {str(_ec_c)[:70]}")
                                if "sorry" in _es_c or "wrong" in _es_c or "challenge" in _es_c:
                                    print(f"   ⛔ IG block — stop")
                                    break
                                _err_c += 1
                        print(f"   {'✅' if _found_c else '⚠️ '} instagrapi: {_found_c} owner comments")
                except ImportError:
                    print(f"   ⚠️  instagrapi tidak terinstall")
                except Exception as _ec_main:
                    print(f"   ⚠️  instagrapi error: {_ec_main}")

        # Diagnosis akhir
        if not owner_replies:
            print(f"   ⚠️  DIAGNOSIS user_comments = 0:")
            print(f"   ⚠️  (1) @{clean} belum pernah komen/reply di post sendiri")
            print(f"   ⚠️  (2) Session expired — update INSTAGRAM_SESSIONID di .env")
            print(f"   ⚠️  (3) Rate limit — naikkan INSTAGRAM_DELAY_MIN di .env")
            print(f"   ⚠️  (4) Akun private — komentar tidak bisa diakses tanpa follow")
        else:
            print(f"   ✅ Total owner comments/replies: {len(owner_replies)}")

        # ── Run 3: Reposts ────────────────────────────────────────────────
        print(f"\n[4/4] Reposts untuk @{clean}...")

        def _parse_repost_item(ri: Dict, source: str = "") -> Dict:
            """
            Normalise satu item repost dari berbagai actor ke format standar.

            data-slayer/instagram-reposts:
                creator_username, post_url, video_url, thumbnail_url,
                like_count, comment_count, view_count, posted_at, post_type, caption

            seemuapps/instagram-reposts-scraper:
                authorUsername, postUrl, videoUrl, thumbnailUrl,
                likeCount, reshareCount, caption, mediaType

            datamagnet/instagram-user-reposts-scraper (raw IG API):
                owner.username, code, video_url, like_count, comment_count,
                taken_at_date, media_type (int), product_type, caption.text

            api-ninja/instagram-posts-scraper (parseType=reposts):
                username, id, code, like_count, comment_count, media_type,
                product_type, caption (object with .text)
            """
            # ── Original author ───────────────────────────────────────────
            orig = _safe_str(
                ri.get("creator_username") or           # data-slayer
                ri.get("authorUsername") or             # seemuapps
                (ri.get("owner") or {}).get("username") or   # datamagnet / raw IG
                (ri.get("user") or {}).get("username") or    # datamagnet alt
                ri.get("originalAuthorUsername") or
                ri.get("ownerUsername") or ""
            )
            if orig.lower() == clean_lower:
                orig = ""  # bukan original author kalau sama dengan target

            # ── Caption ──────────────────────────────────────────────────
            _cap_field = ri.get("caption") or ""
            if isinstance(_cap_field, dict):
                # datamagnet / api-ninja: caption adalah object {"text": "..."}
                r_cap = _safe_str(_cap_field.get("text") or "")
            else:
                r_cap = _safe_str(_cap_field or ri.get("text") or ri.get("alt") or "")

            # ── Post URL ─────────────────────────────────────────────────
            _code = _safe_str(
                ri.get("shortcode") or ri.get("shortCode") or   # data-slayer, seemuapps
                ri.get("code") or                                # datamagnet, api-ninja
                ri.get("id") or ""
            )
            r_url = _safe_str(
                ri.get("post_url") or          # data-slayer
                ri.get("postUrl") or           # seemuapps
                ri.get("url") or
                (f"https://www.instagram.com/p/{_code}/" if _code else "")
            )
            # Normalise: kalau code berisi angka panjang (bukan shortcode) → skip
            if r_url and "/p/" not in r_url and "/reel/" not in r_url and _code:
                if len(_code) > 20 and _code.isdigit():
                    r_url = ""  # ID numerik bukan shortcode

            # ── Video / Image URL ─────────────────────────────────────────
            vid_url_r = _safe_str(
                ri.get("video_url") or ri.get("videoUrl") or    # data-slayer, seemuapps, datamagnet
                ri.get("video_file_url") or ""
            )
            img_url_r = _safe_str(
                ri.get("thumbnail_url") or ri.get("thumbnailUrl") or
                ri.get("displayUrl") or ri.get("display_uri") or
                ri.get("imageUrl") or ""
            )
            if not img_url_r:
                # datamagnet: image_versions.items[0].url
                _iv = ri.get("image_versions") or {}
                _items_iv = _iv.get("items") or []
                if _items_iv and isinstance(_items_iv[0], dict):
                    img_url_r = _safe_str(_items_iv[0].get("url") or "")

            # ── Media type ────────────────────────────────────────────────
            _mt_raw = ri.get("media_type") or ri.get("mediaType") or ri.get("post_type") or ri.get("postType") or ""
            _mt_num = 0
            try: _mt_num = int(_mt_raw)
            except: pass
            # media_type int: 1=Photo, 2=Video/Reel, 8=Carousel
            post_type = _safe_str(
                ri.get("post_type") or ri.get("postType") or
                ri.get("product_type") or ri.get("productType") or ""
            ).lower()
            is_video = bool(
                _mt_num == 2 or
                post_type in ("reel", "video", "clips") or
                ri.get("is_video") or ri.get("isVideo") or
                vid_url_r
            )
            if not post_type:
                post_type = "video" if is_video else ("carousel" if _mt_num == 8 else "image")

            # ── Timestamp ─────────────────────────────────────────────────
            r_date = _parse_ts(
                ri.get("posted_at") or             # data-slayer
                ri.get("taken_at_date") or          # datamagnet
                ri.get("timestamp") or ri.get("takenAtTimestamp") or
                ri.get("repostedAt") or
                (str(ri.get("taken_at")) if ri.get("taken_at") else "") or ""
            )

            # ── Hashtags ──────────────────────────────────────────────────
            r_ht = ri.get("hashtags") or []
            if not isinstance(r_ht, list) or not r_ht:
                # datamagnet: caption.hashtags
                _cap_obj = ri.get("caption") or {}
                if isinstance(_cap_obj, dict):
                    r_ht = _cap_obj.get("hashtags") or []
            if not r_ht:
                r_ht = re.findall(r"#(\w+)", r_cap)

            # ── Metrics ───────────────────────────────────────────────────
            likes_r    = _safe_int(ri.get("like_count")    or ri.get("likeCount")    or ri.get("likesCount")    or 0)
            comments_r = _safe_int(ri.get("comment_count") or ri.get("commentCount") or ri.get("commentsCount") or 0)
            views_r    = _safe_int(ri.get("view_count")    or ri.get("viewCount")    or ri.get("videoViewCount") or
                                   ri.get("ig_play_count") or ri.get("play_count")   or 0)
            reposts_r  = _safe_int(ri.get("repost_count")  or ri.get("reshareCount") or ri.get("share_count")   or 0)

            vd_r = _gen_vd(caption=r_cap, hashtags=r_ht,
                           media_type="video" if is_video else "image",
                           username=orig or clean,
                           likes=likes_r, views=views_r, comments=comments_r)
            author_display = orig or "unknown"
            return {
                "video_url":          r_url,
                "original_author":    author_display,
                "original_caption":   r_cap[:300],
                "repost_date":        r_date,
                "hashtags":           r_ht,
                "image_url":          img_url_r,
                "video_file_url":     vid_url_r,
                "media_type":         "video" if is_video else ("carousel" if _mt_num == 8 else "image"),
                "post_type":          post_type,
                "visual_description": vd_r["visual_description"],
                "ai_description":     vd_r["ai_description"],
                "topic":              vd_r["topic"],
                "metrics": {
                    "likes":    likes_r,
                    "comments": comments_r,
                    "shares":   reposts_r,
                    "plays":    views_r,
                },
                "sentiment":          {"label": "NEUTRAL", "score": 0.5},
                "content_description": (
                    f"Repost dari @{author_display}: {r_cap[:150]}"
                    if r_cap else f"Repost dari @{author_display}."
                ),
                "_source": source,
            }

        def _add_reposts(items, source):
            """Parse list item → tambah ke reposts_list, return jumlah yang ditambahkan."""
            added = 0
            seen_urls = {r.get("video_url", "") for r in reposts_list}
            for ri in (items or []):
                if not isinstance(ri, dict):
                    continue
                if ri.get("errorCode") or ri.get("error") or ri.get("success") is False:
                    continue
                entry = _parse_repost_item(ri, source=source)
                r_url = entry.get("video_url", "")
                # Harus punya URL atau caption — skip kalau keduanya kosong
                if not r_url and not entry.get("original_caption"):
                    continue
                # Skip duplikat
                if r_url and r_url in seen_urls:
                    continue
                reposts_list.append(entry)
                seen_urls.add(r_url)
                added += 1
                print(f"   ✅ [{source}] @{entry['original_author']}: {r_url[-40:] or entry['original_caption'][:50]}")
            return added

        # ── Actor 1: data-slayer/instagram-reposts ─────────────────────
        # Input: {"username": "xxx"}
        # Output: creator_username, post_url, video_url, like_count, posted_at
        print(f"   ↳ [A1] data-slayer/instagram-reposts...")
        try:
            _r1 = client.actor("data-slayer/instagram-reposts").call(run_input={
                "username": clean,
                "maxItems": 10,
            })
            _ds1 = getattr(_r1, "default_dataset_id", None)
            if _ds1:
                _it1 = client.dataset(_ds1).list_items().items or []
                print(f"      {len(_it1)} item raw")
                if _it1:
                    print(f"      keys: {sorted(_it1[0].keys())[:15]}")
                _n1 = _add_reposts(_it1, "data-slayer")
                print(f"      → {_n1} repost valid")
        except Exception as _e1:
            print(f"   ⚠️  A1 error: {str(_e1)[:100]}")

        # ── Actor 2: seemuapps/instagram-reposts-scraper ───────────────
        # Input: {"username": "xxx", "maxItems": 0 (all)}
        # Output: authorUsername, postUrl, videoUrl, likeCount, reshareCount
        if not reposts_list:
            print(f"   ↳ [A2] seemuapps/instagram-reposts-scraper...")
            try:
                _r2 = client.actor("seemuapps/instagram-reposts-scraper").call(run_input={
                    "username": clean,
                    "maxItems": 10,
                })
                _ds2 = getattr(_r2, "default_dataset_id", None)
                if _ds2:
                    _it2 = client.dataset(_ds2).list_items().items or []
                    print(f"      {len(_it2)} item raw")
                    if _it2:
                        print(f"      keys: {sorted(_it2[0].keys())[:15]}")
                    _n2 = _add_reposts(_it2, "seemuapps")
                    print(f"      → {_n2} repost valid")
            except Exception as _e2:
                print(f"   ⚠️  A2 error: {str(_e2)[:100]}")

        # ── Actor 3: datamagnet/instagram-user-reposts-scraper ─────────
        # Input: {"username_or_id_or_url": "xxx", "max_results": 20}
        # Output: raw IG API format — owner.username, code, video_url, ...
        if not reposts_list:
            print(f"   ↳ [A3] datamagnet/instagram-user-reposts-scraper...")
            try:
                _r3 = client.actor("datamagnet/instagram-user-reposts-scraper").call(run_input={
                    "username_or_id_or_url": clean,
                    "max_results": 20,
                })
                _ds3 = getattr(_r3, "default_dataset_id", None)
                if _ds3:
                    _it3 = client.dataset(_ds3).list_items().items or []
                    print(f"      {len(_it3)} item raw")
                    if _it3:
                        print(f"      keys: {sorted(_it3[0].keys())[:15]}")
                    _n3 = _add_reposts(_it3, "datamagnet")
                    print(f"      → {_n3} repost valid")
            except Exception as _e3:
                print(f"   ⚠️  A3 error: {str(_e3)[:100]}")

        # ── Actor 4: api-ninja/instagram-posts-scraper (parseType=reposts) ──
        # Input: {"profiles": ["xxx"], "parseType": "reposts", "maxResults": 20}
        # Output: username, code, like_count, media_type, caption.text
        if not reposts_list:
            print(f"   ↳ [A4] api-ninja/instagram-posts-scraper (reposts)...")
            try:
                _r4 = client.actor("api-ninja/instagram-posts-scraper").call(run_input={
                    "profiles":     [clean],
                    "parseType":    "reposts",
                    "maxResults":   20,
                    "parseAllResults": False,
                })
                _ds4 = getattr(_r4, "default_dataset_id", None)
                if _ds4:
                    _it4 = client.dataset(_ds4).list_items().items or []
                    print(f"      {len(_it4)} item raw")
                    if _it4:
                        print(f"      keys: {sorted(_it4[0].keys())[:15]}")
                    _n4 = _add_reposts(_it4, "api-ninja")
                    print(f"      → {_n4} repost valid")
            except Exception as _e4:
                print(f"   ⚠️  A4 error: {str(_e4)[:100]}")

        # ── Diagnosis ──────────────────────────────────────────────────
        if not reposts_list:
            print(f"   ⚠️  DIAGNOSIS reposts = 0:")
            print(f"   ⚠️  (1) @{clean} belum pernah repost (fitur baru Agustus 2025)")
            print(f"   ⚠️  (2) Akun private — reposts tab tidak terlihat")
            print(f"   ⚠️  (3) Semua 4 actor gagal/timeout — coba lagi nanti")
        else:
            print(f"   ✅ Reposts final: {len(reposts_list)}")

        # ── Finalisasi ────────────────────────────────────────────────────
        owner_replies.sort(key=lambda x: x.get("created_at") or "", reverse=True)
        owner_replies = owner_replies[:10]
        reposts_list  = reposts_list[:10]

        total_likes    = sum(p["likes"]    for p in posts)
        total_comments = sum(p["comments"] for p in posts)

        print(f"\n{'='*60}")
        print(f"✅ SELESAI @{clean}")
        print(f"   Posts:         {len(posts)}")
        print(f"   User comments: {len(owner_replies)}")
        print(f"   Reposts:       {len(reposts_list)}")
        print(f"   Total likes:   {total_likes:,}")
        print(f"{'='*60}\n")

        return {
            "status": "success", "platform": "instagram", "username": clean,
            "user_id": user_id_str, "profile_url": profile_url,
            "full_name": full_name, "bio": bio,
            "followers": followers, "following": following,
            "likes": 0, "verified": verified,
            "join_date": "", "profile_pic": profile_pic, "cover_image": "",
            "website": website, "category": category,
            "is_private": is_private, "is_business": is_business,
            "location": "", "total_posts": total_ig or len(posts),
            "posts": posts, "user_comments": owner_replies, "reposts": reposts_list,
            "total_likes": total_likes, "total_comments": total_comments,
            "total_shares": 0, "has_text": any(p["content"] for p in posts),
            "scrape_errors": [],
        }

    except Exception as e:
        import traceback
        err = f"Instagram scrape error: {str(e)}"
        print(f"   ❌ {err}")
        print(traceback.format_exc())
        return _build_empty(clean, err)


# ── Async wrapper ─────────────────────────────────────────────────────────────
async def _instagram_scrape_real(username: str, apify_token: str = "") -> Dict:
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None, partial(_instagram_scrape_sync, username, apify_token)
    )
    # Fallback ke instagrapi jika Apify return data tidak lengkap
    # Trigger jika: posts kosong ATAU followers = 0 (apapun statusnya)
    apify_posts     = result.get("posts") or []
    apify_followers = result.get("followers", 0)
    apify_status    = result.get("status", "")

    needs_fallback = (
        apify_status == "error" or
        (not apify_posts) or
        (apify_followers == 0 and not apify_posts)
    )

    if needs_fallback:
        print(f"   [Instagram] Apify tidak lengkap (posts={len(apify_posts)}, followers={apify_followers}) -> instagrapi fallback...")
        fb = await loop.run_in_executor(
            None, partial(_instagram_instagrapi_scrape, username)
        )
        if fb.get("followers", 0) > 0 or fb.get("posts"):
            print(f"   [Instagram] instagrapi OK: {fb.get('followers',0):,} followers, {len(fb.get('posts',[]))} posts")
            # Jika Apify berhasil dapat profile tapi posts kosong, merge profile dari Apify
            if apify_followers > 0 and not fb.get("followers"):
                fb["followers"] = apify_followers
                fb["following"] = result.get("following", 0)
                fb["full_name"] = result.get("full_name", "") or fb.get("full_name", "")
                fb["verified"]  = result.get("verified", False) or fb.get("verified", False)
                fb["profile_pic"] = result.get("profile_pic", "") or fb.get("profile_pic", "")
            # Selalu preserve user_comments dan reposts dari Apify (instagrapi tidak scrape ini)
            apify_comments = result.get("user_comments") or []
            apify_reposts  = result.get("reposts") or []
            if apify_comments and not fb.get("user_comments"):
                fb["user_comments"] = apify_comments
            if apify_reposts and not fb.get("reposts"):
                fb["reposts"] = apify_reposts
            return fb
        print(f"   [Instagram] instagrapi fallback juga gagal — return hasil Apify apa adanya")
    return result