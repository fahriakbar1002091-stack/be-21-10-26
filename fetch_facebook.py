"""
fetch_facebook.py - Facebook Scraper via Apify v2.0
Actors:
  - apify/facebook-posts-scraper   → posts publik, repost detection via sharedPost
  - apify/facebook-pages-scraper   → profile lengkap (bio, cover, lokasi, website, dll)
  - apify/facebook-comments-scraper → user_comments (filter: komentar oleh target sendiri)
  - apify/facebook-photos-scraper  → foto publik (best-effort, skip jika gagal)

Semua field profile yang diambil:
  name, profile_pic, cover_photo, bio, address/location, website, email,
  phone, creation_date, categories, about_me (teks panjang), rating,
  followers, likes (page likes), followings

Limitasi Facebook (tidak bisa diambil scraper apapun):
  - Pekerjaan / jabatan       → TIDAK tersedia di API publik
  - Pendidikan                → TIDAK tersedia di API publik
  - Daftar teman              → selalu privat
  - Grup yang diikuti         → privat kecuali grupnya sendiri publik
  - Halaman yang disukai      → privat
"""

import re
import asyncio
import time as time_module
from typing import Dict, List, Any, Tuple
from functools import partial


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────
def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value) if value is not None else default
    except (ValueError, TypeError):
        return default


def _safe_str(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value).strip()


def _parse_fb_date(raw: Any) -> str:
    if not raw:
        return ""
    s = str(raw)
    # Unix timestamp
    if s.isdigit():
        try:
            return time_module.strftime("%Y-%m-%d", time_module.localtime(int(s)))
        except Exception:
            return s
    # ISO string → ambil 10 karakter pertama
    return s[:10] if len(s) >= 10 else s


# ─────────────────────────────────────────────────────────────────────────────
# FACEBOOK CONTENT ANALYSIS ENGINE
# ─────────────────────────────────────────────────────────────────────────────

_FB_TOPICS: Dict[str, List[str]] = {
    "Sains & Alam":          ["science","space","climate","environment","nasa","research",
                               "planet","universe","biology","physics","nature","earth",
                               "galaxy","telescope","nebula","asteroid","climate change",
                               "alam","ilmu","penelitian","lingkungan","luar angkasa"],
    "Teknologi & Inovasi":   ["tech","technology","innovation","startup","digital","ai",
                               "artificial intelligence","software","robot","automation",
                               "internet","app","gadget","coding","programming","blockchain",
                               "teknologi","inovasi","aplikasi","perangkat","digital"],
    "Politik & Pemerintahan":["government","policy","president","election","vote","parliament",
                               "minister","senate","congress","democracy","law","bill",
                               "pemerintah","kebijakan","presiden","pemilu","menteri","DPR"],
    "Bisnis & Ekonomi":      ["business","economy","market","finance","invest","stock","crypto",
                               "bitcoin","trade","gdp","inflation","company","ceo","entrepreneur",
                               "bisnis","ekonomi","pasar","investasi","saham","keuangan"],
    "Olahraga":              ["football","soccer","sport","basketball","tennis","swimming","run",
                               "champion","match","game","athlete","team","league","fifa","nba",
                               "olahraga","sepak bola","futsal","basket","juara","pertandingan"],
    "Hiburan & Komedi":      ["funny","comedy","meme","entertainment","movie","film","music",
                               "song","viral","celebrity","artist","konser","lucu","komedi",
                               "hiburan","artis","lagu","film","pertunjukan","sinetron"],
    "Motivasi & Inspirasi":  ["inspire","dream","success","motivation","believe","goal","mindset",
                               "achieve","leadership","growth","positive","grateful","courage",
                               "inspirasi","semangat","sukses","mimpi","percaya","motivasi"],
    "Karir & Profesional":   ["career","job","hiring","work","professional","office","employee",
                               "interview","salary","promotion","resume","linkedin","networking",
                               "karir","pekerjaan","lowongan","kerja","promosi","profesional"],
    "Pendidikan":            ["education","school","university","learning","course","study",
                               "graduate","degree","teacher","student","campus","scholarship",
                               "pendidikan","sekolah","kampus","belajar","mahasiswa","beasiswa"],
    "Kesehatan & Gaya Hidup":["health","wellness","fitness","diet","exercise","mental health",
                               "meditation","yoga","nutrition","doctor","hospital","vaccine",
                               "kesehatan","sehat","olahraga","diet","gaya hidup","rumah sakit"],
    "Keluarga & Personal":   ["family","personal","life","love","kids","children","parent",
                               "home","birthday","wedding","anniversary","baby","friendship",
                               "keluarga","kehidupan","cinta","anak","pernikahan","ulang tahun"],
    "Perjalanan & Wisata":   ["travel","trip","vacation","tourism","explore","destination",
                               "hotel","flight","beach","mountain","island","adventure",
                               "perjalanan","wisata","liburan","destinasi","pantai","gunung"],
    "Kuliner & Makanan":     ["food","restaurant","cooking","recipe","cuisine","chef","eat",
                               "menu","coffee","bakery","street food","halal","culinary",
                               "makanan","restoran","masak","resep","kuliner","kafe","makan"],
    "Sosial & Kemanusiaan":  ["social","community","charity","humanitarian","volunteer","human rights",
                               "poverty","donation","empathy","protest","movement","awareness",
                               "sosial","komunitas","donasi","kemanusiaan","sukarela","hak asasi"],
    "Berita & Informasi":    ["news","update","breaking","report","announce","official","press",
                               "media","journalist","headline","berita","kabar","informasi",
                               "pengumuman","laporan","terkini","resmi"],
    "Agama & Spiritualitas": ["religion","pray","god","faith","mosque","church","temple","quran",
                               "bible","spiritual","blessing","ramadan","eid","agama","doa",
                               "ibadah","masjid","gereja","syukur","berkat","iman"],
}

_FB_MOOD: Dict[str, str] = {
    "Sains & Alam":          "kagum, informatif, inspiratif, reflektif",
    "Teknologi & Inovasi":   "antusias, inovatif, forward-thinking, optimis",
    "Politik & Pemerintahan":"kritis, tegas, analitis, serius",
    "Bisnis & Ekonomi":      "strategis, ambisius, analitis, pragmatis",
    "Olahraga":              "bersemangat, kompetitif, bangga, penuh energi",
    "Hiburan & Komedi":      "riang, santai, menghibur, ekspresif",
    "Motivasi & Inspirasi":  "positif, penuh semangat, inspiratif, memberdayakan",
    "Karir & Profesional":   "profesional, ambisius, percaya diri, fokus",
    "Pendidikan":            "intelektual, informatif, bersemangat belajar",
    "Kesehatan & Gaya Hidup":"peduli, positif, sadar kesehatan, seimbang",
    "Keluarga & Personal":   "hangat, penuh kasih, autentik, emosional",
    "Perjalanan & Wisata":   "petualangan, eksploratif, bebas, terpesona",
    "Kuliner & Makanan":     "nikmat, menggugah selera, apresiatif, ekspresif",
    "Sosial & Kemanusiaan":  "empatik, peduli, solidaritas, menggerakkan",
    "Berita & Informasi":    "informatif, faktual, serius, urgen",
    "Agama & Spiritualitas": "khusyuk, damai, syukur, penuh makna",
}

_FB_OBJECTS: Dict[str, str] = {
    "Sains & Alam":          "fenomena alam, data ilmiah, teleskop, bintang, ekosistem, eksperimen",
    "Teknologi & Inovasi":   "perangkat teknologi, platform digital, kecerdasan buatan, inovasi produk",
    "Politik & Pemerintahan":"kebijakan publik, tokoh politik, institusi, regulasi, isu nasional",
    "Bisnis & Ekonomi":      "pasar saham, perusahaan, aset keuangan, data ekonomi, bisnis model",
    "Olahraga":              "pemain, tim, stadion, piala, kompetisi, catatan statistik",
    "Hiburan & Komedi":      "konten viral, meme, artis, acara hiburan, referensi budaya pop",
    "Motivasi & Inspirasi":  "kata-kata bijak, kisah sukses, pencapaian, nilai-nilai positif",
    "Karir & Profesional":   "peluang kerja, portfolio, keahlian, pencapaian profesional",
    "Pendidikan":            "materi pelajaran, institusi, prestasi akademik, program beasiswa",
    "Kesehatan & Gaya Hidup":"aktivitas fisik, pola makan, kondisi tubuh, tips kesehatan",
    "Keluarga & Personal":   "momen bersama, kenangan, anggota keluarga, perasaan pribadi",
    "Perjalanan & Wisata":   "destinasi, pemandangan, pengalaman perjalanan, kuliner lokal",
    "Kuliner & Makanan":     "hidangan, bahan masakan, suasana restoran, presentasi makanan",
    "Sosial & Kemanusiaan":  "isu sosial, komunitas, program bantuan, kesadaran publik",
    "Berita & Informasi":    "peristiwa terkini, narasumber, data, konfirmasi fakta",
    "Agama & Spiritualitas": "teks suci, ritual ibadah, nilai moral, komunitas agama",
}

_FB_ACTIVITY: Dict[str, str] = {
    "Sains & Alam":          "membagikan penemuan ilmiah dan informasi tentang alam semesta",
    "Teknologi & Inovasi":   "berbagi wawasan tentang perkembangan teknologi dan inovasi terbaru",
    "Politik & Pemerintahan":"menyampaikan opini politik atau menginformasikan kebijakan publik",
    "Bisnis & Ekonomi":      "berbagi analisis bisnis, peluang investasi, atau tren ekonomi",
    "Olahraga":              "merayakan pencapaian atletik atau mendiskusikan event olahraga",
    "Hiburan & Komedi":      "berbagi konten hiburan, humor, atau referensi budaya pop",
    "Motivasi & Inspirasi":  "menginspirasi dan memotivasi audiens melalui pesan positif",
    "Karir & Profesional":   "berbagi peluang karir atau pengalaman profesional",
    "Pendidikan":            "mendidik audiens dengan informasi akademis atau tips belajar",
    "Kesehatan & Gaya Hidup":"mendorong gaya hidup sehat dan kesadaran akan kesehatan",
    "Keluarga & Personal":   "berbagi momen dan perasaan personal yang autentik",
    "Perjalanan & Wisata":   "berbagi pengalaman perjalanan dan rekomendasi destinasi wisata",
    "Kuliner & Makanan":     "merekomendasikan atau memperkenalkan pengalaman kuliner",
    "Sosial & Kemanusiaan":  "menggerakkan kesadaran sosial dan mendorong aksi nyata",
    "Berita & Informasi":    "menyebarkan informasi terkini kepada publik",
    "Agama & Spiritualitas": "berbagi renungan spiritual dan memperkuat nilai-nilai keimanan",
}


def _detect_topic_fb(text: str, hashtags: List[str] = None) -> str:
    all_lower = (text + " " + " ".join(hashtags or [])).lower()
    scores: Dict[str, int] = {}
    for topic, kws in _FB_TOPICS.items():
        hits = sum(1 for kw in kws if kw in all_lower)
        if hits:
            scores[topic] = hits
    return max(scores, key=lambda k: scores[k]) if scores else "Umum"


def _detect_mood_fb(text: str, topic: str) -> str:
    return _FB_MOOD.get(topic, "informatif, ekspresif, natural")


def _detect_objects_fb(text: str, topic: str, media_type: str = "text") -> str:
    base = _FB_OBJECTS.get(topic, "konten teks, informasi, ekspresi")
    # Tambah media context
    if media_type == "video":
        return base + ", rekaman video, visual bergerak"
    elif media_type == "image":
        return base + ", gambar/foto, visual statis"
    elif media_type == "carousel":
        return base + ", rangkaian foto/video, galeri media"
    return base


def _detect_activity_fb(text: str, topic: str) -> str:
    return _FB_ACTIVITY.get(topic, "berbagi konten dan berinteraksi dengan komunitas Facebook")


def _fb_engagement_level(likes: int, comments: int, shares: int, plays: int = 0) -> str:
    # Facebook engagement lebih besar karena halaman besar punya jutaan followers
    total = likes + (comments * 5) + (shares * 3) + (plays // 100 if plays else 0)
    if total >= 1_000_000: return "VIRAL"
    if total >= 100_000:   return "SANGAT TINGGI"
    if total >= 10_000:    return "TINGGI"
    if total >= 1_000:     return "SEDANG"
    return "RENDAH"


def _build_ai_description_fb(
    text: str,
    topic: str,
    mood: str,
    objects: str,
    activity: str,
    hashtags: List[str],
    mentions: List[str],
    likes: int,
    comments: int,
    shares: int,
    plays: int,
    reactions: Dict[str, int],
    media_type: str,
    media_count: int,
    page_name: str,
    created_at: str,
    is_ad: bool,
    is_repost: bool,
    ocr_text: str = "",
) -> str:
    """Generate ai_description Facebook yang sangat detail (200-500 kata)."""
    clean_text = re.sub(r"\s+", " ", re.sub(r"https?://\S+", "", text)).strip()
    word_count = len(clean_text.split())
    eng_level  = _fb_engagement_level(likes, comments, shares, plays)

    reactions_total = sum(reactions.values())
    dominant_rxn = max(reactions, key=lambda k: reactions[k]) if reactions_total > 0 else "like"
    rxn_label = {
        "like": "menyukai", "love": "mencintai / sangat menyukai",
        "care": "peduli dan empati", "haha": "merasa lucu",
        "wow": "terkejut dan kagum", "sad": "sedih", "angry": "marah",
    }

    # Deskripsi media
    media_desc = {
        "video": f"video{f' (total {media_count} media)' if media_count > 1 else ''}",
        "image": f"foto/gambar{f' (total {media_count} gambar)' if media_count > 1 else ''}",
        "carousel": f"galeri {media_count} foto/video",
        "text": "teks tanpa media pendamping",
    }

    parts: List[str] = []

    # ── 1. Pembuka: siapa, apa, kapan ────────────────────────────────────
    page_ctx = f"Halaman '{page_name}'" if page_name else "Halaman Facebook ini"
    if is_repost:
        parts.append(
            f"{page_ctx} membagikan ulang (share) sebuah postingan dari sumber lain "
            f"pada {created_at or 'tanggal tidak diketahui'}. "
            f"Tindakan share ini menunjukkan bahwa halaman menganggap konten tersebut "
            f"relevan dan layak disebarluaskan kepada audiens mereka."
        )
    elif is_ad:
        parts.append(
            f"Ini adalah konten berbayar (iklan/promoted post) yang dipublikasikan oleh "
            f"{page_ctx} pada {created_at or 'tanggal tidak diketahui'}."
        )
    else:
        parts.append(
            f"{page_ctx} mempublikasikan postingan original pada "
            f"{created_at or 'tanggal tidak diketahui'}. "
            f"Postingan ini disertai {media_desc.get(media_type, 'konten')} "
            f"sebagai elemen visual pendukung pesan."
        )

    # ── 2. Isi konten ─────────────────────────────────────────────────────
    if clean_text:
        if word_count >= 40:
            parts.append(
                f"Teks postingan ditulis dengan gaya {('panjang dan informatif' if word_count >= 80 else 'sedang')} "
                f"({word_count} kata), berbunyi: \"{clean_text[:600]}\". "
                f"Konten ini mencerminkan upaya halaman untuk memberikan informasi mendalam kepada audiens."
            )
        elif word_count >= 10:
            parts.append(
                f"Pesan yang disampaikan: \"{clean_text[:400]}\". "
                f"Teks ditulis singkat namun padat, efektif dalam menyampaikan inti pesan."
            )
        else:
            parts.append(f"Caption singkat: \"{clean_text}\".")

    # ── 3. Konteks topik ──────────────────────────────────────────────────
    _topic_ctx = {
        "Sains & Alam":          "berkaitan dengan ilmu pengetahuan dan alam semesta",
        "Teknologi & Inovasi":   "membahas perkembangan teknologi dan inovasi",
        "Politik & Pemerintahan":"menyentuh isu politik atau kebijakan",
        "Bisnis & Ekonomi":      "berkaitan dengan dunia bisnis dan ekonomi",
        "Olahraga":              "berhubungan dengan dunia olahraga",
        "Hiburan & Komedi":      "berisi konten hiburan dan humor",
        "Motivasi & Inspirasi":  "mengandung pesan motivasi dan inspirasi",
        "Karir & Profesional":   "berkaitan dengan karir dan profesionalisme",
        "Pendidikan":            "membahas topik pendidikan dan pembelajaran",
        "Kesehatan & Gaya Hidup":"berkaitan dengan kesehatan dan gaya hidup",
        "Keluarga & Personal":   "mengangkat tema personal dan keluarga",
        "Perjalanan & Wisata":   "berkaitan dengan perjalanan dan wisata",
        "Kuliner & Makanan":     "membahas pengalaman kuliner dan makanan",
        "Sosial & Kemanusiaan":  "menyentuh isu sosial dan kemanusiaan",
        "Berita & Informasi":    "menyampaikan berita atau informasi terkini",
        "Agama & Spiritualitas": "mengangkat tema agama dan spiritualitas",
    }
    ctx_desc = _topic_ctx.get(topic, "bersifat informatif dan ekspresif")
    parts.append(
        f"Konten ini {ctx_desc}, dengan topik utama yang terdeteksi adalah '{topic}'. "
        f"Suasana yang dibangun dalam postingan ini: {mood}. "
        f"Elemen konten yang menonjol meliputi: {objects}."
    )

    # ── 4. OCR dari gambar ────────────────────────────────────────────────
    if ocr_text and len(ocr_text.strip()) > 5:
        parts.append(
            f"Teks yang terbaca dari elemen visual postingan (OCR): \"{ocr_text.strip()[:200]}\". "
            f"Ini mengindikasikan bahwa postingan menyertakan teks penting dalam bentuk gambar atau infografik."
        )

    # ── 5. Hashtag & mention ──────────────────────────────────────────────
    if hashtags:
        parts.append(
            f"Halaman menggunakan hashtag {', '.join('#'+h for h in hashtags[:8])} "
            f"untuk meningkatkan jangkauan dan menjangkau komunitas yang relevan."
        )
    if mentions:
        parts.append(
            f"Postingan ini menyebut atau menandai akun: {', '.join('@'+m for m in mentions[:5])}."
        )

    # ── 6. Engagement analysis ────────────────────────────────────────────
    if eng_level == "VIRAL":
        parts.append(
            f"Postingan ini mencapai tingkat engagement VIRAL yang luar biasa dengan "
            f"{likes:,} likes, {comments:,} komentar, dan {shares:,} shares. "
            f"Ini menandakan bahwa konten ini resonan secara masif di platform Facebook "
            f"dan kemungkinan besar sudah tersebar jauh melampaui audiens halaman itu sendiri."
        )
    elif eng_level == "SANGAT TINGGI":
        parts.append(
            f"Engagement SANGAT TINGGI: {likes:,} likes, {comments:,} komentar, "
            f"{shares:,} shares{f', {plays:,} views' if plays else ''}. "
            f"Konten ini berhasil menarik perhatian luas dan mendorong interaksi aktif dari audiens."
        )
    elif eng_level == "TINGGI":
        parts.append(
            f"Engagement cukup tinggi dengan {likes:,} likes, {comments:,} komentar, "
            f"dan {shares:,} shares — performa di atas rata-rata."
        )
    elif likes > 0:
        parts.append(
            f"Postingan mendapatkan {likes:,} likes, {comments:,} komentar, "
            f"dan {shares:,} shares."
        )

    # ── 7. Reactions breakdown ────────────────────────────────────────────
    if reactions_total > 0:
        top_rxns = sorted(
            [(k, v) for k, v in reactions.items() if v > 0],
            key=lambda x: x[1], reverse=True
        )[:3]
        rxn_str = ", ".join(
            f"{v:,} {rxn_label.get(k, k)}" for k, v in top_rxns
        )
        parts.append(
            f"Distribusi reaksi publik (total {reactions_total:,}): {rxn_str}. "
            f"Reaksi dominan '{dominant_rxn}' menunjukkan bahwa mayoritas audiens "
            f"merespons konten ini dengan {rxn_label.get(dominant_rxn, dominant_rxn)}."
        )

    # ── 8. Tujuan & dampak ────────────────────────────────────────────────
    _purpose = {
        "Sains & Alam":          "mengedukasi publik tentang fenomena ilmiah dan mendorong rasa ingin tahu",
        "Teknologi & Inovasi":   "menginformasikan perkembangan teknologi dan menginspirasi inovasi",
        "Politik & Pemerintahan":"mempengaruhi opini publik atau menyebarkan informasi kebijakan",
        "Bisnis & Ekonomi":      "memberikan wawasan bisnis dan mendorong keputusan ekonomi yang lebih baik",
        "Olahraga":              "merayakan semangat olahraga dan mendekatkan fans dengan tim/atlet",
        "Hiburan & Komedi":      "menghibur audiens dan menciptakan momen kesenangan bersama",
        "Motivasi & Inspirasi":  "memberdayakan audiens dengan pesan positif dan mendorong perubahan",
        "Karir & Profesional":   "membuka peluang dan menginspirasi perkembangan karir audiens",
        "Pendidikan":            "meningkatkan literasi dan mendorong semangat belajar di masyarakat",
        "Kesehatan & Gaya Hidup":"mendorong gaya hidup lebih sehat dan meningkatkan kesadaran kesehatan",
        "Keluarga & Personal":   "membangun koneksi emosional yang autentik dengan audiens",
        "Perjalanan & Wisata":   "menginspirasi perjalanan dan mempromosikan destinasi wisata",
        "Kuliner & Makanan":     "menggugah selera dan berbagi pengalaman kuliner yang berkesan",
        "Sosial & Kemanusiaan":  "menggerakkan solidaritas sosial dan mendorong aksi nyata di masyarakat",
        "Berita & Informasi":    "menjaga audiens tetap terinformasi dengan berita dan fakta terkini",
        "Agama & Spiritualitas": "memperkuat keimanan dan membangun komunitas spiritual yang solid",
    }
    purpose = _purpose.get(topic, "berinteraksi dengan audiens dan memperkuat kehadiran digital")
    parts.append(
        f"Tujuan utama postingan ini adalah {purpose}. "
        f"Secara keseluruhan, postingan ini merupakan bagian dari strategi konten "
        f"halaman untuk {activity}."
    )

    return " ".join(parts)


def _analyze_facebook_post(
    text: str,
    media_type: str,
    media_count: int,
    hashtags: List[str],
    mentions: List[str],
    likes: int,
    comments: int,
    shares: int,
    plays: int,
    reactions: Dict[str, int],
    page_name: str,
    created_at: str,
    is_ad: bool,
    is_repost: bool,
    ocr_text: str = "",
) -> Dict:
    """Return content_analysis lengkap untuk satu Facebook post."""
    topic    = _detect_topic_fb(text, hashtags)
    mood     = _detect_mood_fb(text, topic)
    objects  = _detect_objects_fb(text, topic, media_type)
    activity = _detect_activity_fb(text, topic)
    eng_lvl  = _fb_engagement_level(likes, comments, shares, plays)

    # Content summary
    clean_text = re.sub(r"\s+", " ", re.sub(r"[#@]|\bhttps?://\S+", "", text)).strip()
    summary = clean_text[:200] if clean_text else (hashtags[0] if hashtags else "")

    # Deteksi emosi dari teks
    text_lower = text.lower()
    emotions: List[str] = []
    if any(w in text_lower for w in ["amazing","incredible","wow","mengagumkan","luar biasa","menakjubkan"]):
        emotions.append("Kagum")
    if any(w in text_lower for w in ["proud","bangga","honor","kehormatan"]):
        emotions.append("Bangga")
    if any(w in text_lower for w in ["excited","antusias","semangat","passionate"]):
        emotions.append("Antusias")
    if any(w in text_lower for w in ["hope","harap","hope","masa depan","future"]):
        emotions.append("Harapan")
    if any(w in text_lower for w in ["sad","sedih","prihatin","duka","grief"]):
        emotions.append("Sedih")
    if any(w in text_lower for w in ["inspire","inspirasi","motivate","semangat","empower"]):
        emotions.append("Inspiratif")
    if any(w in text_lower for w in ["thank","terima kasih","grateful","syukur","bersyukur"]):
        emotions.append("Rasa Syukur")
    if not emotions:
        emotions = ["Informatif"]

    # Language detection (simple)
    id_kw = ["yang","dan","di","ke","dari","untuk","ini","itu","dengan","adalah","tidak","ada"]
    lang = "id" if sum(1 for w in id_kw if f" {w} " in f" {text_lower} ") >= 3 else "en"

    # Word count
    wc = len(text.split()) if text else 0

    # Readability score (simple heuristic)
    avg_word_len = (sum(len(w) for w in text.split()) / wc) if wc > 0 else 0
    readability = max(20, min(100, int(100 - (avg_word_len - 4) * 10)))

    ai_description = _build_ai_description_fb(
        text=text, topic=topic, mood=mood, objects=objects, activity=activity,
        hashtags=hashtags, mentions=mentions,
        likes=likes, comments=comments, shares=shares, plays=plays,
        reactions=reactions, media_type=media_type, media_count=media_count,
        page_name=page_name, created_at=created_at,
        is_ad=is_ad, is_repost=is_repost, ocr_text=ocr_text,
    )

    return {
        "topic":             topic,
        "mood":              mood,
        "objects":           objects,
        "activity":          activity,
        "content_summary":   summary,
        "ai_description":    ai_description,
        "key_themes":        [topic] + hashtags[:5],
        "engagement_level":  eng_lvl,
        "word_count":        wc,
        "readability_score": readability,
        "language":          lang,
        "detected_emotions": emotions,
    }


def _build_empty_result(username: str, error: str) -> Dict:
    return {
        "status": "error", "platform": "facebook", "username": username,
        # profile
        "full_name": "", "bio": "", "about_me": "", "followers": 0,
        "following": 0, "page_likes": 0, "verified": False,
        "join_date": "", "profile_pic": "", "cover_photo": "",
        "location": "", "address": "", "website": "", "email": "",
        "phone": "", "categories": [], "rating": "", "rating_count": 0,
        # stats
        "total_posts": 0, "total_likes": 0, "total_comments": 0,
        "total_shares": 0, "has_text": False,
        # data
        "posts": [], "photos": [], "user_comments": [], "reposts": [],
        "scrape_errors": [error]
    }


# ─────────────────────────────────────────────────────────────────────────────
# SYNC SCRAPER — dijalankan di thread executor agar tidak blocking event loop
# ─────────────────────────────────────────────────────────────────────────────
def _facebook_scrape_sync(username: str, apify_token: str) -> Dict:
    if not apify_token:
        import os
        from dotenv import load_dotenv
        load_dotenv()
        apify_token = os.getenv("APIFY_TOKEN", "")

    if not apify_token:
        return _build_empty_result(username, "APIFY_TOKEN tidak ditemukan di .env")

    try:
        from apify_client import ApifyClient
    except ImportError:
        return _build_empty_result(username, "apify_client tidak terinstall — jalankan: pip install apify-client")

    clean_username = username.replace("@", "").strip()
    profile_url = (
        clean_username
        if clean_username.startswith("http")
        else f"https://www.facebook.com/{clean_username}"
    )
    print(f"📡 [Facebook] Scraping {profile_url}...")

    try:
        client = ApifyClient(apify_token)

        # ══════════════════════════════════════════════════════════════════
        # RUN 1 — Posts (wajib, tidak boleh skip)
        # Strategi: coba beberapa actor — personal profile butuh actor berbeda
        # dari Facebook Pages. Mulai dari yang paling optimal untuk personal.
        # ══════════════════════════════════════════════════════════════════

        def _run_posts_actor(actor_id: str, run_input: dict) -> List[Dict]:
            """Helper: jalankan actor dan return items, atau [] jika error."""
            try:
                print(f"   ↳ Mencoba {actor_id}...")
                run = client.actor(actor_id).call(run_input=run_input)
                ds_id = getattr(run, "default_dataset_id", None)
                if not ds_id:
                    return []
                items = client.dataset(ds_id).list_items().items or []
                # Filter error items
                items = [x for x in items if not x.get("error") and not x.get("errorCode")]
                print(f"   ↳ {actor_id}: {len(items)} items")
                return items
            except Exception as e:
                print(f"   ⚠️ {actor_id} error: {e}")
                return []

        # ── Baca Facebook cookies dari environment ────────────────────────
        import os as _os
        _fb_cookie_str = _os.getenv("FB_COOKIE_STRING", "").strip()
        _c_user  = _os.getenv("FB_COOKIE_C_USER", "").strip()
        _xs      = _os.getenv("FB_COOKIE_XS", "").strip()
        _datr    = _os.getenv("FB_COOKIE_DATR", "").strip()
        _fr      = _os.getenv("FB_COOKIE_FR", "").strip()

        # Build cookie string dan JSON array jika ada komponen individual
        if not _fb_cookie_str and _c_user and _xs:
            _parts = []
            if _c_user: _parts.append(f"c_user={_c_user}")
            if _xs:     _parts.append(f"xs={_xs}")
            if _datr:   _parts.append(f"datr={_datr}")
            if _fr:     _parts.append(f"fr={_fr}")
            _fb_cookie_str = "; ".join(_parts)

        # Build JSON array format untuk curious_coder (Cookie-Editor format)
        _fb_cookie_json = []
        if _c_user:
            _fb_cookie_json.append({"name": "c_user", "value": _c_user, "domain": ".facebook.com"})
        if _xs:
            _fb_cookie_json.append({"name": "xs", "value": _xs, "domain": ".facebook.com"})
        if _datr:
            _fb_cookie_json.append({"name": "datr", "value": _datr, "domain": ".facebook.com"})
        if _fr:
            _fb_cookie_json.append({"name": "fr", "value": _fr, "domain": ".facebook.com"})

        _has_cookie = bool(_fb_cookie_str or _fb_cookie_json)
        print(f"   ↳ Facebook cookie: {'✓ tersedia (' + str(len(_fb_cookie_json)) + ' cookies)' if _has_cookie else '✗ tidak ada (max 3 posts)'}")

        # Actor 1: curious_coder/facebook-post-scraper
        # Dengan cookie → bisa ambil full timeline. Tanpa cookie → hanya 3 posts.
        _curious_input: Dict = {
            "urls":                [profile_url],
            "maxPosts":            10,
            "proxyConfiguration":  {"useApifyProxy": True},
        }
        if _has_cookie:
            # curious_coder menerima JSON array format (dari Cookie-Editor extension)
            if _fb_cookie_json:
                _curious_input["cookies"] = _fb_cookie_json
            elif _fb_cookie_str:
                _curious_input["cookies"] = _fb_cookie_str

        raw_curious = _run_posts_actor("curious_coder/facebook-post-scraper", _curious_input)

        # Normalise curious_coder output → format kompatibel dengan parser kita
        def _normalise_curious(item: Dict) -> Dict:
            """Convert curious_coder actor output ke format standar."""
            attachments = item.get("attachments") or []
            imgs = []
            video_url = ""
            cover_url = ""
            has_video = False
            for att in attachments:
                if not isinstance(att, dict): continue
                att_type = _safe_str(att.get("type") or "")
                media = att.get("media") or {}
                if not isinstance(media, dict): continue
                # Thumbnail (cover)
                thumb_uri = _safe_str(
                    (media.get("thumbnailImage") or {}).get("uri") or
                    (media.get("photo_image") or {}).get("uri") or
                    media.get("thumbnail") or ""
                )
                # Video URL
                vid = _safe_str(
                    (media.get("videoDeliveryResponseFragment") or {}).get("browser_native_hd_url") or
                    (media.get("videoDeliveryResponseFragment") or {}).get("browser_native_sd_url") or
                    (media.get("videoDeliveryLegacyFields") or {}).get("browser_native_hd_url") or
                    (media.get("videoDeliveryLegacyFields") or {}).get("browser_native_sd_url") or ""
                )
                if "video" in att_type or vid:
                    has_video = True
                    if vid and "facebook.com" not in vid:
                        video_url = video_url or vid
                    if thumb_uri and not cover_url:
                        cover_url = thumb_uri
                elif thumb_uri:
                    # Photo attachment
                    if thumb_uri not in imgs:
                        imgs.append(thumb_uri)
                    if not cover_url:
                        cover_url = thumb_uri
            ts = item.get("createdAt") or 0
            date_str = _parse_fb_date(ts) if ts else ""
            return {
                "postId":           _safe_str(item.get("id") or ""),
                "id":               _safe_str(item.get("id") or ""),
                "url":              _safe_str(item.get("url") or ""),
                "topLevelUrl":      _safe_str(item.get("url") or ""),
                "text":             _safe_str(item.get("text") or ""),
                "time":             date_str,
                "timestamp":        _safe_int(ts),
                "likes":            _safe_int(item.get("reactionCount") or 0),
                "comments":         _safe_int(item.get("commentCount") or 0),
                "shares":           _safe_int(item.get("shareCount") or 0),
                "viewsCount":       0,
                "isVideo":          has_video,
                "video_url":        video_url,
                "cover_url":        cover_url,
                "image_url":        cover_url if not has_video else "",
                "media":            [{"url": u, "thumbnail": u, "__typename": "Photo"} for u in imgs],
                "_raw_media_urls":  imgs,
                "taggedUsers":      [],
                "reactionLikeCount": _safe_int(item.get("reactionCount") or 0),
                "pageName":         clean_username,
                "user":             item.get("user") or {"name": clean_username},
            }

        if raw_curious:
            raw_curious = [_normalise_curious(x) for x in raw_curious]
            print(f"   ↳ Normalised curious: {len(raw_curious)} items")

        # Actor 1: spbotdel/facebook-profile-posts-all-photos-scraper
        # Khusus personal profiles, return semua foto termasuk yang tersembunyi di +N grid
        raw_spbotdel = _run_posts_actor("spbotdel/facebook-profile-posts-all-photos-scraper", {
            "profileUrls":               [profile_url],
            "maxPostsPerProfile":         10,
            "expandAllPhotos":            True,
            "omitPinnedPosts":            False,
            "mediaExpansionConcurrency":  3,
            "proxyConfiguration":         {"useApifyProxy": True},
        })

        # Normalise output dari spbotdel — field namanya berbeda dari actor standar
        def _normalise_spbotdel(item: Dict) -> Dict:
            stats = item.get("stats") or {}
            media_list = item.get("media") or []
            imgs = []
            has_video = False
            for m in media_list:
                if not isinstance(m, dict): continue
                u = _safe_str(m.get("source_url") or m.get("thumbnail_url") or "")
                if u: imgs.append(u)
                if m.get("type") == "video" or m.get("is_video"): has_video = True
            return {
                "postId":           item.get("source_post_id") or item.get("id") or "",
                "id":               item.get("source_post_id") or item.get("id") or "",
                "url":              item.get("source_url") or item.get("post_url") or "",
                "topLevelUrl":      item.get("source_url") or "",
                "text":             item.get("raw_text") or item.get("text") or "",
                "time":             item.get("created_at") or item.get("time") or "",
                "timestamp":        item.get("creation_time") or item.get("timestamp") or 0,
                "likes":            stats.get("reactions") or item.get("likes") or 0,
                "comments":         stats.get("comments") or item.get("comments") or 0,
                "shares":           stats.get("shares") or item.get("shares") or 0,
                "viewsCount":       item.get("video_view_count") or 0,
                "isVideo":          has_video,
                "media":            [{"url": u, "thumbnail": u, "__typename": "Photo"} for u in imgs],
                "_raw_media_urls":  imgs,
                "taggedUsers":      item.get("tagged_users") or [],
                "reactionLikeCount": stats.get("reactions") or 0,
                "pageName":         item.get("source_profile_name") or clean_username,
                "user": {
                    "name": item.get("source_profile_name") or clean_username,
                    "profilePic": (item.get("author") or {}).get("picture") or "",
                },
            }

        # Normalise jika output spbotdel
        if raw_spbotdel and (raw_spbotdel[0].get("source_post_id") or raw_spbotdel[0].get("source_url")):
            raw_spbotdel = [_normalise_spbotdel(x) for x in raw_spbotdel]
            print(f"   ↳ Normalised spbotdel: {len(raw_spbotdel)} items")

        # Actor 2: apify/facebook-posts-scraper — jalankan SELALU untuk dapat lebih banyak
        raw_apify = _run_posts_actor("apify/facebook-posts-scraper", {
            "startUrls":          [{"url": profile_url}],
            "resultsLimit":       10,
            "proxyConfiguration": {"useApifyProxy": True},
        })

        # Helper dedup — harus didefinisikan sebelum Actor 3
        def _get_url(item: Dict) -> str:
            return _safe_str(item.get("url") or item.get("topLevelUrl") or
                             item.get("source_url") or item.get("post_url") or "")

        # ── Gabungkan semua hasil, dedup by URL ──────────────────────────

        seen_urls: set = set()
        raw_items: List[Dict] = []
        # Prioritas: curious (cookie → lebih banyak), spbotdel (foto lengkap), apify
        for src in [raw_curious, raw_spbotdel, raw_apify]:
            for it in src:
                u = _get_url(it)
                pid = _safe_str(it.get("postId") or it.get("id") or "")
                key = u or pid
                if key and key not in seen_urls:
                    seen_urls.add(key)
                    raw_items.append(it)
                elif not key:
                    raw_items.append(it)

        # Sort by timestamp — terbaru dulu
        raw_items.sort(
            key=lambda x: x.get("timestamp") or 0,
            reverse=True
        )

        print(f"   ↳ Total combined items: {len(raw_items)} (curious={len(raw_curious)}, spbotdel={len(raw_spbotdel)}, apify={len(raw_apify)})")
        if raw_items:
            _s = raw_items[0]
            _imgs = _s.get('_raw_media_urls') or []
            print(f"   🔍 text={str(_s.get('text',''))[:50]} | imgs={len(_imgs)}")

        if not raw_items:
            return _build_empty_result(
                clean_username,
                f"@{clean_username} tidak ditemukan, akun privat, atau Facebook memblokir akses."
            )

        # ══════════════════════════════════════════════════════════════════
        # RUN 2 — Profile detail lengkap
        # ══════════════════════════════════════════════════════════════════
        # Field yang dikonfirmasi dari apify/facebook-pages-scraper:
        #   title, intro, followers, likes, followings,
        #   profilePictureUrl, coverPhotoUrl, websites, website,
        #   email, phone, address, creation_date,
        #   about_me (dict: {text, urls}), categories, rating, ratingOverall,
        #   ratingCount, pageId, facebookId
        full_name    = ""
        bio          = ""
        about_me_txt = ""
        followers    = 0
        followings   = 0
        page_likes   = 0
        verified     = False
        profile_pic  = ""
        cover_photo  = ""
        location     = ""
        address      = ""
        website      = ""
        email        = ""
        phone        = ""
        categories: List[str] = []
        rating       = ""
        rating_count = 0
        join_date    = ""

        print(f"   ↳ [2/4] Mengambil profile detail via apify/facebook-pages-scraper...")
        try:
            run_profile = client.actor("apify/facebook-pages-scraper").call(
                run_input={
                    "startUrls":          [{"url": profile_url}],
                    "proxyConfiguration": {"useApifyProxy": True},
                }
            )
            ds_profile = getattr(run_profile, "default_dataset_id", None)
            if ds_profile:
                profile_items = client.dataset(ds_profile).list_items().items or []
                if profile_items:
                    pi = profile_items[0]

                    # Nama
                    full_name = _safe_str(pi.get("title") or pi.get("name"))

                    # Bio / intro singkat
                    bio = _safe_str(pi.get("intro") or pi.get("description"))

                    # About me (teks panjang)
                    about_raw = pi.get("about_me")
                    if isinstance(about_raw, dict):
                        about_me_txt = _safe_str(about_raw.get("text"))
                    elif isinstance(about_raw, str):
                        about_me_txt = about_raw.strip()

                    # Followers & likes
                    followers  = _safe_int(pi.get("followers"))
                    page_likes = _safe_int(pi.get("likes"))
                    followings = _safe_int(pi.get("followings"))

                    # Foto profil & cover
                    profile_pic = _safe_str(pi.get("profilePictureUrl") or pi.get("profilePic"))
                    cover_photo = _safe_str(pi.get("coverPhotoUrl"))

                    # Lokasi & alamat
                    address  = _safe_str(pi.get("address"))
                    # address biasanya format: "Jalan X, Kota, Negara url_maps"
                    # ambil bagian sebelum "http" jika ada
                    if "http" in address:
                        address = address.split("http")[0].strip().rstrip(",").strip()
                    location = address  # alias

                    # Kontak
                    # websites bisa list atau string
                    raw_websites = pi.get("websites") or []
                    if isinstance(raw_websites, list) and raw_websites:
                        website = _safe_str(raw_websites[0])
                    elif isinstance(raw_websites, str):
                        website = raw_websites.strip()
                    else:
                        website = _safe_str(pi.get("website"))

                    email = _safe_str(pi.get("email"))
                    phone = _safe_str(pi.get("phone"))

                    # Tanggal pembuatan
                    join_date = _safe_str(pi.get("creation_date"))

                    # Kategori
                    raw_cats = pi.get("categories") or []
                    if isinstance(raw_cats, list):
                        categories = [_safe_str(c) for c in raw_cats if c]
                    elif isinstance(raw_cats, str):
                        categories = [raw_cats.strip()]

                    # Rating (khusus halaman bisnis)
                    rating_overall = pi.get("ratingOverall")
                    rating_cnt     = _safe_int(pi.get("ratingCount"))
                    if rating_overall:
                        rating = f"{rating_overall}% recommend ({rating_cnt} reviews)"
                        rating_count = rating_cnt
                    elif pi.get("rating"):
                        rating = _safe_str(pi.get("rating"))

                    # Verified — facebook-pages-scraper tidak expose field ini
                    # tapi CONFIRMED_OWNER_LABEL menandakan halaman terverifikasi
                    verified = bool(
                        pi.get("CONFIRMED_OWNER_LABEL") or
                        pi.get("verified") or
                        pi.get("is_verified")
                    )

                    print(
                        f"   ↳ Profile: {full_name} | "
                        f"Followers: {followers:,} | "
                        f"Likes: {page_likes:,} | "
                        f"Cover: {'✓' if cover_photo else '✗'}"
                    )
        except Exception as e_profile:
            print(f"   ⚠️ Profile scraper error (non-fatal): {e_profile}")

        # Fallback jika profile scraper gagal — ambil dari data post
        if not full_name:
            first_user  = (raw_items[0].get("user") or {})
            full_name   = _safe_str(first_user.get("name") or raw_items[0].get("pageName") or clean_username)
            profile_pic = profile_pic or _safe_str(first_user.get("profilePic"))

        # ══════════════════════════════════════════════════════════════════
        # PARSE POSTS & REPOSTS dari raw_items
        # ══════════════════════════════════════════════════════════════════
        posts:   List[Dict] = []
        reposts: List[Dict] = []

        for item in raw_items:
            post_id  = _safe_str(item.get("postId") or item.get("id") or item.get("post_id") or "")
            post_url = _safe_str(
                item.get("url") or item.get("topLevelUrl") or item.get("post_url") or
                item.get("postUrl") or item.get("facebookUrl") or
                (f"https://www.facebook.com/{clean_username}/posts/{post_id}" if post_id else "")
            )
            if not post_url:
                continue

            # ── Field dasar — support berbagai naming convention actor ────
            text = _safe_str(
                item.get("text") or item.get("content") or item.get("caption") or
                item.get("message") or item.get("postText") or ""
            )
            likes    = _safe_int(item.get("likes") or item.get("likesCount") or
                                  item.get("reactions_count") or item.get("reactionCount") or 0)
            comments = _safe_int(item.get("comments") or item.get("commentsCount") or
                                  item.get("comment_count") or 0)
            shares   = _safe_int(item.get("shares") or item.get("sharesCount") or
                                  item.get("share_count") or 0)
            plays    = _safe_int(item.get("viewsCount") or item.get("views") or
                                  item.get("playCount") or item.get("videoViews") or 0)

            # ── Timestamp variants ────────────────────────────────────────
            raw_time = (item.get("time") or item.get("timestamp") or
                        item.get("created_at") or item.get("date") or
                        item.get("publishedAt") or "")
            created_at = _parse_fb_date(raw_time)
            ts_int = 0
            if str(raw_time).isdigit():
                ts_int = int(raw_time)
            elif created_at:
                try:
                    import calendar
                    ts_int = int(time_module.mktime(
                        time_module.strptime(created_at, "%Y-%m-%d")
                    ))
                except Exception:
                    pass
            created_at_iso = (
                time_module.strftime("%Y-%m-%dT%H:%M:%S.000Z",
                                     time_module.gmtime(ts_int))
                if ts_int else ""
            )

            # ── Media — extended (image_urls list, media_list, media_count) ─
            # Support berbagai naming: media, photos, images, attachments
            media_raw  = item.get("media") or item.get("photos") or item.get("images") or item.get("attachments") or []
            # Normalise: kadang media adalah list of strings (URL langsung)
            if media_raw and isinstance(media_raw[0], str):
                media_raw = [{"url": u} for u in media_raw if u]
            image_url = video_url = cover_url = ""
            image_urls_list: List[str] = []
            media_list_full: List[Dict] = []
            ocr_texts: List[str] = []

            # ── spbotdel actor: _raw_media_urls sudah berisi semua foto ──────
            _raw_media_urls = item.get("_raw_media_urls") or []
            for _ru in _raw_media_urls:
                if _ru and "http" in _ru and _ru not in image_urls_list:
                    image_urls_list.append(_ru)
                    if not image_url:
                        image_url = cover_url = _ru

            # ── Top-level image URL — hanya tambah jika belum ada di list ──
            _top_img = _safe_str(
                item.get("imageUrl") or item.get("image_url") or
                item.get("photo") or item.get("coverImage") or ""
            )
            if _top_img and "http" in _top_img and _top_img not in image_urls_list:
                image_urls_list.append(_top_img)
                if not image_url:
                    image_url = cover_url = _top_img

            # ── Top-level video URL (beberapa actor return di root item) ──
            _top_vid = _safe_str(
                item.get("videoUrl") or
                item.get("video_url") or
                item.get("videoHD") or
                item.get("videoSD") or
                (item.get("videoData") or {}).get("videoUrl") or
                (item.get("attachedMedia") or [{}])[0].get("videoUrl") if item.get("attachedMedia") else ""
            )
            if _top_vid and ("http" in _top_vid):
                video_url = _top_vid

            for media in media_raw:
                if not isinstance(media, dict):
                    continue
                thumb = (
                    media.get("thumbnail") or
                    (media.get("photo_image") or {}).get("uri") or
                    media.get("url") or
                    media.get("image") or
                    media.get("src") or
                    media.get("imageUrl") or
                    media.get("photo") or ""
                )
                # Cari video URL dari semua kemungkinan field Apify
                vid = _safe_str(
                    media.get("videoUrl") or
                    media.get("videoHD") or
                    media.get("videoSD") or
                    (media.get("videoData") or {}).get("videoUrl") or
                    (media.get("videoData") or {}).get("videoHD") or
                    (media.get("videoData") or {}).get("videoSD") or
                    (media.get("video") or {}).get("url") or
                    media.get("src") or ""
                )
                # Hanya pakai jika ini URL valid (bukan halaman FB)
                if vid and "http" in vid and "facebook.com" not in vid:
                    video_url = video_url or vid
                elif vid and "video" in vid and "facebook.com" in vid and not video_url:
                    # Ini URL halaman FB — simpan sebagai fallback
                    pass
                if thumb:
                    _thumb_str = _safe_str(thumb)
                    if not cover_url:
                        cover_url = image_url = _thumb_str
                    # Deduplicate — jangan tambah URL yang sama dua kali
                    if _thumb_str and _thumb_str not in image_urls_list:
                        image_urls_list.append(_thumb_str)
                # media_list entry
                mtype_raw = _safe_str(media.get("__typename") or "")
                mtype = "video" if (vid or "Video" in mtype_raw) else "image"
                media_list_full.append({
                    "type":    mtype,
                    "url":     vid if mtype == "video" else _safe_str(thumb),
                    "width":   _safe_int(media.get("width") or (media.get("photo_image") or {}).get("width")),
                    "height":  _safe_int(media.get("height") or (media.get("photo_image") or {}).get("height")),
                    "size_mb": 0,
                })
                ocr = _safe_str(media.get("ocrText"))
                if ocr:
                    ocr_texts.append(ocr)

            media_count = len(media_raw)
            if video_url or "reel" in post_url or "videos" in post_url:
                media_type = "video"
            elif media_count > 1:
                media_type = "carousel"
            elif media_count == 1:
                media_type = "image"
            else:
                media_type = "text"

            hashtags = re.findall(r"#(\w+)", text)
            mentions = re.findall(r"@(\w+)", text)
            urls_in_text = [u for u in re.findall(r"https?://\S+", text)
                            if "facebook.com" not in u]

            # Tagged users from actor — bisa object {id,name,url} atau string
            tagged_raw = item.get("taggedUsers") or item.get("tagged_users") or item.get("tagged") or []
            tagged_users = []
            for t in tagged_raw:
                if not t: continue
                if isinstance(t, dict):
                    name = _safe_str(t.get("name") or t.get("username") or "")
                    if name: tagged_users.append(name)
                elif isinstance(t, str):
                    tagged_users.append(t)

            # Tambah mentions dari teks + tagged_users untuk deteksi mentions tab
            # Gabungkan mentions dari @text + tagged_users agar mentions tab berisi data
            all_mentions = list(set(mentions + tagged_users))

            # ── Repost detection ──────────────────────────────────────────
            shared_post_data = item.get("sharedPost") or item.get("shared_post")
            is_repost = bool(shared_post_data)

            # Tambahan: cek field lain yang bisa menandakan share
            if not is_repost:
                # Apify kadang return retweetedPost atau originalPost
                _orig = item.get("originalPost") or item.get("retweetedPost") or {}
                if _orig:
                    is_repost = True
                    shared_post_data = _orig

            # Cek pageName — kalau postingan berasal dari page berbeda
            if not is_repost:
                item_page = _safe_str(item.get("pageName") or item.get("page") or "").strip().lower()
                clean_lower_fb = clean_username.lower().replace(" ", "").replace("_", "")
                item_page_norm = item_page.replace(" ", "").replace("_", "")
                # Hanya tandai repost kalau page_name sangat berbeda (tidak hanya case/space)
                if item_page and item_page_norm and item_page_norm != clean_lower_fb:
                    # Cek apakah URL post milik target
                    _pu = _safe_str(item.get("url") or item.get("postUrl") or "").lower()
                    _target_in_url = clean_username.lower() in _pu or clean_lower_fb in _pu
                    if not _target_in_url:
                        is_repost = True
                        shared_post_data = {"text": text, "user": {"name": item.get("pageName")}}

            # Cek facebookUrl — kalau URL post bukan milik target
            if not is_repost:
                item_fb_url = _safe_str(item.get("facebookUrl") or "").lower().rstrip("/")
                target_variants = [
                    clean_username.lower(),
                    clean_username.lower().replace(" ", ""),
                    profile_url.lower().rstrip("/"),
                ]
                if item_fb_url and not any(v in item_fb_url for v in target_variants if v):
                    # Hanya jika URL sangat berbeda
                    if "facebook.com" in item_fb_url and "posts" in item_fb_url:
                        is_repost = True
                        shared_post_data = shared_post_data or {"text": text, "user": {}}

            shared_post_data = shared_post_data or {}

            # Debug — print untuk item pertama yang terdeteksi sebagai repost
            if is_repost and len(reposts) == 0:
                print(f"   🔍 [FB repost debug] sharedPost={bool(item.get('sharedPost'))} "
                      f"pageName={item.get('pageName')} url={_safe_str(item.get('facebookUrl'))[:50]}")

            # Reactions
            reactions = {
                "like":  _safe_int(item.get("reactionLikeCount")),
                "love":  _safe_int(item.get("reactionLoveCount")),
                "care":  _safe_int(item.get("reactionCareCount")),
                "haha":  _safe_int(item.get("reactionHahaCount")),
                "wow":   _safe_int(item.get("reactionWowCount")),
                "sad":   _safe_int(item.get("reactionSadCount")),
                "angry": _safe_int(item.get("reactionAngryCount")),
            }
            reactions_total = sum(reactions.values())

            ocr_combined = " | ".join(ocr_texts)
            is_pinned    = bool(item.get("isPinned") or item.get("is_pinned"))
            is_story     = bool("stories" in post_url)
            is_ad        = bool((item.get("pageAdLibrary") or {}).get("is_business_page_active"))

            # ── Content analysis ──────────────────────────────────────────
            ca = _analyze_facebook_post(
                text=text, media_type=media_type, media_count=media_count,
                hashtags=hashtags, mentions=mentions,
                likes=likes, comments=comments, shares=shares, plays=plays,
                reactions=reactions, page_name=full_name or clean_username,
                created_at=created_at, is_ad=is_ad, is_repost=is_repost,
                ocr_text=ocr_combined,
            )

            # ── Visual description (text-based) ───────────────────────────
            if media_type == "video":
                vd_prefix = "Video ini"
            elif media_type == "carousel":
                vd_prefix = f"Galeri {media_count} foto/gambar ini"
            elif media_type == "image":
                vd_prefix = "Gambar/foto ini"
            else:
                vd_prefix = "Postingan ini"
            clean_cap = re.sub(r"[#@]\S+", "", text).strip()[:300]
            visual_description = (
                f"{vd_prefix} bertemakan '{ca['topic']}' dengan suasana {ca['mood']}. "
                + (f"Konten visual berisi elemen: {ca['objects']}. " if ca["objects"] else "")
                + (f"Caption: \"{clean_cap}\"." if clean_cap else "")
                + (f" Teks dalam gambar: \"{ocr_combined[:100]}\"." if ocr_combined else "")
            )

            post_entry = {
                # ── ID & URL ─────────────────────────────────────────────
                "id":                    post_id,
                "post_id":               post_id,
                "content":               text,
                "post_url":              post_url,
                # ── Timestamps ───────────────────────────────────────────
                "created_at":            created_at,
                "created_at_timestamp":  ts_int,
                "created_at_iso":        created_at_iso,
                # ── Engagement ───────────────────────────────────────────
                "likes":                 likes,
                "comments":              comments,
                "shares":                shares,
                "plays":                 plays,
                # ── Reactions ────────────────────────────────────────────
                "reactions":             reactions,
                "reactions_total":       reactions_total,
                # ── Media ────────────────────────────────────────────────
                "video_url":             video_url,
                "image_url":             image_url,
                "image_urls":            image_urls_list,
                "cover_url":             cover_url,
                "media_type":            media_type,
                "media_count":           media_count,
                "media_list":            media_list_full,
                # ── Entities ─────────────────────────────────────────────
                "hashtags":              hashtags,
                "mentions":              all_mentions,
                "tagged_users":          tagged_users,
                "urls":                  urls_in_text,
                # ── Flags ────────────────────────────────────────────────
                "is_ad":                 is_ad,
                "is_repost":             is_repost,
                "is_sponsored":          is_ad,
                "is_pinned":             is_pinned,
                "is_story":              is_story,
                # ── Content Analysis ─────────────────────────────────────
                "visual_description":    visual_description,
                "topic":                 ca["topic"],
                "mood":                  ca["mood"],
                "objects":               ca["objects"],
                "activity":              ca["activity"],
                "sentiment":             {"label": "NEUTRAL", "score": 0.5},
                "content_analysis":      ca,
                # ── Comments ─────────────────────────────────────────────
                "comments_data":         [],
                "comments_count_total":  comments,
                "comments_count_visible": 0,
                # ── OCR ──────────────────────────────────────────────────
                "ocr_from_media":        ocr_combined,
                # ── Misc ─────────────────────────────────────────────────
                "duration_sec":          0,
                "music":                 {"title": "", "author": ""},
            }

            if is_repost:
                shared = shared_post_data
                shared_user = shared.get("user") or {}
                ca_r = _analyze_facebook_post(
                    text=text, media_type=media_type, media_count=media_count,
                    hashtags=hashtags, mentions=mentions,
                    likes=likes, comments=comments, shares=shares, plays=plays,
                    reactions=reactions, page_name=full_name or clean_username,
                    created_at=created_at, is_ad=is_ad, is_repost=True,
                    ocr_text=ocr_combined,
                )
                reposts.append({
                    "video_url":           post_url,
                    "original_author":     _safe_str(shared_user.get("name")),
                    "original_author_url": _safe_str(shared_user.get("url") or shared_user.get("profileUrl")),
                    "original_caption":    _safe_str(shared.get("text") or text)[:300],
                    "repost_date":         created_at,
                    "hashtags":            hashtags,
                    "media_type":          media_type,
                    "image_url":           image_url,
                    "metrics":             {"likes": likes, "comments": comments,
                                            "shares": shares, "plays": plays},
                    "reactions":           reactions,
                    "reactions_total":     reactions_total,
                    "sentiment":           {"label": "NEUTRAL", "score": 0.5},
                    "content_analysis":    ca_r,
                    "content_description": ca_r["ai_description"][:300],
                })
            else:
                posts.append(post_entry)

        # ══════════════════════════════════════════════════════════════════
        # RUN 2.5 — Pisah posts dari reels (pakai data dari posts scraper)
        # ══════════════════════════════════════════════════════════════════
        # Pisah: posts yang URL-nya /reel/ atau /videos/ → masuk reels_from_posts
        reels_from_posts: List[Dict] = []
        clean_posts: List[Dict] = []
        for p in posts:
            pu = p.get("post_url", "")
            if "/reel/" in pu or "/videos/" in pu:
                reels_from_posts.append(p)
            else:
                clean_posts.append(p)
        posts = clean_posts

        # Gunakan reels yang sudah tertarik dari posts scraper (hemat credit Apify)
        reels: List[Dict] = reels_from_posts[:10]
        print(f"   ↳ [2.5/4] Reels dari posts: {len(reels)} item (tanpa actor tambahan)")

        # ══════════════════════════════════════════════════════════════════
        # RUN 3 — Foto publik: scrape dari /photos page + fallback dari posts
        # ══════════════════════════════════════════════════════════════════
        photos: List[Dict] = []
        photos_url = f"{profile_url}/photos"
        print(f"   ↳ [3/4] Mengambil foto dari {photos_url}...")

        # Strategy 1: curious_coder dengan cookie → bisa akses /photos page
        if _has_cookie:
            try:
                run_ph = client.actor("curious_coder/facebook-post-scraper").call(
                    run_input={
                        "urls":               [photos_url],
                        "maxPosts":           20,
                        "cookies":            _fb_cookie_str,
                        "proxyConfiguration": {"useApifyProxy": True},
                    }
                )
                ds_ph = getattr(run_ph, "default_dataset_id", None)
                if ds_ph:
                    ph_items = client.dataset(ds_ph).list_items().items or []
                    ph_items = [x for x in ph_items if not x.get("error")]
                    print(f"   ↳ Photos dari /photos page: {len(ph_items)}")
                    seen_ph = set()
                    for ph in ph_items:
                        # Extract foto dari attachments
                        attachments = ph.get("attachments") or []
                        for att in attachments:
                            if not isinstance(att, dict): continue
                            media = att.get("media") or {}
                            if not isinstance(media, dict): continue
                            # Photo URI
                            photo_uri = _safe_str(
                                (media.get("photo_image") or {}).get("uri") or
                                (media.get("thumbnailImage") or {}).get("uri") or
                                media.get("thumbnail") or ""
                            )
                            photo_page_url = _safe_str(
                                att.get("url") or ph.get("url") or ""
                            )
                            if photo_uri and photo_uri not in seen_ph:
                                seen_ph.add(photo_uri)
                                photos.append({
                                    "image_url":  photo_uri,
                                    "photo_page": photo_page_url,
                                    "caption":    _safe_str(ph.get("text") or "")[:100],
                                    "album":      "Photos",
                                    "likes":      _safe_int(ph.get("reactionCount") or 0),
                                    "date":       _parse_fb_date(ph.get("createdAt") or ""),
                                })
            except Exception as e_ph:
                print(f"   ⚠️ curious_coder /photos error: {e_ph}")

        # Strategy 2: simpleapi/facebook-photos-scraper (tanpa cookie)
        if len(photos) < 5:
            try:
                run_photos = client.actor("simpleapi/facebook-photos-scraper").call(
                    run_input={
                        "startUrls":          [{"url": photos_url}],
                        "resultsLimit":       20,
                        "proxyConfiguration": {"useApifyProxy": True},
                    }
                )
                ds_photos = getattr(run_photos, "default_dataset_id", None)
                if ds_photos:
                    photo_items = client.dataset(ds_photos).list_items().items or []
                    print(f"   ↳ simpleapi photos: {len(photo_items)}")
                    seen_ph2 = {p["image_url"] for p in photos}
                    for ph in photo_items:
                        photo_url = _safe_str(ph.get("imageUrl") or ph.get("url") or ph.get("src") or "")
                        if not photo_url or photo_url in seen_ph2: continue
                        seen_ph2.add(photo_url)
                        photos.append({
                            "image_url":  photo_url,
                            "photo_page": _safe_str(ph.get("photoUrl") or ph.get("facebookUrl") or ""),
                            "caption":    _safe_str(ph.get("caption") or ph.get("text") or ""),
                            "album":      _safe_str(ph.get("albumName") or "Photos"),
                            "likes":      _safe_int(ph.get("likes") or ph.get("likesCount") or 0),
                            "date":       _parse_fb_date(ph.get("date") or ph.get("timestamp") or ""),
                        })
            except Exception as e_simpleapi:
                print(f"   ⚠️ simpleapi photos error: {e_simpleapi}")

        # Strategy 3: fallback dari image_urls di setiap post (carousel)
        if len(photos) < 5:
            print(f"   ↳ Photo fallback dari posts carousel...")
            seen_photo_urls = {p["image_url"] for p in photos}
            for p_item in posts[:30]:
                if p_item.get("media_type") == "video" or p_item.get("video_url"):
                    continue
                img_list = p_item.get("image_urls") or []
                if not img_list and p_item.get("image_url"):
                    img_list = [p_item["image_url"]]
                for img_u in img_list:
                    if not img_u or img_u in seen_photo_urls:
                        continue
                    seen_photo_urls.add(img_u)
                    photos.append({
                        "image_url":  img_u,
                        "photo_page": p_item.get("post_url", ""),
                        "caption":    p_item.get("content", "")[:100],
                        "album":      "Timeline",
                        "likes":      p_item.get("likes", 0),
                        "date":       p_item.get("created_at", ""),
                    })
                    if len(photos) >= 20:
                        break
                if len(photos) >= 20:
                    break
            print(f"   ↳ Total photos: {len(photos)}")

        # ══════════════════════════════════════════════════════════════════
        # RUN 4 — Komentar: ambil semua, pisah jadi comments_data & user_comments
        # ══════════════════════════════════════════════════════════════════
        # Output facebook-comments-scraper yang dikonfirmasi:
        #   profileName, profileId, profileUrl, text, date, likesCount,
        #   commentUrl, facebookUrl (= post url), threadingDepth, facebookId
        #
        # Strategi:
        #   - Semua komentar → simpan ke comments_data per post (max 5 per post)
        #   - Filter komentar oleh si target → simpan ke user_comments
        #
        # Filter identitas target (multi-signal):
        #   1. profileId == target_fb_id  (paling akurat)
        #   2. profileName == full_name   (exact match)
        #   3. profileName == clean_username (username sebagai nama)
        #   4. profileUrl mengandung clean_username (link profil target)
        #   5. partial match nama — ambil jika salah satu token nama ada
        # ══════════════════════════════════════════════════════════════════
        user_comments: List[Dict] = []

        # Ambil facebookId target dari post item pertama sebagai anchor
        target_fb_id = _safe_str(
            (raw_items[0].get("user") or {}).get("id") or
            raw_items[0].get("facebookId")
        )

        # Token nama target (untuk partial match)
        # misal full_name = "Anies Rasyid Baswedan" → tokens = {"anies", "baswedan"}
        name_tokens: set = set()
        if full_name:
            name_tokens = {t.lower() for t in full_name.split() if len(t) > 2}

        # URL profil target (bisa jadi https://www.facebook.com/username atau id)
        target_profile_urls = {
            profile_url.lower().rstrip("/"),
            f"https://www.facebook.com/{clean_username}".lower(),
        }
        if target_fb_id:
            target_profile_urls.add(f"https://www.facebook.com/{target_fb_id}".lower())

        # Sort posts dari terbaru ke terlama sebelum ambil untuk comment scraping
        # Gunakan timestamp (Unix integer) untuk sort yang lebih akurat
        posts_sorted_by_date = sorted(
            posts,
            key=lambda p: (
                p.get("created_at_timestamp") or
                int(p.get("created_at", "0").replace("-", "").replace(" ", "") or 0)
            ),
            reverse=True  # terbaru dulu
        )

        # Gunakan 10 post TERBARU — exclude reels karena FB blokir komentar reel tanpa login
        _non_reel_posts = [p for p in posts_sorted_by_date if "/reel/" not in (p.get("post_url") or "")]
        _reel_posts     = [p for p in posts_sorted_by_date if "/reel/" in (p.get("post_url") or "")]
        _sorted_posts   = _non_reel_posts + _reel_posts  # non-reel terbaru dulu

        top_post_urls = [p["post_url"] for p in _sorted_posts[:30] if p["post_url"]]
        print(f"   ↳ [4/4] Comment URLs (terbaru dulu): {len([u for u in top_post_urls if '/reel/' not in u])} posts, "
              f"{len([u for u in top_post_urls if '/reel/' in u])} reels")

        # Buat lookup post by url untuk isi comments_data
        post_url_index: Dict[str, int] = {p["post_url"]: i for i, p in enumerate(posts)}

        if top_post_urls:
            print(f"   ↳ [4/4] Mengambil komentar untuk {len(top_post_urls)} post teratas...")
            try:
                run_comments = client.actor("apify/facebook-comments-scraper").call(
                    run_input={
                        "startUrls":          [{"url": u} for u in top_post_urls],
                        "resultsLimit":       1000,  # ambil sebanyak mungkin
                        "proxyConfiguration": {"useApifyProxy": True},
                    }
                )
                ds_comments = getattr(run_comments, "default_dataset_id", None)
                if ds_comments:
                    comment_items = client.dataset(ds_comments).list_items().items or []
                    # Filter out error items — scraper kadang return {'error', 'errorDescription'}
                    comment_items = [ci for ci in comment_items
                                     if not ci.get("error") and ci.get("profileName")]
                    print(f"   ↳ Total komentar valid: {len(comment_items)}")

                    target_name_lower     = full_name.lower() if full_name else ""
                    target_username_lower = clean_username.lower()

                    # Pre-compute username variants — di luar loop untuk efisiensi
                    _uv = {
                        clean_username.lower(),
                        clean_username.lower().replace(".", "").replace("_", ""),
                    }
                    for _sep in [".", "_"]:
                        if _sep in clean_username:
                            _uv.add(clean_username.lower().split(_sep)[0])
                    _uv = {v for v in _uv if len(v) > 2}

                    # Counter comments_data per post (max 5 per post)
                    comments_per_post: Dict[str, int] = {}

                    for ci in comment_items:
                        if ci.get("errorCode"):
                            continue

                        c_author      = _safe_str(
                            ci.get("profileName") or
                            (ci.get("author") or {}).get("name") or
                            ci.get("authorName")
                        )
                        c_author_lower = c_author.lower()
                        c_author_id    = _safe_str(
                            ci.get("profileId") or
                            (ci.get("author") or {}).get("id")
                        )
                        c_author_url   = _safe_str(
                            ci.get("profileUrl") or
                            (ci.get("author") or {}).get("url") or ""
                        ).lower().rstrip("/")

                        c_text     = _safe_str(ci.get("text") or ci.get("message"))
                        c_url      = _safe_str(ci.get("commentUrl") or ci.get("url"))
                        c_post_url = _safe_str(ci.get("facebookUrl") or ci.get("inputUrl") or ci.get("postUrl"))
                        c_likes    = _safe_int(ci.get("likesCount") or ci.get("likes"))
                        c_date     = _parse_fb_date(ci.get("date") or ci.get("timestamp"))
                        is_reply   = _safe_int(ci.get("threadingDepth")) > 0

                        if not c_text:
                            continue

                        # ── Simpan ke comments_data per post (semua komentar) ──
                        # Cari post yang paling cocok dengan c_post_url
                        matched_post_url = ""
                        for pu in post_url_index:
                            if c_post_url and (
                                c_post_url == pu or
                                pu in c_post_url or
                                c_post_url in pu
                            ):
                                matched_post_url = pu
                                break

                        if matched_post_url:
                            idx = post_url_index[matched_post_url]
                            cnt = comments_per_post.get(matched_post_url, 0)
                            if cnt < 5:
                                posts[idx]["comments_data"].append({
                                    "comment_id":    _safe_str(ci.get("facebookId") or ci.get("id") or ""),
                                    "author":        c_author,
                                    "author_id":     c_author_id,
                                    "author_url":    _safe_str(ci.get("profileUrl") or ""),
                                    "content":       c_text,
                                    "likes":         c_likes,
                                    "date":          c_date,
                                    "date_timestamp": 0,
                                    "date_iso":      "",
                                    "is_reply":      is_reply,
                                    "reply_to":      "",
                                    "reply_to_author": "",
                                    "comment_url":   c_url,
                                    "depth":         _safe_int(ci.get("threadingDepth")),
                                    "sentiment":     {"label": "NEUTRAL", "score": 0.5},
                                })
                                posts[idx]["comments_count_visible"] = cnt + 1
                                comments_per_post[matched_post_url] = cnt + 1

                        # ── Filter: apakah komentar ini dari si target? ────────
                        is_target = False

                        # ── Signal 1: Facebook ID exact match (paling akurat) ──
                        if target_fb_id and c_author_id and c_author_id == target_fb_id:
                            is_target = True

                        # ── Signal 2: Nama persis sama dengan full_name ────────
                        if not is_target and target_name_lower and c_author_lower == target_name_lower:
                            is_target = True

                        # ── Signal 3: Username variants match author name ───────
                        if not is_target and any(c_author_lower == v for v in _uv):
                            is_target = True

                        # ── Signal 4: profileUrl mengandung username/FB ID ──────
                        if not is_target and c_author_url:
                            if any(v in c_author_url for v in _uv):
                                is_target = True
                            if target_fb_id and target_fb_id in c_author_url:
                                is_target = True
                            if c_author_url in target_profile_urls:
                                is_target = True

                        # ── Signal 5: Partial name token match ────────────────
                        # "Mulyana" → match "Mulyana Yans", "Mulyana F", dst
                        if not is_target and name_tokens:
                            c_tokens = {t.lower() for t in c_author.split() if len(t) > 2}
                            if name_tokens & c_tokens:
                                is_target = True

                        # ── Signal 6: Author name mengandung bagian username ───
                        if not is_target:
                            for _part in _uv:
                                if len(_part) > 3 and _part in c_author_lower:
                                    is_target = True
                                    break

                        # ── Signal 7: First name match (untuk nama pendek) ─────
                        # "mulyana.652357" → first token = "mulyana"
                        if not is_target:
                            _first = clean_username.lower().split(".")[0].split("_")[0]
                            if len(_first) > 3:
                                if _first == c_author_lower:
                                    is_target = True
                                elif c_author_url and _first in c_author_url:
                                    is_target = True

                        # ── Signal 8: Full_name first token (Mulyana → mulyana) ─
                        if not is_target and full_name:
                            _fn_first = full_name.lower().split()[0] if full_name.strip() else ""
                            if len(_fn_first) > 3 and _fn_first in c_author_lower:
                                is_target = True

                        # Debug: print komentar yang ditemukan
                        if is_target and len(user_comments) == 0:
                            print(f"   ✅ [UC match] author='{c_author}' id='{c_author_id}' url='{c_author_url[:50]}'")
                        elif not is_target and len(user_comments) < 2:
                            print(f"   🔍 [UC skip] author='{c_author}' vs target='{full_name}'/{clean_username} fb_id='{target_fb_id}'")

                        if not is_target:
                            continue

                        # Cari caption post yang dikomentari
                        post_caption = ""
                        if matched_post_url:
                            post_caption = posts[post_url_index[matched_post_url]]["content"][:100]
                        else:
                            # fallback: cari manual
                            for p in posts:
                                if p["post_url"] and c_post_url and (
                                    c_post_url == p["post_url"] or
                                    p["post_url"] in c_post_url
                                ):
                                    post_caption = p["content"][:100]
                                    break

                        user_comments.append({
                            "post_url":     c_post_url or c_url,
                            "post_caption": post_caption,
                            "post_author":  clean_username,
                            "content":      c_text,
                            "likes":        c_likes,
                            "is_reply":     is_reply,
                            "reply_to":     "",
                            "created_at":   c_date,
                            "sentiment":    {"label": "NEUTRAL", "score": 0.5}
                        })

                    print(f"   ↳ user_comments (by target): {len(user_comments)}")
                    total_cd = sum(len(p["comments_data"]) for p in posts)
                    print(f"   ↳ comments_data (others): {total_cd} across {len(posts)} posts")

            except Exception as e_comments:
                print(f"   ⚠️ Comment scraper error (non-fatal): {e_comments}")

        # ── Trim & hitung total ───────────────────────────────────────────
        # Sort user_comments dari terbaru dulu
        user_comments.sort(key=lambda x: x.get("created_at") or "0000-00-00", reverse=True)
        user_comments = user_comments[:100]  # ambil lebih banyak
        reposts       = reposts[:10]
        photos        = photos[:20]  # lebih banyak foto

        total_likes    = sum(p["likes"]    for p in posts)
        total_comments = sum(p["comments"] for p in posts)
        total_shares   = sum(p["shares"]   for p in posts)

        print(
            f"   ↳ Posts: {len(posts)} | "
            f"Photos: {len(photos)} | "
            f"user_comments: {len(user_comments)} | "
            f"reposts: {len(reposts)} | "
            f"reels: {len(reels)}"
        )

        return {
            "status":      "success",
            "platform":    "facebook",
            "username":    clean_username,

            # ── Profile lengkap ──────────────────────────────────────────
            "full_name":   full_name,
            "bio":         bio,
            "about_me":    about_me_txt,
            "followers":   followers,
            "following":   followings,
            "page_likes":  page_likes,
            "verified":    verified,
            "join_date":   join_date,
            "profile_pic": profile_pic,
            "cover_photo": cover_photo,
            "location":    location,
            "address":     address,
            "website":     website,
            "email":       email,
            "phone":       phone,
            "categories":  categories,
            "rating":      rating,
            "rating_count": rating_count,

            # ── Statistik ────────────────────────────────────────────────
            "total_posts":    len(posts),
            "total_likes":    total_likes,
            "total_comments": total_comments,
            "total_shares":   total_shares,
            "has_text":       any(p["content"] for p in posts),

            # ── Data ─────────────────────────────────────────────────────
            "posts":         posts,
            "reels":         reels,
            "photos":        photos,
            "user_comments": user_comments,
            "reposts":       reposts,
            "scrape_errors": []
        }

    except Exception as e:
        import traceback
        err = f"Facebook scrape error: {str(e)}"
        print(f"   ❌ {err}")
        print(traceback.format_exc())
        return _build_empty_result(clean_username, err)


# ─────────────────────────────────────────────────────────────────────────────
# ASYNC WRAPPER — dipanggil dari scraper_engine.py
# ─────────────────────────────────────────────────────────────────────────────
async def _facebook_scrape_real(username: str, apify_token: str = "") -> Dict:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        partial(_facebook_scrape_sync, username, apify_token)
    )
