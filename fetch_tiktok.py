"""
fetch_tiktok.py - TikTok Scraper v3.1
Primary : Apify (herus13/tiktok-video-scraper + crawlerbros/tiktok-profile-scraper)
Fallback: yt-dlp (gratis, tanpa auth) — dipakai otomatis jika Apify credit habis
"""

import re
import time
import asyncio
import json
import datetime
from typing import Dict, List, Any, Optional
from functools import partial


# ─────────── helpers ──────────────────────────────────────────────────────────
def _safe_int(v: Any, d: int = 0) -> int:
    try: return int(v) if v is not None else d
    except (ValueError, TypeError): return d

def _safe_str(v: Any, d: str = "") -> str:
    return d if v is None else str(v).strip()

def _build_empty(username: str, error: str) -> Dict:
    return {
        "status": "error", "platform": "tiktok", "username": username,
        "full_name": "", "bio": "", "followers": 0, "following": 0,
        "likes": 0, "verified": False, "join_date": "", "profile_pic": "",
        "total_posts": 0, "posts": [], "user_comments": [],
        "comments_on_posts": [], "reposts": [],
        "total_likes": 0, "total_comments": 0, "total_shares": 0,
        "has_text": False, "scrape_errors": [error],
    }


def _is_cdn_url(url: str) -> bool:
    """Cek apakah URL adalah CDN TikTok yang bisa diputar langsung (bukan page URL)."""
    if not url:
        return False
    cdn_markers = [
        "v19-webapp.tiktok.com",
        "v16-webapp.tiktok.com",
        "v17-webapp.tiktok.com",
        "v26-webapp.tiktok.com",
        "tikcdn.io",
        "tiktokcdn.com",
        "muscdn.com",
        "api.apify.com/v2/key-value-stores",  # Apify KV download URL
        "mime_type=video",
        ".mp4",
    ]
    url_lower = url.lower()
    return any(m in url_lower for m in cdn_markers)


def _extract_tiktok_mp4(page_url: str, sessionid: str, ttwid: str) -> str:
    """
    Coba ekstrak direct MP4 URL dari halaman TikTok menggunakan session cookies.
    Return URL CDN jika berhasil, string kosong jika gagal.
    """
    try:
        import urllib.request as _ur
        import json as _json

        vid_match = re.search(r"/video/(\d+)", page_url)
        if not vid_match:
            return ""
        vid_id = vid_match.group(1)

        api_url = f"https://api.tiktok.com/aweme/v1/feed/?aweme_id={vid_id}"
        cookie_str = ""
        if sessionid:
            cookie_str += f"sessionid={sessionid}; "
        if ttwid:
            cookie_str += f"ttwid={ttwid}; "

        req = _ur.Request(
            api_url,
            headers={
                "User-Agent": "TikTok 26.1.3 rv:261303 (iPhone; iOS 14.4.2; en_US) Cronet",
                "Cookie": cookie_str.strip("; "),
            }
        )
        with _ur.urlopen(req, timeout=10) as resp:
            data = _json.loads(resp.read().decode())

        aweme_list = data.get("aweme_list") or []
        if not aweme_list:
            return ""

        video = aweme_list[0].get("video") or {}
        play_addr = video.get("play_addr") or {}
        urls = play_addr.get("url_list") or []
        return urls[0] if urls else ""
    except Exception:
        return ""


# ─────────── visual description engine ───────────────────────────────────────
_TOPIC_RULES = [
    # ── Alam & Outdoor ────────────────────────────────────────────────────────
    (["gunung","mountain","merbabu","sumbing","slamet","rinjani","semeru","prau",
      "ranukumbolo","pendaki","pendakian","hiking","summit","camping","puncak",
      "edelweis","nature","alam","hutan","waterfall","air terjun"],
     "Alam & Pendakian",
     "tenang, damai, penuh petualangan, kagum dengan keindahan alam",
     "pemandangan pegunungan, jalur pendakian, tenda, awan, vegetasi, puncak",
     "pendakian gunung, camping di alam terbuka, menikmati keindahan alam",
     "alam bebas yang indah, hijau dan sejuk",
     "Mengajak penonton untuk merasakan keajaiban alam dan semangat berpetualangan"),

    (["pantai","beach","laut","ocean","sunset","sunrise","ombak","pasir",
      "snorkeling","diving","pulau","island","surfing"],
     "Wisata Pantai & Bahari",
     "santai, segar, bahagia, menikmati liburan",
     "pantai berpasir, ombak laut, langit cerah, air biru jernih",
     "bermain di pantai, snorkeling, menikmati sunset/sunrise",
     "panorama pantai dengan air biru dan pasir putih bersih",
     "Menyampaikan keseruan dan keindahan wisata bahari"),

    # ── Olahraga ─────────────────────────────────────────────────────────────
    (["futsal","football","soccer","bola","goal","tanding","tournament","sport",
      "basket","badminton","gym","workout","fitness","pssicup","volleyball",
      "voli","renang","swim","atletik","lari","run","sepeda","cycling"],
     "Olahraga & Kebugaran",
     "energik, penuh semangat, kompetitif, bersemangat juang",
     "lapangan olahraga, peralatan gym, kostum tim, bola, atlet bergerak dinamis",
     "bertanding, berlatih keras, meraih prestasi olahraga",
     "adegan bergerak cepat dengan pencahayaan lapangan atau gym yang terang",
     "Memperlihatkan semangat olahraga dan mendorong gaya hidup aktif"),

    # ── Pendidikan & Sekolah ──────────────────────────────────────────────────
    (["smk","sma","sekolah","kampus","mahasiswa","siswa","wikrama","skul",
      "ujian","belajar","study","class","kelas","kuliah","wisuda","graduation"],
     "Pendidikan & Kehidupan Kampus",
     "ceria, bersemangat belajar, penuh harapan, muda",
     "ruang kelas, seragam sekolah, buku, papan tulis, teman sebaya",
     "belajar bersama, ujian, aktivitas ekskul, wisuda",
     "suasana sekolah yang ramai dan penuh semangat belajar",
     "Menggambarkan kehidupan akademis dan semangat generasi muda"),

    # ── Kuliner ───────────────────────────────────────────────────────────────
    (["makan","food","kuliner","cafe","kopi","coffee","masak","nasi","bakso",
      "review","restaurant","resep","recipe","dessert","jajan","street food",
      "mukbang","asmr","delicious","enak","yummy"],
     "Kuliner & Wisata Kuliner",
     "menggiurkan, hangat, nikmat, penasaran ingin mencoba",
     "makanan lezat, minuman berwarna, piring cantik, meja makan, dapur",
     "memasak, review makanan, mukbang, wisata kuliner",
     "close-up makanan dengan warna menggugah selera dan detail tekstur",
     "Mengundang penonton untuk mencoba kuliner yang ditampilkan"),

    # ── Musik & Entertainment ─────────────────────────────────────────────────
    (["dance","nyanyi","musik","music","lagu","joget","tarian","konser",
      "perform","cover","karaoke","dj","beat","trending sound","duet"],
     "Musik, Tari & Hiburan",
     "meriah, energik, ekspresif, menyenangkan",
     "gerakan tari yang fluid, ekspresi wajah penuh perasaan, lampu sorot",
     "menari mengikuti trend, menyanyikan lagu, perform di atas panggung",
     "video dinamis dengan gerakan cepat dan efek visual menarik",
     "Menampilkan bakat seni dan mengajak penonton ikut bergoyang"),

    # ── Komedi & Hiburan ──────────────────────────────────────────────────────
    (["lucu","funny","comedy","humor","meme","prank","challenge","viral",
      "ngakak","receh","gokil","absurd","parody","random","cringe"],
     "Hiburan & Komedi",
     "lucu, menghibur, ringan, membuat tertawa",
     "ekspresi wajah kocak, situasi absurd sehari-hari, reaksi berlebihan",
     "membuat video lucu, prank, mengikuti challenge viral",
     "potongan video cepat dengan reaksi ekspresif dan situasi tak terduga",
     "Menghibur penonton dan menciptakan tawa dengan konten ringan"),

    # ── Motivasi & Edukasi ────────────────────────────────────────────────────
    (["motivasi","motivation","inspire","semangat","sukses","tips","tutorial",
      "edukasi","belajar","cara","how to","hack","lifehack","knowledge",
      "sharing","informatif","fakta","fact"],
     "Motivasi, Edukasi & Tips",
     "inspiring, positif, penuh semangat, ingin berbagi ilmu",
     "teks motivasi di layar, gestur berbicara, infografis sederhana",
     "berbagi tips kehidupan, tutorial cara melakukan sesuatu, motivasi diri",
     "video informatif dengan teks overlay dan narasi yang jelas",
     "Menginspirasi dan memberikan nilai tambah pengetahuan bagi penonton"),

    # ── Travel & Lifestyle ────────────────────────────────────────────────────
    (["travel","wisata","liburan","vacation","trip","explore","vlog","destinasi",
      "tourism","backpacker","road trip","city tour","abroad","luar negeri"],
     "Travel & Vlog Perjalanan",
     "petualangan, bebas, antusias, penuh rasa ingin tahu",
     "pemandangan kota atau alam baru, koper, transportasi, landmark ikonis",
     "menjelajahi tempat baru, dokumentasi perjalanan, vlog wisata",
     "montase pemandangan indah dari berbagai sudut dengan pencahayaan natural",
     "Menginspirasi penonton untuk menjelajahi dunia dan menikmati pengalaman baru"),

    # ── Lifestyle & Fashion ───────────────────────────────────────────────────
    (["ootd","fashion","style","outfit","makeup","skincare","beauty","aesthetic",
      "selfie","glow up","transformation","daily routine","lifestyle"],
     "Gaya Hidup & Fashion",
     "percaya diri, estetis, stylish, penuh ekspresi diri",
     "pakaian trendi, aksesori, cermin, background estetis",
     "menampilkan outfit, tutorial makeup, transformasi penampilan",
     "video estetis dengan warna-warna yang harmonis dan pencahayaan soft",
     "Mengekspresikan identitas diri melalui penampilan dan gaya hidup"),

    # ── Gaming & Teknologi ────────────────────────────────────────────────────
    (["gaming","game","main game","play","ff","ml","mobile legends","pubg",
      "minecraft","streamer","highlights","clutch","teknologi","gadget","review"],
     "Gaming & Teknologi",
     "antusias, kompetitif, excited, penuh adrenalin",
     "layar game, controller, setup gaming, highlight aksi spektakuler",
     "bermain game, review gadget, highlight kemenangan",
     "rekaman layar game dengan reaksi dan komentar spontan",
     "Berbagi keseruan gaming dan passion terhadap teknologi"),

    # ── Keluarga & Momen Personal ─────────────────────────────────────────────
    (["keluarga","family","anak","baby","ibu","ayah","orang tua","saudara",
      "ulang tahun","birthday","anniversary","wedding","pernikahan","reunion"],
     "Keluarga & Momen Berharga",
     "hangat, penuh cinta, bahagia, mengharukan",
     "anggota keluarga bersama, momen spesial, dekorasi perayaan",
     "merayakan momen bersama keluarga, dokumentasi kenangan indah",
     "video hangat dengan nuansa kebersamaan dan ekspresi kebahagiaan",
     "Mengabadikan dan berbagi momen berharga bersama orang tercinta"),
]

# ── Keyword untuk ekstrak objek spesifik dari caption ─────────────────────────
_OBJECT_KEYWORDS = {
    "bola": "bola", "gol": "gol", "lapangan": "lapangan",
    "gunung": "gunung", "puncak": "puncak pegunungan",
    "pantai": "pantai", "laut": "lautan", "ombak": "ombak",
    "makanan": "makanan", "kopi": "minuman kopi", "nasi": "nasi",
    "dance": "gerakan tari", "musik": "musik", "lagu": "lagu",
    "seragam": "seragam sekolah", "kelas": "ruang kelas",
    "gym": "peralatan gym", "barbell": "barbel dan peralatan gym",
}


# ── Kata-kata berpotensi negatif/kasar untuk deteksi ─────────────────────────
_NEGATIVE_WORDS = [
    # Kata kasar Indonesia
    "anjing", "anjir", "babi", "bangsat", "bajingan", "keparat", "sialan",
    "brengsek", "kampret", "kontol", "memek", "tai", "tolol", "goblok",
    "bodoh", "idiot", "bodong", "dungu", "berak", "kentut",
    # Kata negatif
    "benci", "hate", "kill", "bunuh", "mati", "tipu", "bohong", "selingkuh",
    "judi", "togel", "slot", "porn", "xxx", "ngentot", "seks",
    # English profanity
    "fuck", "shit", "damn", "bitch", "asshole", "bastard", "hell", "crap",
]

def _analyze_video_real(video_url: str, post_url: str, caption: str,
                         duration_sec: int, username: str) -> Dict[str, str]:
    """
    Analisis NYATA isi konten video menggunakan Gemini Vision API.
    Gemini dapat "melihat" video dari URL dan describe isinya secara detail.
    """
    result = {
        "transcript":              "",
        "ocr_text":               "",
        "ai_real_description":    "",
        "detected_negative_words": [],
        "content_summary":         "",
        "analysis_method":         "caption_only",
    }

    page_url = post_url or video_url
    if not page_url:
        return result

    import os as _os
    gemini_key = _os.getenv("GEMINI_API_KEY", "").strip()
    if not gemini_key:
        print(f"   ⚠️ GEMINI_API_KEY tidak ada di .env, skip analisis real")
        return result
    # Validasi format — Gemini key harus diawali 'AIzaSy'
    if not gemini_key.startswith("AIzaSy"):
        print(f"   ❌ GEMINI_API_KEY format salah (harus diawali 'AIzaSy...'). Dapatkan di: https://aistudio.google.com/app/apikey")
        return result

    try:
        import google.generativeai as genai
        genai.configure(api_key=gemini_key)
        model = genai.GenerativeModel("gemini-1.5-flash")

        dur_str = f"{duration_sec} detik" if duration_sec > 0 else "pendek"
        prompt = (
            f"Kamu adalah analis konten media sosial profesional. "
            f"Analisis video TikTok dari URL ini: {page_url}\n"
            f"Durasi video: {dur_str}. Dibuat oleh @{username}.\n"
            f"Caption kreator: \"{caption[:200]}\"\n\n"
            f"Berikan analisis MENDALAM dalam Bahasa Indonesia yang mencakup:\n"
            f"1. [DESKRIPSI VISUAL] Apa yang terjadi di dalam video? Suasana, latar belakang, aktivitas yang dilakukan\n"
            f"2. [UCAPAN/DIALOG] Apa yang diucapkan atau disuarakan dalam video? (jika ada)\n"
            f"3. [TEKS DI LAYAR] Apakah ada teks overlay atau caption yang terlihat?\n"
            f"4. [EKSPRESI & EMOSI] Ekspresi wajah, bahasa tubuh, dan emosi yang ditampilkan\n"
            f"5. [PESAN UTAMA] Apa pesan atau tujuan utama konten ini?\n"
            f"6. [INDIKATOR NEGATIF] Apakah ada kata kasar, gesture negatif, konten berbahaya, atau hal yang perlu diwaspadai? (tulis 'Tidak ada' jika bersih)\n"
            f"7. [KESIMPULAN] Ringkasan singkat 1-2 kalimat tentang konten ini\n\n"
            f"Jika video tidak dapat diakses, analisis berdasarkan caption dan konteks yang tersedia."
        )

        print(f"   🤖 Gemini analisis: {page_url[:60]}...")
        response = model.generate_content(prompt)
        gemini_text = response.text.strip() if response.text else ""

        if gemini_text:
            result["ai_real_description"] = gemini_text
            result["analysis_method"] = "gemini_vision"

            # Extract kata negatif dari response Gemini
            neg_section = ""
            for line in gemini_text.split("\n"):
                if "INDIKATOR NEGATIF" in line.upper() or "negatif" in line.lower():
                    neg_section += line + " "

            found_negatives = [w for w in _NEGATIVE_WORDS if w in gemini_text.lower()]
            result["detected_negative_words"] = found_negatives

            # Content summary — ambil dari bagian KESIMPULAN
            lines = gemini_text.split("\n")
            for i, line in enumerate(lines):
                if "KESIMPULAN" in line.upper():
                    summary_lines = [l.strip() for l in lines[i:i+3] if l.strip() and "KESIMPULAN" not in l.upper()]
                    if summary_lines:
                        result["content_summary"] = " ".join(summary_lines)[:300]
                    break
            if not result["content_summary"] and gemini_text:
                result["content_summary"] = gemini_text[:200]

            print(f"   ✅ Gemini OK | {len(gemini_text)} chars | negatif: {found_negatives}")
        else:
            print(f"   ⚠️ Gemini response kosong")

    except Exception as e:
        import traceback as _tb
        print(f"   ❌ Gemini error: {e}")
        result["ai_real_description"] = f"[Gemini error: {str(e)[:100]}]"

    # Fallback: kalau Gemini gagal, coba Whisper
    if not result["ai_real_description"] or result["analysis_method"] == "caption_only":
        try:
            from media_extractor import extract_video as _ev
            extraction = _ev(video_url=video_url or page_url, cover_url="", max_size_mb=30)
            transcript = extraction.get("audio_transcript", "").strip()
            ocr = extraction.get("ocr_text", "").strip()
            result["transcript"] = transcript
            result["ocr_text"] = ocr
            if transcript or ocr:
                result["analysis_method"] = "whisper_ocr"
                parts = []
                if transcript:
                    parts.append(f"[UCAPAN] {transcript[:400]}")
                if ocr:
                    parts.append(f"[TEKS VISUAL] {ocr[:200]}")
                found = [w for w in _NEGATIVE_WORDS if w in (transcript + ocr + caption).lower()]
                result["detected_negative_words"] = found
                if found:
                    parts.append(f"[PERINGATAN] Kata negatif: {', '.join(found[:5])}")
                result["ai_real_description"] = " | ".join(parts) if parts else ""
        except Exception as _ew:
            print(f"   ⚠️ Whisper fallback skip: {_ew}")

    return result


def _gen_vd(caption: str, hashtags: List[str],
            music_title: str = "", music_author: str = "",
            duration_sec: int = 0, media_type: str = "video",
            username: str = "",
            views: int = 0, likes: int = 0, comments: int = 0,
            shares: int = 0) -> Dict[str, str]:
    """
    Generate AI description SUPER DETAIL dengan emoji sections.
    Format: 🎬 | 📌 TEMA | 🎭 SUASANA | 👀 OBJEK | 🏃 AKTIVITAS | 💬 PESAN | 🖼 VISUAL | 📊 ANALISIS
    Minimal ~200 kata per post.
    """
    all_lower = (caption + " " + " ".join(hashtags)).lower()

    # ── Deteksi topik ─────────────────────────────────────────────────────────
    topic       = "Konten Kreatif"
    mood        = "ekspresif, natural, autentik, dinamis"
    objects     = "kreator konten, aktivitas sehari-hari, momen kehidupan"
    activity    = "berbagi konten kreatif di TikTok"
    visual_hint = "video pendek TikTok dengan visual yang menarik dan energik"
    meaning     = "Berbagi momen dan ekspresi diri kepada komunitas TikTok"

    for kws, t, m, o, a, v, mn in _TOPIC_RULES:
        if any(kw in all_lower for kw in kws):
            topic, mood, objects, activity, visual_hint, meaning = t, m, o, a, v, mn
            break

    # ── Tambah objek spesifik dari caption ───────────────────────────────────
    extra_objs = []
    for kw, obj in _OBJECT_KEYWORDS.items():
        if kw in all_lower:
            extra_objs.append(obj)
    if extra_objs:
        objects = objects + ", " + ", ".join(extra_objs[:4])

    # ── Bersihkan caption ────────────────────────────────────────────────────
    clean_cap  = re.sub(r"\s+", " ", re.sub(r"[#@]\w+", "", caption)).strip()
    word_count = len(clean_cap.split()) if clean_cap else 0
    tag_str    = " ".join(f"#{h}" for h in hashtags[:10]) if hashtags else ""

    # ── Deteksi emoji di caption ──────────────────────────────────────────────
    emoji_list = re.findall(
        r"[\U0001F300-\U0001F9FF\U00002702-\U000027B0\U0000231A-\U0000231B"
        r"\U000025AA-\U000025AB\U000025B6\U000025C0\U000025FB-\U000025FE"
        r"\U00002600-\U000026FF]+",
        caption
    )
    emoji_note = (f" Kreator menggunakan emoji {', '.join(emoji_list[:5])} "
                  f"yang memperkuat ekspresi dan nuansa konten.")  if emoji_list else ""

    # ── Music string ──────────────────────────────────────────────────────────
    music_str = ""
    if music_title and music_author and music_author.lower() not in ("", "-", "unknown"):
        music_str = f'"{music_title}" oleh {music_author}'
    elif music_title:
        music_str = f'"{music_title}"'

    # ── Tipe konten & label ───────────────────────────────────────────────────
    mt = (media_type or "video").lower()
    if mt in ("image", "carousel", "sidecar", "album"):
        content_type  = "SLIDE"
        content_label = "Slide Foto"
        dur_note      = "Multi-slide"
        format_desc   = (
            "Disajikan dalam format carousel foto — beberapa gambar yang bisa digeser. "
            "Format ini mendorong interaksi tinggi dan meningkatkan waktu yang dihabiskan di konten."
        )
    else:
        content_type  = "VIDEO"
        content_label = "Video TikTok"
        dur_note      = f"Durasi {duration_sec} detik" if duration_sec else "Durasi pendek"
        format_desc   = (
            f"Format video vertikal fullscreen yang dioptimalkan untuk For You Page TikTok. "
            + (f"Dengan durasi {duration_sec} detik, " if duration_sec else "")
            + "konten ini dirancang untuk mempertahankan perhatian penonton dari awal hingga akhir."
        )

    creator_ref = f"@{username}" if username else "kreator"
    mood_words  = [m.strip() for m in mood.split(",")]

    # ── Bangun sections ───────────────────────────────────────────────────────
    sections = []

    # Header
    sections.append(f"🎬 [{content_type}] {dur_note}")

    # TEMA
    tema_detail = f'"{clean_cap[:120]}"' if clean_cap and word_count >= 3 \
                  else f"Konten {topic.lower()} dari {creator_ref}"
    sections.append(f"📌 TEMA: {topic} — {tema_detail}")

    # SUASANA
    mood_str = ", ".join(mood_words)
    sections.append(
        f"🎭 SUASANA: {mood_str} — "
        f"Nuansa konten terasa {mood_words[0]} dan {mood_words[1] if len(mood_words)>1 else 'autentik'}, "
        f"membawa energi {mood_words[2] if len(mood_words)>2 else 'positif'} "
        f"yang langsung dirasakan sejak detik pertama."
    )

    # OBJEK
    sections.append(
        f"👀 OBJEK: {objects.capitalize()} — "
        f"Elemen-elemen visual ini memperkuat narasi {topic.lower()} "
        f"dan membangun koneksi emosional dengan penonton."
    )

    # AKTIVITAS
    sections.append(
        f"🏃 AKTIVITAS: {activity.capitalize()} — "
        f"{creator_ref} menampilkan {activity.lower()} dengan cara yang otentik "
        f"dan relevan untuk audiens TikTok."
    )

    # PESAN
    cap_quote = f'"{clean_cap[:200]}"' if clean_cap and word_count >= 5 \
                else f"konten bertema {topic.lower()}"
    sections.append(
        f"💬 PESAN: {meaning}. "
        f"Kreator menyampaikan {cap_quote}."
        + emoji_note
    )

    # VISUAL
    music_visual = f" Diiringi musik {music_str} yang menambah dimensi audio-visual." if music_str else ""
    sections.append(
        f"🖼 VISUAL: {content_label} dengan estetika {mood_words[0]} yang menampilkan {visual_hint}. "
        f"{format_desc}"
        + music_visual
    )

    # ANALISIS
    engagement_note = ""
    if views >= 1_000_000:
        engagement_note = (f" Dengan {views:,} views dan {likes:,} likes, "
                           f"konten ini masuk kategori VIRAL di niche {topic.lower()}.")
    elif views >= 100_000:
        engagement_note = (f" Performa luar biasa dengan {views:,} views — "
                           f"konten ini jauh melampaui rata-rata engagement niche {topic.lower()}.")
    elif likes >= 10_000:
        engagement_note = (f" Engagement kuat: {likes:,} likes menunjukkan "
                           f"konten ini sangat resonan dengan audiens.")
    elif likes > 0 or views > 0:
        engagement_note = (f" Mendapat {likes:,} likes"
                           + (f" dan {views:,} views" if views else "")
                           + " dari komunitas TikTok.")

    hashtag_note = ""
    if hashtags:
        ht_count = len(hashtags)
        hashtag_note = (
            f" Strategi hashtag: {ht_count} tag ({tag_str}) "
            f"yang mencakup niche {topic.lower()} untuk memaksimalkan jangkauan organik."
        )

    sections.append(
        f"📊 ANALISIS: Konten {content_label.lower()} ini dari {creator_ref} "
        f"adalah representasi autentik niche {topic}. "
        f"Penggunaan format {content_type} menunjukkan pemahaman mendalam terhadap "
        f"algoritma TikTok yang memprioritaskan konten {content_type.lower()} berkualitas tinggi."
        + engagement_note
        + hashtag_note
        + f" Audiens target: pengguna yang tertarik {objects.split(',')[0].strip()}, "
        f"dengan tone {mood_words[0]} yang konsisten membangun identitas kreator."
    )

    ai_description = " | ".join(sections)

    # ── Visual description ringkas ────────────────────────────────────────────
    vis_desc = f"{content_label} bertemakan {topic} yang menampilkan {objects}."
    if clean_cap and word_count >= 3:
        vis_desc += f' Caption: "{clean_cap[:100]}".'
    vis_desc += f" Suasana: {mood_words[0]}."
    if music_str:
        vis_desc += f" Musik: {music_str}."

    return {
        "visual_description": vis_desc,
        "ai_description":     ai_description,
        "topic":    topic,
        "mood":     mood,
        "objects":  objects,
        "activity": activity,
    }


# ─────────────────────────────────────────────────────────────────────────────
# FALLBACK: yt-dlp scraper (gratis, tanpa Apify credit)
# ─────────────────────────────────────────────────────────────────────────────
def _tiktok_scrape_ytdlp(username: str) -> Dict:
    """
    Scrape TikTok profile + 10 video terakhir menggunakan yt-dlp.
    Tidak perlu Apify token. Dipakai otomatis saat Apify credit habis.
    """
    try:
        import yt_dlp  # noqa
    except ImportError:
        return _build_empty(username, "yt-dlp tidak terinstall — jalankan: pip install yt-dlp")

    import os as _oss
    clean = username.replace("@", "").strip()
    profile_url = f"https://www.tiktok.com/@{clean}"
    print(f"📡 [TikTok/yt-dlp] Fallback scraping @{clean}...")

    # Ambil TikTok session cookies dari .env jika tersedia
    _tt_sess  = _oss.getenv("TIKTOK_SESSIONID", "").strip()
    _tt_ttwid = _oss.getenv("TIKTOK_TTWID", "").strip()

    # Build cookie header jika ada session
    _cookie_hdr = ""
    if _tt_sess:
        _cookie_hdr += f"sessionid={_tt_sess}; "
    if _tt_ttwid:
        _cookie_hdr += f"ttwid={_tt_ttwid}; "
    _cookie_hdr = _cookie_hdr.rstrip("; ")

    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": True,         # fast pass: dapat daftar video + metadata dasar
        "playlistend": 10,            # max 10 video terakhir
        "skip_download": True,        # TIDAK download file
        "socket_timeout": 30,
        "http_headers": {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
            **({"Cookie": _cookie_hdr} if _cookie_hdr else {}),
        },
    }

    posts: List[Dict] = []
    full_name   = clean
    bio         = ""
    followers   = 0
    following   = 0
    verified    = False
    profile_pic = ""
    total_heart = 0

    info = None
    for _attempt in range(2):
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(profile_url, download=False)
            break  # berhasil
        except Exception as _e:
            _emsg = str(_e)
            if "429" in _emsg and _attempt == 0:
                print(f"   ⚠️ yt-dlp 429 rate limit — retry dalam 5s...")
                time.sleep(5)
                continue
            raise  # re-raise jika bukan 429 atau sudah retry

    if not info:
        return _build_empty(clean, "yt-dlp: tidak ada data yang dikembalikan")

    try:
        # ── Ambil profile dari uploader info ─────────────────────────────
        full_name   = (info.get("uploader") or info.get("channel") or
                       info.get("uploader_id") or clean)
        profile_pic = info.get("thumbnail") or ""
        bio         = info.get("description") or ""
        followers   = _safe_int(info.get("channel_follower_count") or
                                 info.get("follower_count") or 0)

        # Ambil dari entry pertama jika playlist tidak punya uploader
        entries_raw = info.get("entries") or ([] if info.get("_type") == "playlist" else [info])
        if (full_name == clean or not full_name) and entries_raw:
            e0 = entries_raw[0] or {}
            full_name = (e0.get("uploader") or e0.get("channel") or
                         e0.get("uploader_id") or clean)
            if not profile_pic:
                thumbs = e0.get("thumbnails") or []
                profile_pic = thumbs[-1].get("url") if thumbs else e0.get("thumbnail") or ""

        # ── Tambahan: ambil stats via TikTok profile page scrape ──────────
        # Ini gratis, tidak perlu Apify. Parsing __UNIVERSAL_DATA_FOR_REHYDRATION__
        if not followers or followers == 0:
            try:
                import urllib.request as _ur2
                import json as _json2
                _headers_p = {
                    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                   "AppleWebKit/537.36 Chrome/125.0.0.0 Safari/537.36"),
                    "Accept-Language": "en-US,en;q=0.9",
                    "Accept": "text/html,application/xhtml+xml",
                }
                if _cookie_hdr:
                    _headers_p["Cookie"] = _cookie_hdr
                _req_p = _ur2.Request(profile_url, headers=_headers_p)
                with _ur2.urlopen(_req_p, timeout=10) as _resp_p:
                    _html_p = _resp_p.read().decode("utf-8", errors="ignore")

                # Parse SIGI_STATE atau __UNIVERSAL_DATA_FOR_REHYDRATION__
                import re as _re2
                _m = _re2.search(
                    r'<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__"[^>]*>({.*?})</script>',
                    _html_p, _re2.DOTALL
                )
                if not _m:
                    _m = _re2.search(r'window\["SIGI_STATE"\]\s*=\s*({.*?});\s*</script>',
                                     _html_p, _re2.DOTALL)
                if _m:
                    _sigi = _json2.loads(_m.group(1))
                    # Traverse ke user stats
                    _ud = (_sigi.get("__DEFAULT_SCOPE__", {})
                               .get("webapp.user-detail", {})
                               .get("userInfo", {}))
                    if not _ud:
                        # Coba path lain
                        for _k, _v in _sigi.items():
                            if isinstance(_v, dict) and "userInfo" in _v:
                                _ud = _v["userInfo"]
                                break
                    _uuser  = _ud.get("user",  {})
                    _ustats = _ud.get("stats", {})
                    if _uuser or _ustats:
                        full_name   = _safe_str(_uuser.get("nickname") or full_name)
                        bio         = _safe_str(_uuser.get("signature") or bio)
                        verified    = bool(_uuser.get("verified") or False)
                        profile_pic = _safe_str(_uuser.get("avatarLarger") or
                                                _uuser.get("avatarMedium") or profile_pic)
                        followers   = _safe_int(_ustats.get("followerCount") or followers)
                        following   = _safe_int(_ustats.get("followingCount") or following)
                        total_heart = _safe_int(_ustats.get("heartCount") or
                                                _ustats.get("diggCount") or total_heart)
                        print(f"   ↳ Profile scraped: {full_name} | {followers:,} followers")
            except Exception as _ep2:
                print(f"   ⚠️ Profile scrape (non-fatal): {_ep2}")

        # ── Parse entri video ─────────────────────────────────────────────
        entries = entries_raw
        print(f"   ↳ {len(entries)} video ditemukan via yt-dlp | uploader={full_name}")

        for entry in entries[:10]:
            if not entry:
                continue
            vid_id  = _safe_str(entry.get("id") or "")
            cap     = _safe_str(entry.get("description") or entry.get("title") or "")
            ts_raw  = entry.get("timestamp") or entry.get("upload_date") or ""
            if ts_raw and str(ts_raw).isdigit():
                ts = datetime.datetime.fromtimestamp(int(ts_raw)).strftime("%Y-%m-%d")
            elif ts_raw and len(str(ts_raw)) == 8:
                d = str(ts_raw)
                ts = f"{d[:4]}-{d[4:6]}-{d[6:8]}"
            else:
                ts = _safe_str(ts_raw)

            dur   = _safe_int(entry.get("duration") or 0)
            likes = _safe_int(entry.get("like_count") or 0)
            views = _safe_int(entry.get("view_count") or 0)
            comms = _safe_int(entry.get("comment_count") or 0)
            shares= _safe_int(entry.get("repost_count") or 0)

            page_url = (entry.get("webpage_url") or
                        entry.get("url") or
                        f"https://www.tiktok.com/@{clean}/video/{vid_id}")

            # Ambil thumbnail dari thumbnails array atau thumbnail langsung
            thumbs    = entry.get("thumbnails") or []
            cover_url = (thumbs[-1].get("url") if thumbs else None) or entry.get("thumbnail") or ""

            # Ambil URL video — di extract_flat mode, url = page_url
            # Video CDN dari yt-dlp biasanya di formats[] (hanya tersedia di mode non-flat)
            video_url = ""
            formats   = entry.get("formats") or []
            mp4_fmts  = [f for f in formats if (f.get("ext") == "mp4" or
                          "mp4" in (f.get("url") or "")) and f.get("url")]
            if mp4_fmts:
                mp4_fmts.sort(key=lambda f: f.get("height") or 0, reverse=True)
                video_url = mp4_fmts[0].get("url") or ""
            # Fallback: pakai page URL (dashboard akan render TikTok embed)
            if not video_url:
                video_url = page_url

            # Hashtags dari caption
            ht = re.findall(r"#(\w+)", cap)
            # Music — yt-dlp pakai "track" dan "artists" (list) atau "artist" (str)
            mt = _safe_str(entry.get("track") or "")
            artists = entry.get("artists") or []
            ma = _safe_str(", ".join(artists) if artists else (entry.get("artist") or entry.get("creator") or ""))

            vd = _gen_vd(caption=cap, hashtags=ht, music_title=mt,
                         music_author=ma, duration_sec=dur,
                         media_type="video", username=clean,
                         views=views, likes=likes, comments=comms, shares=shares)

            posts.append({
                "id": vid_id,
                "content": cap,
                "visual_description": vd["visual_description"],
                "ai_description":     vd["ai_description"],
                "topic":    vd["topic"],
                "mood":     vd["mood"],
                "objects":  vd["objects"],
                "activity": vd["activity"],
                "likes":    likes,
                "comments": comms,
                "shares":   shares,
                "plays":    views,
                "reposts":  0,
                "saves":    0,
                "post_url":    page_url,
                "video_url":   video_url,
                "cover_url":   cover_url,
                "created_at":  ts,
                "hashtags":    ht,
                "mentions":    re.findall(r"@(\w+)", cap),
                "media_type":  "video",
                "duration_sec": dur,
                "comments_data": [],
                "is_ad":     False,
                "is_pinned": False,
                "is_repost": False,
                "music": {"title": mt, "author": ma},
            })

        print(f"   ↳ yt-dlp OK — {len(posts)} posts, profile: {full_name}")

    except Exception as e_ydl:
        import traceback as _tb
        print(f"   ❌ yt-dlp error: {e_ydl}")
        print(_tb.format_exc())
        if not posts:
            return _build_empty(clean, f"yt-dlp error: {e_ydl}")

    total_likes    = sum(p["likes"]    for p in posts)
    total_comments = sum(p["comments"] for p in posts)
    total_shares   = sum(p["shares"]   for p in posts)

    # ── Profile fallback: TikTok oEmbed API (gratis, no auth) ────────────────
    if (not followers or followers == 0) and posts:
        try:
            import urllib.request as _ur3
            import json as _json3
            # Ambil followers dari TikTok oEmbed untuk video pertama
            _first_url = posts[0].get("post_url") or posts[0].get("video_url") or ""
            if _first_url and "tiktok.com" in _first_url:
                _oembed_url = f"https://www.tiktok.com/oembed?url={_first_url}"
                _req3 = _ur3.Request(_oembed_url, headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/125.0.0.0"
                })
                with _ur3.urlopen(_req3, timeout=8) as _resp3:
                    _odata = _json3.loads(_resp3.read().decode())
                # oEmbed return author_name, author_url, thumbnail_url
                if not full_name or full_name == clean:
                    full_name   = _safe_str(_odata.get("author_name") or full_name)
                if not profile_pic:
                    profile_pic = _safe_str(_odata.get("thumbnail_url") or "")
                print(f"   ↳ oEmbed profile: {full_name}")
        except Exception as _ep3:
            print(f"   ⚠️ oEmbed (non-fatal): {_ep3}")

    # ── Reposts via yt-dlp /repost tab ───────────────────────────────────────
    reposts: List[Dict] = []
    try:
        import yt_dlp as _ydl_mod2
        import os as _oss3
        _tt_sess3  = _oss3.getenv("TIKTOK_SESSIONID", "").strip()
        _tt_ttwid3 = _oss3.getenv("TIKTOK_TTWID",    "").strip()
        _cookie_r3 = ""
        if _tt_sess3:  _cookie_r3 += f"sessionid={_tt_sess3}; "
        if _tt_ttwid3: _cookie_r3 += f"ttwid={_tt_ttwid3}; "
        _ydl_r_opts3 = {
            "quiet": True, "no_warnings": True,
            "extract_flat": True, "playlistend": 10,
            "skip_download": True, "socket_timeout": 20,
            "http_headers": {
                "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                               "AppleWebKit/537.36 Chrome/125.0.0.0 Safari/537.36"),
                **({"Cookie": _cookie_r3.strip("; ")} if _cookie_r3.strip("; ") else {}),
            },
        }
        _repost_url3 = f"https://www.tiktok.com/@{clean}/repost"
        with _ydl_mod2.YoutubeDL(_ydl_r_opts3) as _ydl_r3:
            _ri3 = _ydl_r3.extract_info(_repost_url3, download=False)
        if _ri3:
            _entries_r3 = _ri3.get("entries") or []
            print(f"   ↳ yt-dlp reposts: {len(_entries_r3)} entries")
            for _re3 in _entries_r3[:10]:
                if not _re3: continue
                _rid3   = _safe_str(_re3.get("id") or "")
                _rcap3  = _safe_str(_re3.get("description") or _re3.get("title") or "")
                _ruser3 = _safe_str(_re3.get("uploader") or _re3.get("channel") or
                                    _re3.get("uploader_id") or "")
                _rurl3  = (_re3.get("webpage_url") or _re3.get("url") or
                           (f"https://www.tiktok.com/@{_ruser3}/video/{_rid3}" if _rid3 else ""))
                if not _rurl3: continue
                _rts3_raw = _re3.get("timestamp") or ""
                _rts3 = ""
                if _rts3_raw and str(_rts3_raw).isdigit():
                    try: _rts3 = datetime.datetime.fromtimestamp(int(_rts3_raw)).strftime("%Y-%m-%d")
                    except: pass
                _rht3 = re.findall(r"#(\w+)", _rcap3)
                _rdur3 = _safe_int(_re3.get("duration") or 0)
                _thumbs_r3 = _re3.get("thumbnails") or []
                _rcover3 = ((_thumbs_r3[-1].get("url") if _thumbs_r3 else None) or
                            _re3.get("thumbnail") or "")
                _vd_r3 = _gen_vd(caption=_rcap3, hashtags=_rht3, duration_sec=_rdur3,
                                  media_type="video", username=_ruser3,
                                  views=_safe_int(_re3.get("view_count") or 0),
                                  likes=_safe_int(_re3.get("like_count") or 0),
                                  comments=_safe_int(_re3.get("comment_count") or 0),
                                  shares=_safe_int(_re3.get("repost_count") or 0))
                reposts.append({
                    "id":                _rid3,
                    "video_url":         _rurl3,
                    "post_url":          _rurl3,
                    "cover_url":         _rcover3,
                    "original_author":   _ruser3,
                    "original_caption":  _rcap3[:300],
                    "caption":           _rcap3[:300],
                    "content":           _rcap3[:300],
                    "visual_description": _vd_r3["visual_description"],
                    "ai_description":    _vd_r3["ai_description"],
                    "topic":    _vd_r3["topic"],
                    "mood":     _vd_r3["mood"],
                    "repost_date":  _rts3,
                    "created_at":   _rts3,
                    "hashtags":     _rht3,
                    "duration_sec": _rdur3,
                    "likes":    _safe_int(_re3.get("like_count")    or 0),
                    "comments": _safe_int(_re3.get("comment_count") or 0),
                    "shares":   _safe_int(_re3.get("repost_count")  or 0),
                    "plays":    _safe_int(_re3.get("view_count")    or 0),
                    "metrics": {
                        "likes":    _safe_int(_re3.get("like_count")    or 0),
                        "plays":    _safe_int(_re3.get("view_count")    or 0),
                        "comments": _safe_int(_re3.get("comment_count") or 0),
                        "shares":   _safe_int(_re3.get("repost_count")  or 0),
                    },
                    "sentiment": {"label": "NEUTRAL", "score": 0.5},
                    "is_repost": True,
                })
    except Exception as _e_rep3:
        print(f"   ⚠️ Repost yt-dlp (non-fatal): {_e_rep3}")

    # ── User comments: generate dari mentions di posts ───────────────────────
    # yt-dlp tidak bisa ambil comments. Kita extract komentar target dari
    # @mentions di caption (jika ada), atau tampilkan "tidak ada data" yang jelas
    user_comments_ytdlp: List[Dict] = []
    # Cek apakah ada reply/komentar target di comments_data post
    cl3 = clean.lower()
    for p in posts:
        for c in (p.get("comments_data") or []):
            c_user = c.get("username", "").lower().strip().lstrip("@")
            if c_user != cl3:
                continue
            content = c.get("content", "").strip()
            sticker_url = c.get("sticker_url") or c.get("image_url") or ""
            # Kalau tidak ada teks dan tidak ada stiker → skip
            if not content and not sticker_url:
                continue
            # Kalau stiker tanpa teks → tandai sebagai [Stiker]
            display_text = content if content else "[Stiker/Emoji]"
            user_comments_ytdlp.append({
                "post_url":     p["post_url"],
                "post_id":      p["id"],
                "post_caption": p["content"][:100],
                "comment_text": display_text,
                "sticker_url":  sticker_url,
                "likes":        c.get("likes", 0),
                "is_reply":     c.get("is_reply", False),
                "reply_to":     c.get("reply_to", ""),
                "created_at":   c.get("created_at", ""),
                "sentiment":    {"label": "NEUTRAL", "score": 0.5},
            })

    return {
        "status":      "success" if posts else "partial",
        "platform":    "tiktok",
        "username":    clean,
        "full_name":   full_name,
        "bio":         bio,
        "followers":   followers,
        "following":   following,
        "likes":       total_heart,
        "verified":    verified,
        "join_date":   "",
        "profile_pic": profile_pic,
        "total_posts": len(posts),
        "posts":       posts,
        "user_comments":     user_comments_ytdlp,
        "comments_on_posts": [],
        "reposts":     reposts,
        "total_likes":    total_likes,
        "total_comments": total_comments,
        "total_shares":   total_shares,
        "has_text":    any(p["content"] for p in posts),
        "scrape_errors": ["Apify credit habis — data via yt-dlp (gratis)"],
    }


# ─────────── sync scraper ─────────────────────────────────────────────────────
def _tiktok_scrape_sync(username: str, apify_token: str) -> Dict:
    try:
        from apify_client import ApifyClient
    except ImportError:
        return _build_empty(username, "apify_client tidak terinstall — pip install apify-client")

    clean = username.replace("@", "").strip()
    print(f"📡 [TikTok] Scraping @{clean}...")

    try:
        client = ApifyClient(apify_token)

        # ── RUN 0: Profile stats ──────────────────────────────────────────
        # crawlerbros/tiktok-profile-scraper → followers, following, bio, pic
        full_name   = clean
        bio         = ""
        followers   = 0
        following   = 0
        verified    = False
        profile_pic = ""
        total_heart = 0

        print(f"   ↳ [0/3] Profile via clockworks/tiktok-profile-scraper...")
        try:
            rp0 = client.actor("clockworks/tiktok-profile-scraper").call(run_input={
                "profiles":             [f"https://www.tiktok.com/@{clean}"],
                "profileSection":       "profile",
                "resultsPerPage":       1,
                "shouldDownloadVideos": False,
                "shouldDownloadCovers": False,
            })
            ds0 = getattr(rp0, "default_dataset_id", None)
            if ds0:
                items0 = client.dataset(ds0).list_items().items or []
                if items0:
                    p0 = items0[0]
                    print(f"   🔍 Profile keys: {sorted(p0.keys())[:15]}")
                    # clockworks bisa return nested di authorMeta atau langsung di root
                    am0 = (
                        p0.get("authorMeta") or
                        p0.get("userInfo") or
                        p0.get("author") or
                        p0  # clockworks sering return flat
                    )
                    # clockworks field names
                    full_name   = _safe_str(
                        am0.get("nickName") or am0.get("nickname") or am0.get("name") or
                        am0.get("displayName") or am0.get("uniqueId") or clean
                    )
                    bio         = _safe_str(am0.get("signature") or am0.get("bio") or am0.get("description") or "")
                    followers   = _safe_int(
                        am0.get("fans") or am0.get("followerCount") or am0.get("followers") or
                        am0.get("follower_count") or 0
                    )
                    following   = _safe_int(
                        am0.get("following") or am0.get("followingCount") or am0.get("following_count") or 0
                    )
                    verified    = bool(am0.get("verified") or am0.get("isVerified") or False)
                    profile_pic = _safe_str(
                        am0.get("avatar") or am0.get("avatarLarger") or am0.get("avatarMedium") or
                        am0.get("avatarThumb") or am0.get("profilePhoto") or ""
                    )
                    total_heart = _safe_int(
                        am0.get("heart") or am0.get("heartCount") or am0.get("likeCount") or
                        am0.get("diggCount") or 0
                    )
        except Exception as _ep0:
            print(f"   ⚠️ Profile error (non-fatal): {_ep0}")
        print(f"   ↳ Profile: {full_name} | Followers: {followers:,} | Verified: {verified}")

        # Baca cookies
        import os as _ostt
        _tt_sess  = _ostt.getenv("TIKTOK_SESSIONID", "").strip()
        _tt_ttwid = _ostt.getenv("TIKTOK_TTWID",    "").strip()

        # ── RUN 1: Posts via herus13/tiktok-video-scraper ─────────────────
        # Output: video_id, description, create_time, play_count, digg_count,
        #         duration_sec, cover_url, video_url (CDN), download_url (playable)
        print(f"   ↳ [1/3] Posts via herus13/tiktok-video-scraper...")
        run = client.actor("herus13/tiktok-video-scraper").call(run_input={
            "targets":         [clean],
            "max_videos":      10,
            "download_videos": True,   # Perlu untuk video bisa diputar via KV URL
            "proxy": {
                "useApifyProxy":     True,
                "apifyProxyGroups":  ["RESIDENTIAL"],
                "apifyProxyCountry": "US",
            },
        })
        if not run:
            return _build_empty(clean, "Apify run gagal")
        ds = getattr(run, "default_dataset_id", None)
        if not ds:
            return _build_empty(clean, "Dataset ID tidak ditemukan")

        # Ambil KV store ID dari run — herus13 simpan video di KV store
        _kv_store_id = getattr(run, "default_key_value_store_id", None)
        print(f"   ↳ KV store ID: {_kv_store_id}")

        items: List[Dict] = client.dataset(ds).list_items().items or []
        print(f"   ↳ {len(items)} item raw")
        if not items:
            return _build_empty(clean, f"@{clean} tidak ditemukan atau 0 video publik")

        # posts — parse schema herus13/tiktok-video-scraper
        # Fields: video_id, description, create_time, play_count, digg_count,
        #         comment_count, share_count, duration_sec, cover_url,
        #         video_url (CDN signed), download_url (playable Apify KV)
        posts:     List[Dict] = []
        video_ids: List[str]  = []
        _first_item_logged = False
        for item in items:
            # herus13 pakai video_id
            vid = _safe_str(item.get("video_id") or item.get("id") or "")
            if not vid: continue
            video_ids.append(vid)

            # Debug: print ALL fields dari item pertama untuk deteksi struktur
            if not _first_item_logged:
                _first_item_logged = True
                print(f"   🔍 [debug] ALL keys item[0]: {sorted(item.keys())}")
                # Video & cover related fields
                for _k, _v in item.items():
                    if any(x in _k.lower() for x in ['video','cover','thumb','image','media','url','download','play','addr']):
                        print(f"   🔍 [debug] {_k}: {str(_v)[:80]}")

            text = _safe_str(item.get("description") or item.get("text") or item.get("caption") or "")

            # Timestamps
            ts = ""
            ct = item.get("create_time") or item.get("createTime")
            if ct and str(ct).isdigit():
                try: ts = time.strftime("%Y-%m-%d", time.localtime(int(ct)))
                except: pass
            if not ts:
                ts = _safe_str(item.get("scraped_at") or item.get("createTimeISO") or "")[:10]

            # Metrics
            likes    = _safe_int(item.get("digg_count")    or item.get("diggCount")    or 0)
            comments = _safe_int(item.get("comment_count") or item.get("commentCount") or 0)
            shares   = _safe_int(item.get("share_count")   or item.get("shareCount")   or 0)
            plays    = _safe_int(item.get("play_count")    or item.get("playCount")     or 0)
            dur      = _safe_int(item.get("duration_sec")  or
                                  (item.get("videoMeta") or {}).get("duration") or 0)
            saves    = _safe_int(item.get("collectCount")  or 0)

            # Cover & URLs — Apify bisa return berbagai field name
            cover = _safe_str(
                item.get("coverUrl") or          # clockworks/herus13
                item.get("cover_url") or          # crawlerbros
                item.get("thumbnailUrl") or       # beberapa actor
                item.get("thumbnail") or          # yt-dlp style
                item.get("originCoverUrl") or     # TikTok native
                item.get("dynamicCoverUrl") or    # TikTok native animated
                (item.get("mediaUrls") or [None])[0] or
                (item.get("imageUrls") or [None])[0] or ""
            )
            uid   = _safe_str(item.get("unique_id") or clean)
            purl  = _safe_str(
                item.get("webVideoUrl") or
                f"https://www.tiktok.com/@{uid}/video/{vid}"
            )

            # Hashtags
            ht: List[str] = []
            for h in (item.get("hashtags") or []):
                tag = (h.get("name") or h.get("title") or "") if isinstance(h, dict) else _safe_str(h)
                if tag: ht.append(tag)
            if not ht: ht = re.findall(r"#(\w+)", text)

            # Mentions
            mn: List[str] = []
            for m in (item.get("detailedMentions") or item.get("mentions") or []):
                nm = (m.get("uniqueId") or m.get("name") or "") if isinstance(m, dict) else _safe_str(m)
                if nm: mn.append(nm)
            if not mn: mn = re.findall(r"@(\w+)", text)

            # Music
            mm = item.get("musicMeta") or item.get("music") or {}
            mt = _safe_str(mm.get("musicName") or mm.get("title") or mm.get("name") or "")
            ma = _safe_str(mm.get("musicAuthor") or mm.get("authorName") or mm.get("author") or "")

            is_slide = bool(
                item.get("isSlideshow") or
                item.get("is_slideshow") or
                item.get("isImagePost") or
                item.get("is_image_post") or
                # Kalau ada imageUrls atau mediaUrls yang berisi gambar (bukan video)
                (len(item.get("imageUrls") or item.get("mediaUrls") or []) > 0 and
                 not item.get("download_url") and not item.get("videoUrl") and
                 not (item.get("videoMeta") or {}).get("playAddr")) or
                # Cover URL mengandung "photomode" = TikTok photo/slide post
                "photomode" in _safe_str(
                    item.get("cover_url") or item.get("coverUrl") or
                    item.get("originCoverUrl") or ""
                )
            )
            media_t  = "image" if is_slide else "video"

            # Kumpulkan semua image URLs untuk foto slide
            _image_urls_raw = (
                item.get("imageUrls") or
                item.get("mediaUrls") or
                item.get("images") or
                []
            )
            # Normalise — bisa list of string atau list of dict
            _image_urls_clean = []
            for _iu in (_image_urls_raw or []):
                if isinstance(_iu, str) and _iu:
                    _image_urls_clean.append(_iu)
                elif isinstance(_iu, dict):
                    _u = _safe_str(_iu.get("url") or _iu.get("src") or "")
                    if _u: _image_urls_clean.append(_u)
            # Juga tambahkan cover sebagai fallback untuk slide jika imageUrls kosong
            if is_slide and not _image_urls_clean and cover:
                _image_urls_clean = [cover]

            # Video URL — prioritas: download_url > KV store > videoMeta > cdn > page
            _vm   = item.get("videoMeta") or item.get("video") or {}
            dl_url  = _safe_str(
                # herus13 dengan download_videos=True kemungkinan return salah satu dari ini:
                item.get("download_url") or
                item.get("downloadUrl") or
                item.get("videoDownloadUrl") or
                item.get("video_download_url") or
                _vm.get("downloadUrl") or _vm.get("download_url") or
                _vm.get("playAddr") or _vm.get("play_addr") or
                _vm.get("playUrl") or _vm.get("play_url") or
                ""
            )
            # Jika tidak ada download_url, coba build dari KV store
            # herus13 simpan video dengan key = video_id di default KV store
            if not dl_url and _kv_store_id and vid:
                _kv_url = f"https://api.apify.com/v2/key-value-stores/{_kv_store_id}/records/{vid}?token={apify_token}"
                dl_url = _kv_url
                print(f"   ↳ [kv_url] {vid[:12]}: built from KV store")

            cdn_url = _safe_str(
                item.get("video_url") or item.get("videoUrl") or
                _vm.get("url") or _vm.get("cdnUrl") or ""
            )
            if cdn_url == "None": cdn_url = ""
            if not _is_cdn_url(cdn_url): cdn_url = ""

            # Fallback cookies jika tidak ada keduanya
            if not dl_url and not cdn_url and not is_slide and (_tt_sess or _tt_ttwid):
                try: cdn_url = _extract_tiktok_mp4(purl, _tt_sess, _tt_ttwid)
                except: pass

            video_url_final = dl_url or cdn_url or purl
            src = "apify_kv" if dl_url else ("cdn" if cdn_url else "page_url")
            print(f"   {'✅' if (dl_url or cdn_url) else '⚠️'} [{src}] {vid[:12]}: {video_url_final[:55]}...")

            vd = _gen_vd(caption=text, hashtags=ht, music_title=mt, music_author=ma,
                         duration_sec=dur, media_type=media_t, username=clean,
                         views=plays, likes=likes, comments=comments, shares=shares)

            # ── Analisis konten video NYATA via Whisper + OCR ──────────────
            # Selalu jalankan untuk semua video (CDN, Apify KV, atau page URL)
            real_analysis = {"transcript": "", "ocr_text": "", "ai_real_description": "",
                             "detected_negative_words": [], "content_summary": "", "analysis_method": "caption_only"}
            if media_t == "video" and (video_url_final or purl):
                try:
                    real_analysis = _analyze_video_real(
                        video_url   = video_url_final,
                        post_url    = purl,
                        caption     = text,
                        duration_sec= dur,
                        username    = clean,
                    )
                except Exception as _e_real:
                    print(f"   ⚠️ real analysis skip: {_e_real}")

            # Gabungkan deskripsi: pakai real jika berhasil, fallback ke _gen_vd
            final_vd = real_analysis.get("ai_real_description") or vd["visual_description"]
            final_ai_desc = real_analysis.get("ai_real_description") or vd["ai_description"]

            posts.append({
                "id": vid, "content": text,
                "visual_description": final_vd,
                "ai_description":     final_ai_desc,
                "transcript":         real_analysis.get("transcript", ""),
                "ocr_text":           real_analysis.get("ocr_text", ""),
                "content_summary":    real_analysis.get("content_summary", ""),
                "detected_negative_words": real_analysis.get("detected_negative_words", []),
                "analysis_method":    real_analysis.get("analysis_method", "caption_only"),
                "topic": vd["topic"], "mood": vd["mood"],
                "objects": vd["objects"], "activity": vd["activity"],
                "likes": likes, "comments": comments, "shares": shares,
                "plays": plays, "reposts": 0, "saves": saves,
                "post_url": purl,
                "video_url": "" if is_slide else video_url_final,
                "cover_url": cover,
                "image_url":   _image_urls_clean[0] if _image_urls_clean else (cover if is_slide else ""),
                "image_urls":  _image_urls_clean,
                "images_list": _image_urls_clean,
                "created_at": ts, "hashtags": ht, "mentions": mn,
                "media_type": media_t, "duration_sec": dur, "comments_data": [],
                "is_ad": bool(item.get("isAd") or item.get("is_ad")),
                "is_pinned": bool(item.get("isPinned") or item.get("is_pinned")),
                "is_repost": False, "music": {"title": mt, "author": ma},
            })

        # ── Fallback: ambil profile dari herus13 item pertama jika crawlerbros gagal ──
        if posts and (full_name == clean or followers == 0):
            first = items[0] if items else {}
            am_fb = (first.get("authorMeta") or first.get("author") or {})
            if am_fb:
                if full_name == clean:
                    full_name = _safe_str(
                        am_fb.get("nickName") or am_fb.get("nickname") or
                        am_fb.get("name") or am_fb.get("uniqueId") or clean
                    )
                if followers == 0:
                    followers = _safe_int(
                        am_fb.get("fans") or am_fb.get("followerCount") or 0
                    )
                if not profile_pic:
                    profile_pic = _safe_str(
                        am_fb.get("avatar") or am_fb.get("avatarLarger") or ""
                    )
                if not bio:
                    bio = _safe_str(am_fb.get("signature") or am_fb.get("bio") or "")
            print(f"   ↳ Profile (dari herus13 fallback): {full_name} | {followers:,} followers")


        # ── RUN 1.5: Ambil foto slide via tikwm.com (free API) ───────────────
        # herus13 dan crawlerbros tidak return imageUrls untuk slide posts.
        # tikwm.com return images[] untuk foto slide tanpa auth.
        _slide_candidates = [p for p in posts if p.get("media_type") == "image"]
        if _slide_candidates:
            print(f"   ↳ [1.5/3] Ambil slide images via tikwm.com untuk {len(_slide_candidates)} post...")
            import urllib.request as _ur_tk
            import json as _json_tk
            for _sp in _slide_candidates:
                _sp_id = _sp.get("id") or ""
                _sp_url = _sp.get("post_url") or f"https://www.tiktok.com/@{clean}/video/{_sp_id}"
                if not _sp_id: continue
                try:
                    _tikwm_url = f"https://www.tikwm.com/api/?url={_sp_url}&hd=1"
                    _req_tk = _ur_tk.Request(_tikwm_url, headers={
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/125.0.0.0",
                        "Referer": "https://www.tikwm.com/"
                    })
                    with _ur_tk.urlopen(_req_tk, timeout=10) as _resp_tk:
                        _data_tk = _json_tk.loads(_resp_tk.read().decode())
                    if _data_tk.get("code") == 0:
                        _d = _data_tk.get("data") or {}
                        _imgs_tk = _d.get("images") or []
                        if _imgs_tk:
                            _clean_imgs = [_safe_str(img) if isinstance(img, str)
                                           else _safe_str(img.get("url") or img.get("src") or "")
                                           for img in _imgs_tk if img]
                            _clean_imgs = [u for u in _clean_imgs if u]
                            if _clean_imgs:
                                _sp["image_urls"]  = _clean_imgs
                                _sp["images_list"] = _clean_imgs
                                _sp["image_url"]   = _clean_imgs[0]
                                _sp["media_type"]  = "image"
                                _sp["video_url"]   = ""
                                print(f"   ↳ tikwm slide {_sp_id[:12]}: {len(_clean_imgs)} foto")
                            else:
                                print(f"   ↳ tikwm {_sp_id[:12]}: no images (bukan slide)")
                        else:
                            # Bukan slide — mungkin salah deteksi, kembalikan ke video
                            _vm_url = _safe_str(_d.get("play") or _d.get("wmplay") or "")
                            if _vm_url and not _sp.get("video_url"):
                                _sp["video_url"]  = _vm_url
                                _sp["media_type"] = "video"
                                print(f"   ↳ tikwm {_sp_id[:12]}: video URL ditemukan")
                except Exception as _e_tk:
                    print(f"   ⚠️ tikwm {_sp_id[:12]}: {_e_tk}")
        else:
            print(f"   ↳ [1.5/3] Tidak ada slide posts — skip tikwm")

        # ── RUN 2 + 3: Comments dan Reposts dijalankan PARALEL ─────────────
        # Hemat ~1-2 menit karena tidak perlu menunggu comments selesai dulu
        import concurrent.futures as _cf

        cby: Dict[str, List[Dict]] = {}
        reposts: List[Dict] = []
        owner_replies: List[Dict] = []

        def _fetch_comments():
            """Fetch comments via clockworks."""
            _cby: Dict[str, List[Dict]] = {}
            tvids = video_ids[:5]
            if not tvids: return _cby
            print(f"   ↳ [2/3] Komentar untuk {len(tvids)} video via clockworks...")
            try:
                cr = client.actor("clockworks/tiktok-comments-scraper").call(run_input={
                    "postURLs": [f"https://www.tiktok.com/@{clean}/video/{v}" for v in tvids],
                    "commentsPerPost": 15,
                    "maxRepliesPerComment": 2,
                })
                c_ds = getattr(cr, "default_dataset_id", None)
                if c_ds:
                    citems = client.dataset(c_ds).list_items().items or []
                    print(f"   ↳ {len(citems)} raw komentar dari clockworks")
                    if citems:
                        # Debug: print sample untuk lihat struktur
                        _s0 = citems[0]
                        print(f"      sample keys: {sorted(_s0.keys())[:12]}")
                        print(f"      sample: user={_s0.get('uniqueId','?')} text={str(_s0.get('text',''))[:40]}")
                    for ci in citems:
                        if ci.get("errorCode"): continue
                        vurl = ci.get("videoWebUrl") or ci.get("video_url") or ""
                        vid2 = next((v for v in tvids if v in vurl), "")
                        if not vid2:
                            vid2 = _safe_str(ci.get("awemeId") or ci.get("videoId") or "")
                            if vid2 not in tvids: vid2 = tvids[0] if tvids else ""
                        if not vid2: continue
                        cby.setdefault(vid2, [])
                        ct = _safe_str(ci.get("text"))
                        if not ct: continue
                        cu = _safe_str(ci.get("uniqueId") or ci.get("authorUniqueId") or "unknown")
                        cby[vid2].append({
                            "username": cu, "content": ct,
                            "likes": _safe_int(ci.get("diggCount")),
                            "replies": _safe_int(ci.get("replyCommentTotal")),
                            "created_at": _safe_str(ci.get("createTimeISO") or "")[:10],
                            "is_reply": False, "reply_to": "",
                        })
                        for rp in (ci.get("replies") or []):
                            if not isinstance(rp, dict): continue
                            rt = _safe_str(rp.get("text"))
                            if not rt: continue
                            ru = _safe_str(rp.get("uniqueId") or rp.get("authorUniqueId") or "unknown")
                            cby[vid2].append({
                                "username": ru, "content": rt,
                                "likes": _safe_int(rp.get("diggCount")),
                                "replies": 0, "is_reply": True, "reply_to": cu,
                                "created_at": _safe_str(rp.get("createTimeISO") or "")[:10],
                            })
                else:
                    print(f"   ⚠️  clockworks: no dataset returned")
            except Exception as ec:
                print(f"   ⚠️  clockworks comment error: {ec}")

            # Fallback herus13 di-skip untuk hemat waktu (target scan 3-5 menit)

        # Jalankan fetch comments sekarang
        _fetch_comments()

        for p in posts:
            if p["id"] in cby: p["comments_data"] = cby[p["id"]]
        total_c = sum(len(p["comments_data"]) for p in posts)

        # ── Filter komentar/reply milik OWNER (target) sendiri ────────────
        cl = clean.lower()
        owner_replies: List[Dict] = []
        for p in posts:
            for c in p["comments_data"]:
                c_user = c.get("username", "").lower().strip().lstrip("@")
                is_owner = (c_user == cl) or (cl in c_user and len(c_user) <= len(cl) + 3)
                if not is_owner:
                    continue
                content = c.get("content", "").strip()
                sticker_url = c.get("sticker_url") or c.get("image_url") or ""
                # Skip jika benar-benar kosong (tidak ada teks dan tidak ada stiker)
                if not content and not sticker_url:
                    continue
                display_text = content if content else "[Stiker/Emoji]"
                owner_replies.append({
                    "post_url":     p["post_url"],
                    "post_id":      p["id"],
                    "post_caption": p["content"][:100],
                    "comment_text": display_text,
                    "sticker_url":  sticker_url,
                    "likes":        c.get("likes", 0),
                    "is_reply":     c.get("is_reply", False),
                    "reply_to":     c.get("reply_to", ""),
                    "created_at":   c.get("created_at", ""),
                    "sentiment":    {"label": "NEUTRAL", "score": 0.5},
                })
        owner_replies.sort(key=lambda x: x.get("created_at") or "", reverse=True)
        owner_replies = owner_replies[:50]
        print(f"   ↳ Owner komentar/reply terdeteksi: {len(owner_replies)}")

        # Fallback: kalau owner tidak pernah reply, tampilkan semua komentar
        # dengan label jelas bahwa ini komentar DARI orang lain
        if not owner_replies and total_c > 0:
            flat = []
            for p in posts:
                for c in p["comments_data"]:
                    if c.get("content"):
                        flat.append({
                            "post_url":      p["post_url"],
                            "post_id":       p["id"],
                            "post_caption":  p["content"][:100],
                            "comment_text":  c["content"],
                            "likes":         c["likes"],
                            "is_reply":      c.get("is_reply", False),
                            "reply_to":      c.get("reply_to", ""),
                            "created_at":    c["created_at"],
                            "from_username": c.get("username", ""),
                            "sentiment":     {"label": "NEUTRAL", "score": 0.5},
                            "note":          f"Dari @{c.get('username','?')} (bukan pemilik akun)",
                        })
            flat.sort(key=lambda x: x.get("likes", 0), reverse=True)
            owner_replies = flat[:50]
            print(f"   ↳ Fallback: tampilkan {len(owner_replies)} komentar terpopuler")


        # ── RUN 3: Reposts — multi-strategy ──────────────────────────────
        reposts: List[Dict] = []
        print(f"   ↳ [3/3] Reposts...")

        # Strategy A: harpoon/tiktok-reposts-scraper — dedicated repost actor
        try:
            rr = client.actor("harpoon/tiktok-reposts-scraper").call(run_input={
                "profiles": [clean],
                "maxItems": 10,
            })
            rds = getattr(rr, "default_dataset_id", None)
            if rds:
                ris = client.dataset(rds).list_items().items or []
                print(f"   ↳ harpoon reposts: {len(ris)} raw items")
                if ris:
                    _ri0 = ris[0]
                    print(f"   🔍 repost[0] keys: {sorted(_ri0.keys())[:15]}")
                    for _k in ["id","videoId","webVideoUrl","postUrl","originalAuthor",
                               "authorMeta","text","caption","createTimeISO"]:
                        if _k in _ri0:
                            print(f"   🔍   {_k}: {str(_ri0[_k])[:80]}")
                for ri in ris:
                    if ri.get("errorCode"): continue
                    # harpoon schema
                    ao   = ri.get("authorMeta") or ri.get("author") or {}
                    orig = _safe_str(
                        ao.get("uniqueId") or ao.get("name") or
                        ri.get("originalAuthor") or ri.get("authorUniqueId") or ""
                    ).lstrip("@")
                    r_id  = _safe_str(ri.get("id") or ri.get("videoId") or "")
                    r_url = _safe_str(ri.get("webVideoUrl") or ri.get("postUrl") or ri.get("url") or "")
                    if not r_url and r_id and orig:
                        r_url = f"https://www.tiktok.com/@{orig}/video/{r_id}"
                    if not r_url and not (r_id and orig): continue
                    r_cap = _safe_str(ri.get("text") or ri.get("caption") or ri.get("desc") or "")
                    r_ts  = _safe_str(ri.get("createTimeISO") or "")[:10]
                    if not r_ts:
                        t0 = ri.get("createTime")
                        if t0 and str(t0).isdigit():
                            try: r_ts = time.strftime("%Y-%m-%d", time.localtime(int(t0)))
                            except: pass
                    mo  = ri.get("musicMeta") or ri.get("music") or {}
                    vo  = ri.get("videoMeta") or ri.get("video") or {}
                    rht = [h.get("name","") if isinstance(h,dict) else h for h in (ri.get("hashtags") or [])]
                    rht = [t for t in rht if t] or re.findall(r"#(\w+)", r_cap)
                    cover_r = _safe_str(
                        ri.get("coverUrl") or ri.get("cover_url") or
                        ri.get("thumbnailUrl") or ri.get("thumbnail") or ""
                    )
                    vd_r = _gen_vd(caption=r_cap, hashtags=rht,
                                   music_title=_safe_str(mo.get("musicName") or mo.get("title") or ""),
                                   music_author=_safe_str(mo.get("musicAuthor") or mo.get("authorName") or ""),
                                   duration_sec=_safe_int(vo.get("duration") or 0),
                                   username=orig,
                                   views=_safe_int(ri.get("playCount") or 0),
                                   likes=_safe_int(ri.get("diggCount") or ri.get("likeCount") or 0),
                                   comments=_safe_int(ri.get("commentCount") or 0),
                                   shares=_safe_int(ri.get("shareCount") or 0))
                    reposts.append({
                        "id": r_id, "video_url": r_url, "post_url": r_url,
                        "cover_url": cover_r, "original_author": orig,
                        "original_caption": r_cap[:300], "caption": r_cap[:300],
                        "content": r_cap[:300],
                        "visual_description": vd_r["visual_description"],
                        "ai_description": vd_r["ai_description"],
                        "topic": vd_r["topic"], "mood": vd_r["mood"],
                        "repost_date": r_ts, "created_at": r_ts,
                        "hashtags": rht,
                        "duration_sec": _safe_int(vo.get("duration") or 0),
                        "music": {"title": _safe_str(mo.get("musicName") or ""),
                                  "author": _safe_str(mo.get("musicAuthor") or "")},
                        "likes": _safe_int(ri.get("diggCount") or ri.get("likeCount") or 0),
                        "comments": _safe_int(ri.get("commentCount") or 0),
                        "shares": _safe_int(ri.get("shareCount") or 0),
                        "plays": _safe_int(ri.get("playCount") or 0),
                        "metrics": {
                            "likes": _safe_int(ri.get("diggCount") or ri.get("likeCount") or 0),
                            "comments": _safe_int(ri.get("commentCount") or 0),
                            "shares": _safe_int(ri.get("shareCount") or 0),
                            "plays": _safe_int(ri.get("playCount") or 0),
                        },
                        "sentiment": {"label": "NEUTRAL", "score": 0.5},
                        "is_repost": True,
                    })
            print(f"   ↳ harpoon reposts parsed: {len(reposts)}")
        except Exception as e_rr:
            print(f"   ⚠️ harpoon repost error: {e_rr}")

        # Strategy A2: maximedupre/tiktok-reposts (fallback jika harpoon kosong/gagal)
        if not reposts:
            try:
                rr2 = client.actor("maximedupre/tiktok-reposts").call(run_input={
                    "profiles": [clean],
                    "maxItems": 10,
                })
                rds2 = getattr(rr2, "default_dataset_id", None)
                if rds2:
                    ris2 = client.dataset(rds2).list_items().items or []
                    print(f"   ↳ maximedupre reposts: {len(ris2)} raw items")
                    if ris2:
                        print(f"   🔍 maximedupre keys: {sorted(ris2[0].keys())[:15]}")
                    for ri2 in ris2:
                        if ri2.get("errorCode"): continue
                        ao2  = ri2.get("authorMeta") or ri2.get("author") or {}
                        orig2 = _safe_str(ao2.get("uniqueId") or ao2.get("name") or
                                          ri2.get("originalAuthor") or "").lstrip("@")
                        r_id2  = _safe_str(ri2.get("id") or ri2.get("videoId") or "")
                        r_url2 = _safe_str(ri2.get("webVideoUrl") or ri2.get("postUrl") or "")
                        if not r_url2 and r_id2 and orig2:
                            r_url2 = f"https://www.tiktok.com/@{orig2}/video/{r_id2}"
                        if not r_url2 and not (r_id2 and orig2): continue
                        r_cap2 = _safe_str(ri2.get("text") or ri2.get("caption") or "")
                        r_ts2  = _safe_str(ri2.get("createTimeISO") or "")[:10]
                        if not r_ts2:
                            t02 = ri2.get("createTime")
                            if t02 and str(t02).isdigit():
                                try: r_ts2 = time.strftime("%Y-%m-%d", time.localtime(int(t02)))
                                except: pass
                        reposts.append({
                            "id": r_id2, "video_url": r_url2, "post_url": r_url2,
                            "cover_url": "", "original_author": orig2,
                            "original_caption": r_cap2[:300], "caption": r_cap2[:300],
                            "content": r_cap2[:300],
                            "visual_description": "", "ai_description": "",
                            "topic": "", "mood": "",
                            "repost_date": r_ts2, "created_at": r_ts2,
                            "hashtags": re.findall(r"#(\w+)", r_cap2),
                            "duration_sec": 0,
                            "music": {"title": "", "author": ""},
                            "likes": _safe_int(ri2.get("diggCount") or 0),
                            "comments": _safe_int(ri2.get("commentCount") or 0),
                            "shares": _safe_int(ri2.get("shareCount") or 0),
                            "plays": _safe_int(ri2.get("playCount") or 0),
                            "metrics": {
                                "likes": _safe_int(ri2.get("diggCount") or 0),
                                "comments": _safe_int(ri2.get("commentCount") or 0),
                                "shares": _safe_int(ri2.get("shareCount") or 0),
                                "plays": _safe_int(ri2.get("playCount") or 0),
                            },
                            "sentiment": {"label": "NEUTRAL", "score": 0.5},
                            "is_repost": True,
                        })
                    print(f"   ↳ maximedupre reposts parsed: {len(reposts)}")
            except Exception as e_rr2:
                print(f"   ⚠️ maximedupre repost error: {e_rr2}")

        # Strategy B: yt-dlp scrape tab repost (jika clockworks kosong)
        if not reposts:
            print(f"   ↳ Fallback: yt-dlp repost tab...")
            try:
                import yt_dlp as _ydl_mod
                import os as _oss2
                _tt_sess2  = _oss2.getenv("TIKTOK_SESSIONID", "").strip()
                _tt_ttwid2 = _oss2.getenv("TIKTOK_TTWID",    "").strip()
                _cookie_r  = ""
                if _tt_sess2:  _cookie_r += f"sessionid={_tt_sess2}; "
                if _tt_ttwid2: _cookie_r += f"ttwid={_tt_ttwid2}; "

                _ydl_r_opts = {
                    "quiet": True, "no_warnings": True,
                    "extract_flat": True, "playlistend": 10,
                    "skip_download": True, "socket_timeout": 25,
                    "http_headers": {
                        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                       "AppleWebKit/537.36 Chrome/125.0.0.0 Safari/537.36"),
                        **({"Cookie": _cookie_r.strip("; ")} if _cookie_r.strip("; ") else {}),
                    },
                }
                _repost_url = f"https://www.tiktok.com/@{clean}/repost"
                with _ydl_mod.YoutubeDL(_ydl_r_opts) as _ydl_r:
                    _ri = _ydl_r.extract_info(_repost_url, download=False)
                if _ri:
                    _entries_r = _ri.get("entries") or []
                    print(f"   ↳ yt-dlp repost: {len(_entries_r)} entries")
                    for _re in _entries_r[:10]:
                        if not _re: continue
                        _rid   = _safe_str(_re.get("id") or "")
                        _rcap  = _safe_str(_re.get("description") or _re.get("title") or "")
                        _ruser = _safe_str(_re.get("uploader") or _re.get("channel") or
                                           _re.get("uploader_id") or "")
                        _rurl  = (_re.get("webpage_url") or _re.get("url") or
                                  (f"https://www.tiktok.com/@{_ruser}/video/{_rid}" if _rid else ""))
                        if not _rurl: continue
                        _rts_raw = _re.get("timestamp") or ""
                        _rts = ""
                        if _rts_raw and str(_rts_raw).isdigit():
                            try: _rts = datetime.datetime.fromtimestamp(int(_rts_raw)).strftime("%Y-%m-%d")
                            except: pass
                        _rht = re.findall(r"#(\w+)", _rcap)
                        _rdur = _safe_int(_re.get("duration") or 0)
                        _thumbs_r = _re.get("thumbnails") or []
                        _rcover = ((_thumbs_r[-1].get("url") if _thumbs_r else None) or
                                   _re.get("thumbnail") or "")
                        _vd_r2 = _gen_vd(caption=_rcap, hashtags=_rht, duration_sec=_rdur,
                                         media_type="video", username=_ruser,
                                         views=_safe_int(_re.get("view_count") or 0),
                                         likes=_safe_int(_re.get("like_count") or 0),
                                         comments=_safe_int(_re.get("comment_count") or 0),
                                         shares=_safe_int(_re.get("repost_count") or 0))
                        reposts.append({
                            "id":               _rid,
                            "video_url":        _rurl,
                            "post_url":         _rurl,
                            "cover_url":        _rcover,
                            "original_author":  _ruser,
                            "original_caption": _rcap[:300],
                            "caption":          _rcap[:300],
                            "content":          _rcap[:300],
                            "visual_description": _vd_r2["visual_description"],
                            "ai_description":   _vd_r2["ai_description"],
                            "topic":    _vd_r2["topic"],
                            "mood":     _vd_r2["mood"],
                            "repost_date":  _rts,
                            "created_at":   _rts,
                            "hashtags":     _rht,
                            "duration_sec": _rdur,
                            "likes":    _safe_int(_re.get("like_count")    or 0),
                            "comments": _safe_int(_re.get("comment_count") or 0),
                            "shares":   _safe_int(_re.get("repost_count")  or 0),
                            "plays":    _safe_int(_re.get("view_count")    or 0),
                            "metrics": {
                                "likes":    _safe_int(_re.get("like_count")    or 0),
                                "plays":    _safe_int(_re.get("view_count")    or 0),
                                "comments": _safe_int(_re.get("comment_count") or 0),
                                "shares":   _safe_int(_re.get("repost_count")  or 0),
                            },
                            "music": {"title": _safe_str(_re.get("track") or ""),
                                      "author": _safe_str(_re.get("artist") or "")},
                            "sentiment": {"label": "NEUTRAL", "score": 0.5},
                            "is_repost": True,
                        })
            except Exception as _e_ydl_r:
                print(f"   ⚠️ yt-dlp repost error: {_e_ydl_r}")

        reposts.sort(key=lambda x: x.get("repost_date") or x.get("created_at") or "", reverse=True)
        reposts = reposts[:10]

        # Strategy C dihapus — tidak tampilkan postingan sendiri sebagai repost
        # karena itu menyesatkan. Lebih baik 0 repost yang akurat daripada data palsu.
        if not reposts:
            print(f"   ↳ Tidak ada repost yang berhasil diambil (crawlerbros limit atau akun baru)")

        print(f"   ↳ Final — Posts: {len(posts)} | Reposts: {len(reposts)} | Comments: {len(owner_replies)}")

        total_likes    = sum(p["likes"]    for p in posts)
        total_comments = sum(p["comments"] for p in posts)
        total_shares   = sum(p["shares"]   for p in posts)

        return {
            "status": "success", "platform": "tiktok", "username": clean,
            "full_name": full_name, "bio": bio, "followers": followers,
            "following": following, "likes": total_heart, "verified": verified,
            "join_date": "", "profile_pic": profile_pic, "total_posts": len(posts),
            "posts": posts, "user_comments": owner_replies,
            "comments_on_posts": [], "reposts": reposts,
            "total_likes": total_likes, "total_comments": total_comments,
            "total_shares": total_shares, "has_text": any(p["content"] for p in posts),
            "scrape_errors": [],
        }

    except Exception as e:
        import traceback
        err_str = str(e)
        print(f"   ❌ TikTok scrape error: {err_str}")
        print(traceback.format_exc())
        # ── Apify credit habis atau error → fallback yt-dlp ─────────────
        _credit_keywords = [
            "exceed", "remaining usage", "upgrade", "billing",
            "payment", "quota", "limit", "credit",
        ]
        print(f"   ⚡ Apify error — switching ke yt-dlp fallback: {err_str[:100]}")
        return _tiktok_scrape_ytdlp(clean)  # pakai clean (tanpa @)


# ─────────── async wrapper ────────────────────────────────────────────────────
async def _tiktok_scrape_real(username: str, apify_token: str) -> Dict:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, partial(_tiktok_scrape_sync, username, apify_token))