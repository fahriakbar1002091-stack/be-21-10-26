"""
ai_engine.py - Social Radar AI Analysis Engine v3.0
Menggunakan DistilBERT untuk:
1. Sentimen PER POSTINGAN (POSITIVE / NEGATIVE / NEUTRAL)
2. Sentimen OVERALL + BREAKDOWN (persentase)
3. Risk score AKURAT berdasarkan konten nyata
4. Personality traits (OCEAN model)
5. Summary OBJEKTIF berdasarkan fakta
6. Red flags & green flags berdasarkan konten
7. Rekomendasi & suitable roles
"""

from __future__ import annotations

import re
import math
from typing import Dict, List, Any, Optional

# ─────────────────────────────────────────────────────────────────────────────
# LOAD MODEL DistilBERT sekali saat module diimport
# ─────────────────────────────────────────────────────────────────────────────
_sentiment_pipeline = None

def _load_model():
    global _sentiment_pipeline
    if _sentiment_pipeline is not None:
        return _sentiment_pipeline

    try:
        from transformers import pipeline as hf_pipeline
        print("⏳ [AI] Loading DistilBERT sentiment model...")
        _sentiment_pipeline = hf_pipeline(
            "sentiment-analysis",
            model="distilbert-base-uncased-finetuned-sst-2-english",
            truncation=True,
            max_length=512
        )
        print("✅ [AI] DistilBERT model loaded!")
    except Exception as e:
        print(f"⚠️ [AI] Gagal load DistilBERT: {e} — menggunakan rule-based fallback")
        _sentiment_pipeline = None

    return _sentiment_pipeline


# ─────────────────────────────────────────────────────────────────────────────
# SENSITIVE KEYWORDS untuk risk scoring
# ─────────────────────────────────────────────────────────────────────────────
_HIGH_RISK_KEYWORDS = [
    # Kekerasan & ancaman
    "kill", "murder", "violence", "attack", "bomb", "weapon", "shoot", "stab",
    "bunuh", "ancam", "serang", "bom", "senjata",
    # Ujaran kebencian
    "hate", "racist", "racism", "nazi", "terrorist", "extremist",
    "rasis", "teroris", "ekstremis", "kafir", "sesat",
    # SARA
    "n****", "anjing", "babi", "monyet",
    # Pornografi
    "porn", "nude", "naked", "sex tape",
    # Narkoba
    "drug", "cocaine", "heroin", "meth", "ganja", "narkoba", "sabu",
    # Penipuan
    "scam", "fraud", "hack", "phishing", "penipuan", "tipu",
]

_MEDIUM_RISK_KEYWORDS = [
    "protest", "riot", "controversial", "fake", "lie", "cheat",
    "fight", "drama", "exposed", "cancel", "banned",
    "demo", "rusuh", "kontroversial", "palsu", "bohong", "curang",
    "berantem", "skandal", "tersangka",
]

_POSITIVE_KEYWORDS = [
    # Inggris
    "love", "happy", "fun", "amazing", "great", "wonderful", "beautiful",
    "success", "win", "joy", "laugh", "smile", "thank", "grateful",
    "awesome", "excited", "blessed", "perfect", "fantastic", "enjoy",
    "proud", "inspired", "good", "nice", "best", "wow", "cool",
    # Indonesia positif jelas
    "senang", "bahagia", "lucu", "keren", "sukses", "menang", "terima kasih",
    "syukur", "indah", "luar biasa", "bangga", "seru", "asik", "mantap",
    "bagus", "hebat", "salut", "sayang", "cinta", "gembira", "semangat",
    "berhasil", "bersyukur", "menyenangkan", "ramah", "positif", "damai",
    "tenang", "nyaman", "sehat", "selamat", "alhamdulillah", "subhanallah",
    "keren banget", "top", "juara", "bestie", "gaskeun", "ayok", "yuk",
    "amazing", "wow", "hore", "yeay", "yeey", "finally",
]

_NEGATIVE_KEYWORDS_ID = [
    # Kata kasar Indonesia
    "anjing", "anjir", "anjrit", "babi", "bangsat", "bajingan", "keparat",
    "sialan", "brengsek", "kampret", "goblok", "tolol", "bodoh", "idiot",
    "dungu", "geblek", "bego", "tai", "taik", "kontol", "memek",
    # Emosi negatif kuat
    "nyebelin", "sebel", "kesel", "marah", "benci", "bete", "gagal",
    "payah", "kecewa", "nyesel", "menyesal", "sedih", "nangis",
    "susah", "susah banget", "capek", "cape", "lelah", "stress",
    "pusing", "sakit", "buruk", "jelek", "parah", "mending ga usah",
    "ga suka", "gak suka", "ngga suka", "gapuas", "ga puas",
    "mengecewakan", "nyakitin", "sakit hati", "broken", "patah",
    "ngeselin", "nyusahin", "ribet", "susah", "susah parah",
    # Inggris negatif
    "hate", "worst", "terrible", "awful", "horrible", "disgusting",
    "boring", "stupid", "idiot", "fail", "failed", "bad", "ugly",
    "shame", "disappointed", "frustrated", "annoyed", "angry",
]

_NEUTRAL_SIGNALS = [
    # Kata-kata yang sering disalah-artikan sebagai negatif oleh DistilBERT
    "hidup", "mati", "lama", "cepat", "besar", "kecil", "tua", "muda",
    "panjang", "pendek", "tinggi", "rendah", "keras", "lembut",
    # Ekspresi netral TikTok
    "fyp", "foryou", "foryoupage", "viral", "trending", "explore",
    "ootd", "daily", "vlog", "challenge", "duet", "stitch",
]

# Emoji positif — dideteksi langsung dari teks asli (sebelum cleaning)
_POSITIVE_EMOJI_SIGNALS = [
    "😍", "❤️", "🔥", "✨", "🙌", "👏", "💪", "😊", "🥰", "💕",
    "🎉", "🥳", "😁", "🤩", "👍", "💯", "🌟", "⭐", "😄", "😃",
    "🙏", "💚", "💙", "💛", "🧡", "💜", "🤗", "😂", "🥹", "🫶",
]

_NEGATIVE_EMOJI_SIGNALS = [
    "😡", "🤬", "💔", "😢", "😭", "😤", "🤮", "🖕", "😒", "😞",
    "😔", "😟", "🥺", "😠", "👎", "💀", "😩", "😫", "🤦",
]


# ─────────────────────────────────────────────────────────────────────────────
# HELPER: analisis sentimen satu teks
# ─────────────────────────────────────────────────────────────────────────────
def _analyze_single_sentiment(text: str) -> Dict[str, Any]:
    """
    Analisis sentimen yang lebih akurat dan objektif.
    Pipeline yang diupgrade:
    1. Deteksi teks kosong/pure hashtag → NEUTRAL langsung
    2. Deteksi kata kasar Indonesia → NEGATIVE langsung (sangat akurat)
    3. Sinyal emoji kuat → pengaruh langsung
    4. Deteksi bahasa → pilih metode yang tepat
    5. Indonesia/pendek → rule-based yang diperkaya
    6. Inggris panjang → DistilBERT dengan threshold lebih tinggi (0.80)
    7. Fallback rule-based
    """
    if not text or not text.strip():
        return {"label": "NEUTRAL", "score": 0.5}

    lower = text.lower()

    # ── Step 0: Pure hashtag/emoji/mention tanpa konten bermakna ─────────
    clean_check = re.sub(r"[#@]\w+", "", text).strip()
    clean_check = re.sub(r"[^\w\s]", " ", clean_check).strip()
    meaningful = [w for w in clean_check.split() if len(w) > 2]
    if len(meaningful) == 0:
        return {"label": "NEUTRAL", "score": 0.50}

    # ── Step 1: Deteksi kata kasar Indonesia (high confidence negative) ──
    kasar_count = sum(1 for kw in ["anjing", "anjir", "babi", "bangsat",
                                    "bajingan", "keparat", "sialan", "goblok",
                                    "tolol", "tai", "taik", "kontol"] if kw in lower)
    if kasar_count >= 1:
        conf = min(0.75 + kasar_count * 0.08, 0.97)
        return {"label": "NEGATIVE", "score": round(conf, 4)}

    # ── Step 2: Sinyal emoji ──────────────────────────────────────────────
    pos_emoji = sum(1 for e in _POSITIVE_EMOJI_SIGNALS if e in text)
    neg_emoji = sum(1 for e in _NEGATIVE_EMOJI_SIGNALS if e in text)
    emoji_signal = pos_emoji - neg_emoji

    # Emoji sangat kuat → langsung tentukan jika tidak ada kata bermakna lain
    if pos_emoji >= 3 and len(meaningful) <= 3:
        return {"label": "POSITIVE", "score": 0.72}
    if neg_emoji >= 3 and len(meaningful) <= 3:
        return {"label": "NEGATIVE", "score": 0.72}

    # ── Step 3: Bersihkan untuk model ────────────────────────────────────
    clean_for_model = re.sub(r"http\S+", "", text)
    clean_latin = re.sub(r"[^\w\s.,!?']", " ", clean_for_model).strip()
    words = clean_latin.split()

    # ── Step 4: Deteksi bahasa Indonesia ─────────────────────────────────
    _ID_INDICATORS = [
        "yang", "dan", "di", "ini", "itu", "dengan", "untuk", "tidak",
        "ada", "ke", "dari", "nya", "aku", "gue", "gw", "kamu", "lo",
        "aja", "sih", "banget", "dong", "deh", "yuk", "udah",
        "sama", "kalau", "gimana", "makasih", "nggak", "ngga", "mah",
        "emang", "masa", "lagi", "udah", "belum", "baru", "juga",
    ]
    id_count = sum(1 for kw in _ID_INDICATORS if f" {kw} " in f" {lower} ")
    is_indonesian = id_count >= 1 or len(words) < 5

    # ── Step 5: Indonesia atau teks pendek → rule-based ──────────────────
    if is_indonesian or len(words) < 5:
        rb = _rule_based_sentiment(text)
        # Koreksi dengan emoji
        if emoji_signal >= 2 and rb["label"] == "NEUTRAL":
            return {"label": "POSITIVE", "score": min(0.65 + emoji_signal * 0.04, 0.90)}
        if emoji_signal <= -2 and rb["label"] == "NEUTRAL":
            return {"label": "NEGATIVE", "score": min(0.65 + abs(emoji_signal) * 0.04, 0.90)}
        if emoji_signal > 0 and rb["label"] == "POSITIVE":
            return {"label": "POSITIVE", "score": min(rb["score"] + 0.04, 0.95)}
        if emoji_signal < 0 and rb["label"] == "NEGATIVE":
            return {"label": "NEGATIVE", "score": min(rb["score"] + 0.04, 0.95)}
        # Jika emoji berlawanan dengan rule-based → NEUTRAL
        if emoji_signal > 1 and rb["label"] == "NEGATIVE" and rb["score"] < 0.80:
            return {"label": "NEUTRAL", "score": 0.52}
        if emoji_signal < -1 and rb["label"] == "POSITIVE" and rb["score"] < 0.80:
            return {"label": "NEUTRAL", "score": 0.52}
        return rb

    # ── Step 6: Bahasa Inggris → DistilBERT dengan threshold 0.80 ────────
    model = _load_model()
    if model:
        try:
            clean_for_distilbert = re.sub(r"[^\w\s.,!?']", " ", clean_for_model).strip()
            result = model(clean_for_distilbert[:512])[0]
            label = result["label"].upper()
            score = round(float(result["score"]), 4)

            # Threshold lebih tinggi (0.80) = lebih konservatif, lebih akurat
            if score < 0.80:
                # Score tidak cukup yakin → cek emoji dan rule-based
                if emoji_signal >= 2:
                    return {"label": "POSITIVE", "score": 0.63}
                if emoji_signal <= -2:
                    return {"label": "NEGATIVE", "score": 0.63}
                # Fallback ke rule-based
                rb = _rule_based_sentiment(text)
                if rb["label"] != "NEUTRAL":
                    return rb
                return {"label": "NEUTRAL", "score": round(score, 4)}

            # Score tinggi — pertimbangkan emoji juga
            if emoji_signal > 0 and label == "POSITIVE":
                score = min(score + 0.03, 0.99)
            elif emoji_signal < 0 and label == "NEGATIVE":
                score = min(score + 0.03, 0.99)
            elif emoji_signal >= 3 and label == "NEGATIVE" and score < 0.90:
                # Banyak emoji positif tapi model bilang negatif → NEUTRAL
                return {"label": "NEUTRAL", "score": 0.53}
            elif emoji_signal <= -3 and label == "POSITIVE" and score < 0.90:
                return {"label": "NEUTRAL", "score": 0.53}

            return {"label": label, "score": round(score, 4)}
        except Exception as e:
            print(f"   ⚠️ DistilBERT error: {e}")

    # ── Fallback ──────────────────────────────────────────────────────────
    rb = _rule_based_sentiment(text)
    if emoji_signal >= 2 and rb["label"] == "NEUTRAL":
        return {"label": "POSITIVE", "score": 0.63}
    if emoji_signal <= -2 and rb["label"] == "NEUTRAL":
        return {"label": "NEGATIVE", "score": 0.63}
    return rb


def _rule_based_sentiment(text: str) -> Dict[str, Any]:
    """
    Keyword-based sentiment yang lebih akurat untuk konten Indonesia + English.
    Menggunakan bobot berbeda dan konteks untuk menghindari false positive/negative.
    """
    lower = text.lower()
    original = text  # simpan asli untuk emoji check

    # ── Cek negasi — "tidak senang" ≠ POSITIVE ──────────────────────────
    negation_patterns = ["tidak ", "gak ", "ngga ", "nggak ", "ga ", "enggak ",
                         "bukan ", "jangan ", "belum ", "tak "]

    def _is_negated(keyword: str) -> bool:
        """Cek apakah keyword didahului kata negasi dalam 3 kata sebelumnya."""
        idx = lower.find(keyword)
        if idx == -1:
            return False
        before = lower[max(0, idx-30):idx]
        return any(neg in before for neg in negation_patterns)

    # ── Score positif (dari keyword positif yang tidak dinegasi) ──────────
    pos_score = 0
    for kw in _POSITIVE_KEYWORDS:
        if kw in lower and not _is_negated(kw):
            pos_score += 2 if len(kw) > 6 else 1  # keyword panjang lebih kuat

    # ── Score negatif ─────────────────────────────────────────────────────
    neg_score = 0
    # High risk keywords (kata kasar)
    for kw in _HIGH_RISK_KEYWORDS:
        if kw in lower:
            neg_score += 4  # kata kasar = negatif kuat

    # Keyword negatif Indonesia
    for kw in _NEGATIVE_KEYWORDS_ID:
        if kw in lower and not _is_negated(kw):
            neg_score += 2 if len(kw) > 5 else 1

    # Medium risk
    for kw in _MEDIUM_RISK_KEYWORDS:
        if kw in lower:
            neg_score += 1

    # ── Sinyal netral — kurangi confidence ───────────────────────────────
    neutral_count = sum(1 for kw in _NEUTRAL_SIGNALS if kw in lower)

    # ── Konteks khusus — pure hashtag/fyp tanpa kata bermakna ────────────
    # Kalau caption CUMA hashtag/mentions tanpa kata substantif → NEUTRAL
    words_only = re.sub(r"[#@]\w+", "", lower).strip()
    words_only = re.sub(r"\s+", " ", words_only).strip()
    meaningful_words = [w for w in words_only.split() if len(w) > 2]
    if len(meaningful_words) <= 2:
        # Terlalu sedikit kata bermakna → tidak bisa menilai sentimen
        return {"label": "NEUTRAL", "score": 0.50}

    # ── Tentukan label ────────────────────────────────────────────────────
    diff = pos_score - neg_score

    if diff > 0:
        conf = min(0.58 + (diff * 0.07), 0.95)
        return {"label": "POSITIVE", "score": round(conf, 4)}
    elif diff < 0:
        conf = min(0.58 + (abs(diff) * 0.07), 0.95)
        return {"label": "NEGATIVE", "score": round(conf, 4)}
    else:
        return {"label": "NEUTRAL", "score": 0.50}


# ─────────────────────────────────────────────────────────────────────────────
# HELPER: analisis isi konten satu post
# ─────────────────────────────────────────────────────────────────────────────
_TOPIC_KEYWORDS: Dict[str, List[str]] = {
    "olahraga":         ["football", "soccer", "sport", "goal", "match", "game", "win", "champion",
                         "bola", "sepak", "olahraga", "gol", "juara", "pertandingan"],
    "motivasi":         ["believe", "dream", "work hard", "never give up", "inspire", "legend",
                         "percaya", "mimpi", "semangat", "inspirasi", "berjuang"],
    "keluarga":         ["family", "son", "daughter", "wife", "mother", "father", "love",
                         "keluarga", "anak", "istri", "ibu", "ayah", "cinta"],
    "promosi":          ["check out", "link in bio", "buy", "discount", "offer", "sponsor",
                         "promo", "beli", "diskon", "penawaran"],
    "kesehatan":        ["workout", "training", "fitness", "gym", "health", "strong",
                         "latihan", "kebugaran", "sehat", "kuat"],
    "perjalanan":       ["travel", "trip", "city", "country", "visit", "tour",
                         "perjalanan", "kota", "negara", "wisata"],
    "hiburan":          ["funny", "fun", "comedy", "laugh", "entertainment",
                         "lucu", "komedi", "hiburan", "seru"],
    "nasionalisme":     ["portugal", "brazil", "indonesia", "country", "flag", "nation",
                         "bangsa", "negara", "bendera", "tanah air"],
    # LinkedIn-specific topics
    "karir_profesional":["career", "job", "hiring", "promotion", "promotion", "role", "position",
                         "karir", "pekerjaan", "jabatan", "promosi", "rekrutmen", "loker"],
    "kepemimpinan":     ["leadership", "leader", "ceo", "founder", "manager", "team",
                         "kepemimpinan", "pemimpin", "manajer", "tim"],
    "inovasi_bisnis":   ["innovation", "startup", "entrepreneur", "business", "product", "launch",
                         "inovasi", "bisnis", "wirausaha", "produk", "peluncuran"],
    "pendidikan":       ["learning", "education", "course", "certification", "degree", "university",
                         "belajar", "pendidikan", "kursus", "sertifikasi", "kampus"],
    "teknologi":        ["ai", "artificial intelligence", "machine learning", "software", "tech",
                         "cloud", "data", "digital", "coding", "programming", "algorithm"],
    "networking":       ["connect", "network", "collaboration", "partnership", "community",
                         "koneksi", "jaringan", "kolaborasi", "kemitraan", "komunitas"],
    "pencapaian":       ["achievement", "award", "milestone", "proud", "gratitude", "celebrate",
                         "pencapaian", "penghargaan", "bangga", "syukur", "perayaan"],
    "insight_industri": ["industry", "trend", "market", "analysis", "report", "insight",
                         "industri", "tren", "pasar", "analisis", "laporan"],
}


def _analyze_post_content(text: str, activity: Dict) -> Dict[str, Any]:
    """
    Analisis lengkap isi konten satu postingan.

    Untuk X/Twitter: ai_description sudah diisi di fetch_tweet.py dengan
    deskripsi sangat detail. Fungsi ini memakai prefilled_desc itu dan hanya
    menambahkan sentiment, topic, engagement_level via AI engine.

    Untuk platform lain (TikTok, IG, FB, LinkedIn): generate ai_description
    dari caption + hashtag + OCR + transcript seperti sebelumnya.
    """
    # Ambil data yang sudah diisi di fetch layer (X/Twitter path)
    existing_ca    = activity.get("content_analysis") or {}
    prefilled_desc = (existing_ca.get("ai_description") or
                      activity.get("ai_description") or      # Instagram/TikTok dari _gen_vd
                      activity.get("visual_description") or "")
    # Topic dari fetch layer (_gen_vd) — lebih akurat dari _TOPIC_KEYWORDS
    _fetch_topic = (existing_ca.get("topic") or
                    activity.get("topic") or "")  # Instagram/TikTok sudah punya ini
    if not text:
        text = activity.get("content_description") or ""

    # ── Input teks terbaik ────────────────────────────────────────────────
    combined   = activity.get("combined_text") or text
    caption    = activity.get("text") or activity.get("caption_text") or text
    ocr_text   = activity.get("ocr_text") or ""
    transcript = activity.get("audio_transcript") or ""
    hashtags   = activity.get("hashtags") or []
    mentions   = activity.get("mentions") or []
    media_type = activity.get("content_type") or activity.get("media_type") or "text"
    lower      = combined.lower()
    platform   = activity.get("platform") or ""

    # ── Sentimen ──────────────────────────────────────────────────────────
    # Prioritas: sentiment dari fetch layer (Instagram _sentiment_from_caption)
    _fetch_sent = activity.get("sentiment") or {}
    if _fetch_sent and _fetch_sent.get("label") in ("POSITIVE","NEGATIVE","NEUTRAL"):
        caption_sent = _fetch_sent
        ai_sent      = _fetch_sent
    else:
        caption_sent = (_analyze_single_sentiment(caption)
                        if caption.strip() else {"label": "NEUTRAL", "score": 0.5})
        ai_sent = (_analyze_single_sentiment(combined)
                   if combined.strip() else caption_sent)

    # ── Topik ─────────────────────────────────────────────────────────────
    topic_scores: Dict[str, int] = {}
    for topic, keywords in _TOPIC_KEYWORDS.items():
        hits = sum(1 for kw in keywords if kw in lower)
        if hits > 0:
            topic_scores[topic] = hits
    top_topics = sorted(topic_scores, key=lambda k: topic_scores[k], reverse=True)[:3]
    if not top_topics and hashtags:
        top_topics = hashtags[:3]
    main_topic = (
        _fetch_topic or                    # fetch layer (_gen_vd) — paling akurat
        existing_ca.get("topic") or        # X/Twitter content_analysis
        (top_topics[0] if top_topics else "umum")
    )

    # ── Engagement level ──────────────────────────────────────────────────
    metrics   = activity.get("metrics") or {}
    likes     = metrics.get("likes", 0)
    comments  = metrics.get("comments", 0)
    plays     = metrics.get("plays", 0)
    retweets  = metrics.get("retweets", 0) or metrics.get("shares", 0)
    views     = metrics.get("views", 0) or plays

    # X menggunakan views, platform lain plays
    total_eng = (likes + (comments * 5) + (retweets * 2) +
                 ((views // 100) if views else (plays // 100 if plays else 0)))

    if total_eng >= 5_000_000:
        eng_level = "VIRAL"
    elif total_eng >= 1_000_000:
        eng_level = "SANGAT TINGGI"
    elif total_eng >= 100_000:
        eng_level = "TINGGI"
    elif total_eng >= 10_000:
        eng_level = "SEDANG"
    else:
        eng_level = existing_ca.get("engagement_level") or "RENDAH"

    # ── AI Description ────────────────────────────────────────────────────
    # Prioritas: prefilled dari fetch layer (X sudah punya deskripsi sangat detail)
    # Fallback: generate dari caption + konteks untuk platform lain
    if prefilled_desc and len(prefilled_desc) > 80:
        ai_description = prefilled_desc
    else:
        # Generate untuk TikTok / Instagram / Facebook / LinkedIn
        clean_caption = re.sub(r"\s+", " ", re.sub(r"[#@]\w+", "", caption)).strip()
        all_text_lower = (caption + " " + " ".join(hashtags)).lower()

        _CONTEXT_MAP = [
            (["gunung","mountain","hiking","pendaki","summit","puncak",
              "ranukumbolo","rinjani","semeru","sumbing","merbabu","prau"],
             "menampilkan aktivitas di alam pegunungan"),
            (["pantai","beach","laut","ocean","sea","sunset","sunrise"],
             "menampilkan pemandangan pantai atau lautan"),
            (["alam","nature","hutan","forest","air terjun","waterfall"],
             "menampilkan keindahan alam terbuka"),
            (["food","makanan","kuliner","makan","masak","cooking","restaurant","cafe","kopi"],
             "berkaitan dengan kuliner atau makanan"),
            (["comedy","komedi","lucu","funny","humor","meme","viral","prank"],
             "berisi konten hiburan atau komedi"),
            (["gym","workout","fitness","sport","olahraga","football","soccer","basketball"],
             "berkaitan dengan olahraga atau kebugaran"),
            (["musik","music","dance","nyanyi","singing","lagu","song","cover"],
             "menampilkan musik atau tarian"),
            (["travel","wisata","liburan","vacation","trip","explore","vlog"],
             "berupa vlog perjalanan atau lifestyle"),
            (["motivasi","motivation","inspire","semangat","tips","tutorial","belajar","edukasi"],
             "bersifat edukatif atau motivasional"),
            (["keluarga","family","anak","baby","sahabat","teman","couple","selfie"],
             "menampilkan momen personal atau keluarga"),
            (["ai","artificial intelligence","machine learning","gpt","tech","software",
              "startup","coding","programming"],
             "membahas topik teknologi atau inovasi"),
            (["politics","government","election","economy","business","bitcoin","crypto"],
             "membahas topik politik, bisnis, atau isu sosial"),
            (["career","job","hiring","karir","rekrutmen","leadership","ceo","founder"],
             "berkaitan dengan karir atau profesionalisme"),
        ]

        ctx = "berisi informasi atau ekspresi"
        for tags, desc in _CONTEXT_MAP:
            if any(t in all_text_lower for t in tags):
                ctx = desc
                break

        _dur = activity.get("duration_sec") or 0
        if media_type == "video" and _dur > 0:
            opener = f"Video berdurasi {_dur} detik ini {ctx}"
        elif media_type == "video":
            opener = f"Video ini {ctx}"
        elif media_type in ("image", "photo"):
            opener = f"Konten foto ini {ctx}"
        elif media_type == "carousel":
            opener = f"Konten carousel ini {ctx}"
        else:
            opener = f"Konten ini {ctx}"

        parts = [opener]
        cap_no_url = re.sub(r"\s+", " ", re.sub(r"https?://\S+", "", clean_caption)).strip()
        if cap_no_url and len(cap_no_url) > 3:
            parts.append(f'mengekspresikan: "{cap_no_url[:300]}"')
        if mentions:
            parts.append(f"Menyebut: {', '.join('@'+m for m in mentions[:3])}")
        _music = activity.get("music") or {}
        if isinstance(_music, dict) and _music.get("title") and _music.get("author"):
            parts.append(f'Diiringi musik "{_music["title"]}" oleh {_music["author"]}')
        if ocr_text and len(ocr_text.strip()) > 5:
            parts.append(f'Teks visual: "{ocr_text.strip()[:150]}"')
        if transcript and len(transcript.strip()) > 10:
            parts.append(f'Narasi: "{transcript.strip()[:200]}"')
        if hashtags:
            parts.append(f"Hashtag: {' '.join('#'+h for h in hashtags[:8])}")
        if eng_level in ("VIRAL", "SANGAT TINGGI", "TINGGI"):
            parts.append(f"Konten ini mendapat engagement {eng_level.lower()}")
        sent_ctx = {
            "POSITIVE": "Konten bersentimen positif — mengekspresikan semangat, kebahagiaan, atau hal menyenangkan",
            "NEGATIVE": "Konten bersentimen negatif — mengandung kritik, keluhan, atau ekspresi kuat",
            "NEUTRAL":  "Konten bersentimen netral — bersifat informatif atau deskriptif",
        }
        parts.append(sent_ctx.get(ai_sent["label"], sent_ctx["NEUTRAL"]))
        ai_description = ". ".join(parts).rstrip(".") + "."

    # ── Sentiment comparison ──────────────────────────────────────────────
    def _norm(label: str, score: float) -> float:
        if label == "POSITIVE": return score
        if label == "NEGATIVE": return 1.0 - score
        return 0.5

    diff = round(abs(_norm(caption_sent["label"], caption_sent["score"]) -
                     _norm(ai_sent["label"],      ai_sent["score"])), 4)

    sentiment_comparison = {
        "caption":    caption_sent["label"],
        "ai":         ai_sent["label"],
        "match":      caption_sent["label"] == ai_sent["label"],
        "difference": diff,
        "note": (
            "Sentimen caption dan AI sama"
            if caption_sent["label"] == ai_sent["label"]
            else f"Caption {caption_sent['label'].lower()} tapi AI mendeteksi "
                 f"{ai_sent['label'].lower()} dari keseluruhan konten"
        ),
    }

    clean_caption_final = re.sub(r"\s+", " ",
                                  re.sub(r"[#@]\w+", "", caption)).strip()

    return {
        "caption_sentiment":    caption_sent,
        "ai_description":       ai_description,
        "ai_sentiment":         ai_sent,
        "sentiment_comparison": sentiment_comparison,
        "topics":               top_topics,
        "topic":                main_topic,
        "mood":                 (existing_ca.get("mood") or activity.get("mood") or ""),
        "objects":              (existing_ca.get("objects") or activity.get("objects") or ""),
        "activity":             (existing_ca.get("activity") or activity.get("activity") or ""),
        "content_type":         media_type,
        "engagement_level":     eng_level,
        "hashtags":             hashtags,
        "has_mentions":         len(mentions) > 0,
        "word_count":           len(caption.split()) if caption else 0,
        "content_summary":      (existing_ca.get("content_summary") or
                                 clean_caption_final[:200] or
                                 (hashtags[0] if hashtags else "")),
        "key_themes":           existing_ca.get("key_themes") or top_topics,
        "has_hashtags":         len(hashtags) > 0,
    }


# ─────────────────────────────────────────────────────────────────────────────
# HELPER: hitung risk score dari activities
# ─────────────────────────────────────────────────────────────────────────────
def _compute_risk_score(
    activities: List[Dict],
    sentiment_breakdown: Dict[str, float]
) -> int:
    """
    Risk score 0–100 berdasarkan:
    - Persentase sentimen NEGATIVE
    - Kehadiran high-risk keywords
    - Kehadiran medium-risk keywords
    """
    base_risk = 0

    # Komponen 1: dari sentimen negatif (max 50 poin)
    neg_pct = sentiment_breakdown.get("NEGATIVE", 0)
    base_risk += int(neg_pct * 0.5)   # 100% negatif → +50

    # Komponen 2: scan keywords di semua teks (max 50 poin)
    all_text = " ".join(
        (
            a.get("combined_text") or   # ← pakai combined_text jika ada
            a.get("text") or
            a.get("content_text") or
            ""
        ).lower()
        for a in activities
    )

    high_hits   = sum(1 for kw in _HIGH_RISK_KEYWORDS   if kw in all_text)
    medium_hits = sum(1 for kw in _MEDIUM_RISK_KEYWORDS if kw in all_text)

    keyword_risk = min((high_hits * 15) + (medium_hits * 5), 50)
    base_risk += keyword_risk

    return min(max(base_risk, 0), 100)


# ─────────────────────────────────────────────────────────────────────────────
# HELPER: hitung personality OCEAN dari konten
# ─────────────────────────────────────────────────────────────────────────────
def _compute_personality(
    activities: List[Dict],
    sentiment_breakdown: Dict[str, float],
    profile: Dict
) -> Dict[str, int]:
    """
    Estimasi OCEAN (Big Five) berdasarkan pola konten.
    Nilai 0–100.
    """
    all_text = " ".join(
        (a.get("text") or "").lower() for a in activities
    )
    total_posts = max(len(activities), 1)

    # Hitung engagement rate rata-rata
    avg_engagement = 0
    if activities:
        total_eng = sum(
            a.get("metrics", {}).get("likes", 0) +
            a.get("metrics", {}).get("comments", 0)
            for a in activities
        )
        avg_engagement = total_eng / total_posts

    followers = profile.get("followers", 0)

    # Openness: penggunaan hashtag beragam, topik variatif
    all_hashtags = []
    for a in activities:
        all_hashtags.extend(a.get("hashtags") or [])
    unique_hashtags = len(set(h.lower() for h in all_hashtags))
    openness = min(40 + (unique_hashtags * 3), 95)

    # Conscientiousness: konsistensi posting (proxy: jumlah postingan)
    conscientiousness = min(30 + (total_posts * 4), 90)

    # Extraversion: followers banyak + engagement tinggi
    if followers > 1_000_000:
        extraversion = min(70 + int(math.log10(followers) * 3), 95)
    elif followers > 10_000:
        extraversion = min(50 + int(math.log10(followers) * 5), 90)
    else:
        extraversion = 40

    # Agreeableness: sentimen positif tinggi
    pos_pct = sentiment_breakdown.get("POSITIVE", 50)
    agreeableness = min(30 + int(pos_pct * 0.6), 95)

    # Neuroticism: sentimen negatif tinggi → neuroticism tinggi
    neg_pct = sentiment_breakdown.get("NEGATIVE", 0)
    neuroticism = min(10 + int(neg_pct * 0.7), 80)

    return {
        "openness": int(openness),
        "conscientiousness": int(conscientiousness),
        "extraversion": int(extraversion),
        "agreeableness": int(agreeableness),
        "neuroticism": int(neuroticism)
    }


# ─────────────────────────────────────────────────────────────────────────────
# HELPER: buat flags dan rekomendasi
# ─────────────────────────────────────────────────────────────────────────────
def _compute_flags(
    activities: List[Dict],
    sentiment_breakdown: Dict[str, float],
    risk_score: int,
    profile: Dict
) -> Dict[str, Any]:
    red_flags: List[str] = []
    green_flags: List[str] = []

    pos_pct = sentiment_breakdown.get("POSITIVE", 0)
    neg_pct = sentiment_breakdown.get("NEGATIVE", 0)
    followers = profile.get("followers", 0)
    verified = profile.get("verified", False)

    all_text = " ".join(
        (a.get("text") or "").lower() for a in activities
    )

    # ── Green flags ───────────────────────────────────────────────────────
    if pos_pct >= 60:
        green_flags.append(f"✅ Sentimen positif dominan ({pos_pct:.0f}%)")
    if risk_score <= 20:
        green_flags.append("✅ Risk score rendah — konten aman")
    if followers >= 1_000_000:
        green_flags.append(f"✅ Pengaruh besar ({followers:,} followers)")
    if verified:
        green_flags.append("✅ Akun terverifikasi resmi")
    if neg_pct == 0 and activities:
        green_flags.append("✅ Tidak ada konten negatif terdeteksi")

    # ── Red flags ─────────────────────────────────────────────────────────
    if neg_pct >= 40:
        red_flags.append(f"🚨 Sentimen negatif tinggi ({neg_pct:.0f}%)")
    if risk_score >= 70:
        red_flags.append(f"🚨 Risk score tinggi ({risk_score}/100)")
    elif risk_score >= 40:
        red_flags.append(f"⚠️ Risk score sedang ({risk_score}/100)")

    high_hits = [kw for kw in _HIGH_RISK_KEYWORDS if kw in all_text]
    if high_hits:
        red_flags.append(f"🚨 Kata berisiko tinggi terdeteksi: {', '.join(set(high_hits[:3]))}")

    medium_hits = [kw for kw in _MEDIUM_RISK_KEYWORDS if kw in all_text]
    if medium_hits:
        red_flags.append(f"⚠️ Kata kontroversial terdeteksi: {', '.join(set(medium_hits[:3]))}")

    # ── Rekomendasi ───────────────────────────────────────────────────────
    if risk_score <= 25:
        recommendation = "SANGAT DIREKOMENDASIKAN"
    elif risk_score <= 45:
        recommendation = "DIREKOMENDASIKAN"
    elif risk_score <= 65:
        recommendation = "PERTIMBANGKAN DENGAN HATI-HATI"
    else:
        recommendation = "TIDAK DIREKOMENDASIKAN"

    # ── Suitable roles ────────────────────────────────────────────────────
    suitable_roles: List[str] = []
    pos_pct_val = sentiment_breakdown.get("POSITIVE", 0)

    if pos_pct_val >= 60 and risk_score <= 40:
        suitable_roles.extend(["BRAND AMBASSADOR", "MARKETING"])
    if followers >= 100_000 and risk_score <= 50:
        suitable_roles.extend(["CREATIVE", "CONTENT CREATOR"])
    if verified and risk_score <= 30:
        suitable_roles.append("PUBLIC RELATIONS")
    if risk_score <= 20:
        suitable_roles.append("CORPORATE SPOKESPERSON")
    if not suitable_roles:
        suitable_roles.append("INTERNAL ROLE ONLY")

    # Deduplicate
    suitable_roles = list(dict.fromkeys(suitable_roles))

    return {
        "red_flags": red_flags,
        "green_flags": green_flags,
        "recommendation": recommendation,
        "suitable_roles": suitable_roles
    }


# ─────────────────────────────────────────────────────────────────────────────
# HELPER: buat summary objektif
# ─────────────────────────────────────────────────────────────────────────────
def _build_summary(
    username: str,
    platform: str,
    profile: Dict,
    activities: List[Dict],
    sentiment_breakdown: Dict[str, float],
    risk_score: int,
    risk_level: str
) -> str:
    """
    Summary berdasarkan FAKTA:
    - Nama, followers, platform
    - Jumlah postingan dianalisis
    - Sentimen dominan & persentase
    - Risk score & level
    - Topik/hashtag dominan
    """
    full_name  = profile.get("full_name") or username
    followers  = profile.get("followers", 0)
    verified   = profile.get("verified", False)
    total_p    = len(activities)

    pos_pct  = sentiment_breakdown.get("POSITIVE", 0)
    neg_pct  = sentiment_breakdown.get("NEGATIVE", 0)
    neu_pct  = sentiment_breakdown.get("NEUTRAL",  0)

    # Sentimen dominan
    if pos_pct >= neg_pct and pos_pct >= neu_pct:
        dominant_sentiment = "positif"
        dom_pct = pos_pct
    elif neg_pct >= pos_pct and neg_pct >= neu_pct:
        dominant_sentiment = "negatif"
        dom_pct = neg_pct
    else:
        dominant_sentiment = "netral"
        dom_pct = neu_pct

    # Kumpulkan topik / hashtag dominan
    all_hashtags: List[str] = []
    for a in activities:
        all_hashtags.extend(a.get("hashtags") or [])
    top_tags = []
    if all_hashtags:
        from collections import Counter
        counted = Counter(h.lower() for h in all_hashtags)
        top_tags = [f"#{tag}" for tag, _ in counted.most_common(3)]

    # Kumpulkan topik konten dominan dari content_analysis
    all_topics: List[str] = []
    engagement_levels: Dict[str, int] = {}
    viral_count = 0
    for a in activities:
        ca = a.get("content_analysis") or {}
        topic = ca.get("topic")
        if topic and topic != "umum":
            all_topics.append(topic)
        eng = ca.get("engagement_level", "")
        if eng:
            engagement_levels[eng] = engagement_levels.get(eng, 0) + 1
        if eng in ("VIRAL", "SANGAT TINGGI"):
            viral_count += 1

    dominant_topic = ""
    if all_topics:
        from collections import Counter
        topic_count = Counter(all_topics)
        dominant_topic = topic_count.most_common(1)[0][0]

    # Total engagement
    total_likes_all = sum(
        (a.get("metrics") or {}).get("likes", 0) for a in activities
    )
    avg_likes = int(total_likes_all / max(len(activities), 1))

    # Followers formatting
    if followers >= 1_000_000:
        followers_str = f"{followers/1_000_000:.1f} juta"
    elif followers >= 1_000:
        followers_str = f"{followers/1_000:.1f} ribu"
    else:
        followers_str = str(followers)

    verified_str = " (akun terverifikasi)" if verified else ""

    tag_str = f" Topik dominan: {', '.join(top_tags)}." if top_tags else ""

    # Bangun insight tambahan
    extra_insights = []
    if dominant_topic:
        extra_insights.append(f"Konten didominasi topik {dominant_topic}")
    if viral_count > 0:
        extra_insights.append(f"{viral_count} postingan mencapai engagement viral/sangat tinggi")
    if avg_likes > 0:
        if avg_likes >= 1_000_000:
            extra_insights.append(f"rata-rata {avg_likes/1_000_000:.1f}M likes per postingan")
        elif avg_likes >= 1_000:
            extra_insights.append(f"rata-rata {avg_likes/1_000:.0f}K likes per postingan")
    if top_tags:
        extra_insights.append(f"hashtag paling sering: {', '.join(top_tags[:2])}")

    extra_str = ". ".join(extra_insights)
    if extra_str:
        extra_str = " " + extra_str + "."

    summary = (
        f"@{username} ({full_name}) adalah pengguna {platform.upper()}"
        f"{verified_str} dengan {followers_str} followers. "
        f"Dari {total_p} postingan terakhir yang dianalisis, "
        f"{dom_pct:.0f}% konten bersentimen {dominant_sentiment} "
        f"({pos_pct:.0f}% positif, {neg_pct:.0f}% negatif, {neu_pct:.0f}% netral)."
        f"{extra_str}"
        f" Risk score: {risk_score}/100 ({risk_level})."
    )

    return summary.strip()


# ─────────────────────────────────────────────────────────────────────────────
# HELPER: generate AI Narrative — narasi panjang dan detail tentang akun
# ─────────────────────────────────────────────────────────────────────────────
def _build_narrative(
    username: str,
    platform: str,
    profile: Dict,
    activities: List[Dict],
    sentiment_breakdown: Dict[str, float],
    risk_score: int,
    risk_level: str,
    personality: Dict,
    flags: Dict,
) -> str:
    """
    Generate narasi investigasi lengkap tentang profil digital target.
    Mencakup: identitas, pola konten, sentimen, risiko, kepribadian, rekomendasi.
    """
    from collections import Counter

    full_name = profile.get("full_name") or username
    followers = profile.get("followers", 0)
    following = profile.get("following", 0)
    verified  = profile.get("verified", False)
    bio       = profile.get("bio", "")
    total_p   = len(activities)

    pos_pct = sentiment_breakdown.get("POSITIVE", 0)
    neg_pct = sentiment_breakdown.get("NEGATIVE", 0)
    neu_pct = sentiment_breakdown.get("NEUTRAL",  0)

    # Format angka
    def _fmt(n):
        if n >= 1_000_000: return f"{n/1_000_000:.1f} juta"
        if n >= 1_000: return f"{n/1_000:.0f}K"
        return str(n)

    # Topik dominan
    all_topics = []
    all_hashtags = []
    all_moods = []
    total_likes = 0
    total_views = 0
    viral_count = 0
    neg_posts = 0
    pos_posts = 0

    for a in activities:
        ca = a.get("content_analysis") or {}
        t = ca.get("topic") or a.get("topic", "")
        if t: all_topics.append(t)
        all_hashtags.extend(a.get("hashtags") or [])
        m = ca.get("mood") or a.get("mood", "")
        if m: all_moods.append(m.split(",")[0].strip())
        met = a.get("metrics") or {}
        total_likes += met.get("likes", 0) or a.get("likes", 0)
        total_views += met.get("plays", 0) or a.get("views", 0) or a.get("plays", 0)
        eng = ca.get("engagement_level", "")
        if eng in ("VIRAL", "SANGAT TINGGI"): viral_count += 1
        sent = (a.get("sentiment") or {})
        sl = sent.get("label", "NEUTRAL") if isinstance(sent, dict) else str(sent)
        if sl == "NEGATIVE": neg_posts += 1
        if sl == "POSITIVE": pos_posts += 1

    top_topics = [t for t, _ in Counter(all_topics).most_common(3)]
    top_hashtags = [f"#{h}" for h, _ in Counter(h.lower() for h in all_hashtags if "fyp" not in h.lower()).most_common(5)]
    top_moods = [m for m, _ in Counter(all_moods).most_common(2)]
    avg_likes = int(total_likes / max(total_p, 1))
    avg_views = int(total_views / max(total_p, 1))
    eng_rate = round((avg_likes / max(avg_views, 1)) * 100, 2) if avg_views > 0 else 0

    # ── Paragraf 1: Identitas & Skala ─────────────────────────────────────
    verified_note = " dengan centang biru (akun terverifikasi resmi)" if verified else ""
    follow_ratio = round(followers / max(following, 1), 1)
    p1 = (
        f"**{full_name}** (@{username}) adalah kreator konten {platform.upper()}{verified_note}. "
        f"Akun ini memiliki **{_fmt(followers)} followers** dan {_fmt(following)} following, "
        f"dengan rasio followers/following sebesar {follow_ratio}x yang menunjukkan "
        f"{'pengaruh besar di platform ini' if follow_ratio >= 10 else 'basis audiens yang solid'}. "
    )
    if bio:
        p1 += f"Dalam bionya, target mendeskripsikan dirinya sebagai: \"{bio[:120]}\". "

    # ── Paragraf 2: Pola Konten ───────────────────────────────────────────
    topic_str = ", ".join(top_topics) if top_topics else "berbagai topik"
    hashtag_str = ", ".join(top_hashtags[:3]) if top_hashtags else "tidak ada hashtag dominan"
    mood_str = " dan ".join(top_moods) if top_moods else "bervariasi"
    p2 = (
        f"Dari {total_p} postingan terakhir yang dianalisis, konten {full_name} "
        f"didominasi oleh topik **{topic_str}** dengan mood konten yang cenderung **{mood_str}**. "
        f"Hashtag yang paling sering digunakan: {hashtag_str}. "
    )
    if viral_count > 0:
        p2 += f"Sebanyak **{viral_count} postingan** berhasil mencapai level engagement viral atau sangat tinggi. "
    if avg_views > 0:
        p2 += f"Rata-rata konten mendapat **{_fmt(avg_views)} penayangan** dengan engagement rate **{eng_rate}%**. "

    # ── Paragraf 3: Analisis Sentimen ─────────────────────────────────────
    if pos_pct >= neg_pct and pos_pct >= neu_pct:
        sent_tone = "positif dan menghibur"
        sent_impl = "Konten yang dibagikan cenderung membangun mood yang baik bagi audiensnya"
    elif neg_pct >= 40:
        sent_tone = "negatif atau kritis"
        sent_impl = "Perlu diwaspadai karena konten yang bersifat negatif dapat mempengaruhi citra"
    else:
        sent_tone = "netral dan informatif"
        sent_impl = "Konten yang dibagikan bersifat faktual dan tidak memihak"

    p3 = (
        f"Secara sentimen, profil ini menunjukkan tone yang **{sent_tone}** — "
        f"{pos_pct:.0f}% positif, {neg_pct:.0f}% negatif, {neu_pct:.0f}% netral. "
        f"{sent_impl}. "
        f"Dari {total_p} postingan, {pos_posts} bersentimen positif dan {neg_posts} bersentimen negatif. "
    )

    # ── Paragraf 4: Profil Risiko ─────────────────────────────────────────
    risk_desc = {
        "RENDAH":   "relatif aman dan tidak mengandung konten kontroversial yang signifikan",
        "SEDANG":   "perlu perhatian karena terdapat beberapa indikator yang perlu diverifikasi lebih lanjut",
        "TINGGI":   "mengkhawatirkan dan memerlukan investigasi mendalam sebelum mengambil keputusan",
        "KRITIS":   "sangat berisiko dan mengandung banyak sinyal bahaya yang perlu segera ditangani",
    }.get(risk_level, "dalam tahap penilaian")

    red_flags = flags.get("red_flags", [])
    green_flags = flags.get("green_flags", [])
    p4 = (
        f"**Risk score** profil ini adalah **{risk_score}/100 ({risk_level})**, yang berarti profil ini {risk_desc}. "
    )
    if red_flags:
        p4 += f"Indikator risiko yang terdeteksi: {'; '.join(str(f).replace('🚨','').replace('⚠️','').strip() for f in red_flags[:2])}. "
    if green_flags:
        p4 += f"Di sisi positif: {'; '.join(str(f).replace('✅','').strip() for f in green_flags[:2])}. "

    # ── Paragraf 5: Kepribadian Digital ──────────────────────────────────
    ocean_labels = {
        "openness": "Keterbukaan (Openness)",
        "conscientiousness": "Ketelitian (Conscientiousness)",
        "extraversion": "Ekstraversi",
        "agreeableness": "Keramahan (Agreeableness)",
        "neuroticism": "Neurotisisme",
    }
    top_traits = sorted(personality.items(), key=lambda x: x[1], reverse=True)[:2]
    trait_str = " dan ".join(f"{ocean_labels.get(k, k)} ({v}/100)" for k, v in top_traits)

    p5 = (
        f"Dari pola konten yang dianalisis, profil digital ini menunjukkan kepribadian yang dominan dalam **{trait_str}**. "
    )
    if personality.get("extraversion", 0) >= 70:
        p5 += "Sifat extrovert yang kuat tercermin dari tingginya interaksi dan engagement dengan audiens. "
    if personality.get("openness", 0) >= 70:
        p5 += "Kreativitas tinggi ditunjukkan dari keberagaman topik dan gaya konten yang dibagikan. "

    # ── Paragraf 6: Kesimpulan & Rekomendasi ─────────────────────────────
    rec = flags.get("recommendation", "PERTIMBANGKAN DENGAN HATI-HATI")
    suitable_roles = flags.get("suitable_roles", [])

    if rec in ("SANGAT DIREKOMENDASIKAN", "DIREKOMENDASIKAN"):
        conclusion = f"Secara keseluruhan, profil digital @{username} menunjukkan jejak yang **sehat dan positif**. "
    elif rec == "PERTIMBANGKAN DENGAN HATI-HATI":
        conclusion = f"Secara keseluruhan, profil digital @{username} memerlukan **review lebih lanjut** sebelum pengambilan keputusan. "
    else:
        conclusion = f"Secara keseluruhan, profil digital @{username} menunjukkan **beberapa red flags** yang perlu diperhatikan serius. "

    p6 = conclusion
    p6 += f"Rekomendasi: **{rec}**. "
    if suitable_roles:
        p6 += f"Posisi yang cocok berdasarkan profil digital: {', '.join(suitable_roles[:3])}. "
    p6 += (
        f"Analisis ini didasarkan pada {total_p} postingan terakhir dan data profil yang tersedia. "
        f"Untuk hasil yang lebih akurat, disarankan untuk melakukan verifikasi manual tambahan."
    )

    # ── Gabungkan semua paragraf ──────────────────────────────────────────
    narrative = "\n\n".join([p1.strip(), p2.strip(), p3.strip(), p4.strip(), p5.strip(), p6.strip()])
    return narrative


# ─────────────────────────────────────────────────────────────────────────────
# HELPER: generate AI Narrative Short — kesimpulan 2-3 kalimat
# ─────────────────────────────────────────────────────────────────────────────
def _build_narrative_short(
    username: str,
    platform: str,
    profile: Dict,
    activities: List[Dict],
    sentiment_breakdown: Dict[str, float],
    risk_score: int,
    risk_level: str,
    flags: Dict,
) -> str:
    """
    Kesimpulan singkat 2-3 kalimat yang langsung menggambarkan orang ini.
    Fokus: siapa dia, karakter kontennya, dan apakah layak dipercaya.
    """
    from collections import Counter

    full_name = profile.get("full_name") or username
    followers = profile.get("followers", 0)
    verified  = profile.get("verified", False)
    total_p   = len(activities)

    def _fmt(n):
        if n >= 1_000_000: return f"{n/1_000_000:.1f}jt"
        if n >= 1_000: return f"{n/1_000:.0f}K"
        return str(n)

    pos_pct = sentiment_breakdown.get("POSITIVE", 0)
    neg_pct = sentiment_breakdown.get("NEGATIVE", 0)
    rec     = flags.get("recommendation", "PERTIMBANGKAN DENGAN HATI-HATI")

    # Topik dominan
    all_topics = []
    total_likes = 0
    total_views = 0
    for a in activities:
        ca = a.get("content_analysis") or {}
        t  = ca.get("topic") or a.get("topic", "")
        if t: all_topics.append(t)
        met = a.get("metrics") or {}
        total_likes += met.get("likes", 0) or a.get("likes", 0)
        total_views += met.get("plays", 0) or a.get("views", 0) or a.get("plays", 0)

    top_topic = Counter(all_topics).most_common(1)[0][0] if all_topics else "berbagai topik"
    avg_views = int(total_views / max(total_p, 1))

    def _fmt_v(n):
        if n >= 1_000_000: return f"{n/1_000_000:.1f}M"
        if n >= 1_000: return f"{n/1_000:.0f}K"
        return str(n)

    # Kalimat 1: identitas + skala + karakter konten (satu kalimat padat)
    v_note = " terverifikasi" if verified else ""
    followers_str = _fmt(followers)
    avg_views_str = _fmt_v(avg_views) if avg_views > 0 else ""

    # Pilih kata sifat yang paling menggambarkan konten
    if pos_pct >= 65:
        content_char = "positif dan menghibur"
    elif neg_pct >= 50:
        content_char = "kritis dan ekspresif"
    elif neg_pct >= 30:
        content_char = "bervariasi dengan nada yang cukup kritis"
    else:
        content_char = "netral dan informatif"

    views_note = f", rata-rata {avg_views_str} penayangan per konten" if avg_views_str else ""
    s1 = (
        f"**{full_name}**{v_note} adalah pengguna {platform.upper()} dengan "
        f"**{followers_str} followers** yang aktif membuat konten bertema **{top_topic}**"
        f"{views_note}."
    )

    # Kalimat 2: sentimen + risk — langsung dan informatif
    red_flags = flags.get("red_flags", [])
    green_flags = flags.get("green_flags", [])
    rf_note = ""
    if red_flags:
        rf_note = f" Ditemukan {len(red_flags)} indikator yang perlu diperhatikan."
    elif green_flags:
        rf_note = f" Tidak ada red flags signifikan ditemukan."

    s2 = (
        f"Dari {total_p} postingan yang dianalisis, tone konten cenderung **{content_char}** "
        f"({pos_pct:.0f}% positif, {neg_pct:.0f}% negatif) "
        f"dengan skor risiko **{risk_score}/100**.{rf_note}"
    )

    # Kalimat 3: verdict — langsung ke poin
    verdict_map = {
        "SANGAT DIREKOMENDASIKAN":        "Secara keseluruhan, profil digital ini **aman dan layak** tanpa temuan serius.",
        "DIREKOMENDASIKAN":               "Secara keseluruhan, profil ini **dapat dipertimbangkan** dengan catatan minor.",
        "PERTIMBANGKAN DENGAN HATI-HATI": "Diperlukan **verifikasi lebih lanjut** sebelum mengambil keputusan penting.",
        "TIDAK DIREKOMENDASIKAN":         "Profil ini **tidak disarankan** — terdapat red flags yang perlu diselidiki.",
    }
    s3 = verdict_map.get(rec, "Verifikasi manual tetap disarankan untuk keputusan penting.")

    return f"{s1} {s2} {s3}"


# ─────────────────────────────────────────────────────────────────────────────
# FUNGSI ANALISIS REPOST — dipanggil dari main.py
# ─────────────────────────────────────────────────────────────────────────────
def analyze_reposts(
    username: str,
    reposts: List[Dict]
) -> List[Dict]:
    """
    Analisis sentimen + buat deskripsi mudah dipahami untuk setiap repost.
    """
    if not reposts:
        return []

    _load_model()
    enriched: List[Dict] = []

    for r in reposts:
        caption   = r.get("original_caption") or ""
        hashtags  = r.get("hashtags") or []
        author    = r.get("original_author") or "kreator"
        metrics   = r.get("metrics") or {}
        likes     = metrics.get("likes", 0)
        plays     = metrics.get("plays", 0)

        # ── Sentimen berdasarkan caption ─────────────────────────────────
        sent = _analyze_single_sentiment(caption) if caption else {"label": "NEUTRAL", "score": 0.5}

        # ── Deteksi topik ─────────────────────────────────────────────────
        lower = caption.lower()
        topic_scores: Dict[str, int] = {}
        for topic, keywords in _TOPIC_KEYWORDS.items():
            hits = sum(1 for kw in keywords if kw in lower)
            if hits > 0:
                topic_scores[topic] = hits
        main_topic = max(topic_scores, key=lambda k: topic_scores[k]) if topic_scores else "umum"

        # ── Buat deskripsi visual yang lebih natural ─────────────────────
        clean_caption = re.sub(r"[#@]\w+", "", caption).strip()
        clean_caption = re.sub(r"\s+", " ", clean_caption).strip()
        all_tags_lower = [h.lower() for h in hashtags]
        all_text_lower = (caption + " " + " ".join(hashtags)).lower()

        # Peta konteks → kalimat deskriptif (sama dengan _analyze_post_content)
        _REPOST_CONTEXT_MAP = [
            (["gunung", "mountain", "hiking", "pendaki", "summit", "puncak",
              "ranukumbolo", "rinjani", "semeru", "sumbing", "merbabu"],
             f"Video dari @{author} menampilkan aktivitas pendakian atau wisata pegunungan"),
            (["pantai", "beach", "laut", "ocean", "sunset", "sunrise"],
             f"Video dari @{author} menampilkan pemandangan pantai atau alam lautan"),
            (["alam", "nature", "hutan", "forest", "air terjun", "waterfall"],
             f"Video dari @{author} menampilkan keindahan alam terbuka"),
            (["food", "makanan", "kuliner", "makan", "masak", "cooking",
              "restaurant", "cafe", "kopi", "coffee"],
             f"Video dari @{author} berkaitan dengan kuliner atau makanan"),
            (["comedy", "komedi", "lucu", "funny", "humor", "meme", "viral", "prank"],
             f"Video dari @{author} berisi konten hiburan atau komedi"),
            (["gym", "workout", "fitness", "sport", "olahraga", "latihan",
              "football", "soccer", "basketball"],
             f"Video dari @{author} berkaitan dengan olahraga atau kebugaran"),
            (["musik", "music", "dance", "nyanyi", "singing", "lagu", "cover"],
             f"Video dari @{author} menampilkan musik atau tarian"),
            (["travel", "wisata", "liburan", "vacation", "trip", "explore", "vlog"],
             f"Video dari @{author} berupa vlog perjalanan atau eksplorasi"),
            (["motivasi", "motivation", "inspire", "tips", "tutorial", "belajar", "edukasi"],
             f"Video dari @{author} bersifat edukatif atau motivasional"),
            (["motor", "mobil", "otomotif", "racing", "drag", "modifikasi", "knalpot"],
             f"Video dari @{author} menampilkan konten otomotif atau kendaraan"),
            (["gaming", "game", "gamer", "esports", "main game", "gameplay"],
             f"Video dari @{author} berkaitan dengan gaming atau esports"),
        ]

        # Cari konteks yang cocok
        opening = None
        for context_tags, context_desc in _REPOST_CONTEXT_MAP:
            if any(tag in all_text_lower for tag in context_tags):
                opening = context_desc
                break

        if not opening:
            opening = f"Video dari @{author}"

        # Susun deskripsi repost yang kaya dan menjelaskan
        desc_parts: List[str] = []

        # 1. Siapa kreator aslinya dan apa konteksnya
        desc_parts.append(opening)

        # 2. Pesan/caption dari video asli
        if clean_caption and len(clean_caption) > 3:
            if len(clean_caption) > 50:
                desc_parts.append(f'Kreator asli mengungkapkan: "{clean_caption[:200]}"')
            else:
                desc_parts.append(f'dengan pesan: "{clean_caption}"')

        # 3. Topik konten
        if main_topic != "umum":
            desc_parts.append(f"Konten ini berfokus pada topik {main_topic}")

        # 4. Semua hashtag yang dipakai
        if hashtags:
            tag_str = " ".join(f"#{h}" for h in hashtags[:6])
            desc_parts.append(f"Hashtag yang digunakan: {tag_str}")

        # 5. Kenapa di-repost (inferensi dari sentimen dan topik)
        why_repost = {
            "hiburan":    f"Kemungkinan di-repost karena kontennya menghibur",
            "motivasi":   f"Kemungkinan di-repost karena kontennya inspiratif",
            "olahraga":   f"Kemungkinan di-repost karena relevan dengan minat olahraga",
            "perjalanan": f"Kemungkinan di-repost karena menampilkan destinasi atau pengalaman menarik",
            "kesehatan":  f"Kemungkinan di-repost karena berkaitan dengan gaya hidup sehat",
            "keluarga":   f"Kemungkinan di-repost karena kontennya personal dan relatable",
            "promosi":    f"Kemungkinan di-repost sebagai bagian dari promosi atau kolaborasi",
        }.get(main_topic, "")
        if why_repost:
            desc_parts.append(why_repost)

        # 6. Sentimen konten
        sent_phrases_repost = {
            "POSITIVE": "Konten ini bersentimen positif dan kemungkinan dianggap menginspirasi atau menghibur",
            "NEGATIVE": "Konten ini bersentimen negatif — mungkin berisi kritik, drama, atau konten kontroversial",
            "NEUTRAL":  "Konten ini bersentimen netral — bersifat informatif atau deskriptif",
        }
        desc_parts.append(sent_phrases_repost.get(sent["label"], sent_phrases_repost["NEUTRAL"]))

        content_description = ". ".join(desc_parts).rstrip(".") + "."

        enriched.append({
            **r,
            "sentiment":           sent,
            "topic":               main_topic,
            "content_description": content_description,
        })

    return enriched



def analyze_user_comments(
    username: str,
    user_comments: List[Dict]
) -> Dict[str, Any]:
    """
    Analisis 15 komentar terakhir yang ditulis si target.
    Mengembalikan sentimen, breakdown, topik, gaya bahasa, flags, summary.
    """
    if not user_comments:
        return {
            "comment_sentiment_overall":   "NEUTRAL",
            "comment_sentiment_score":     0.5,
            "comment_sentiment_breakdown": {"POSITIVE": 0, "NEGATIVE": 0, "NEUTRAL": 0},
            "comment_topics":              [],
            "comment_style":               "tidak ada data",
            "comment_red_flags":           [],
            "comment_green_flags":         [],
            "comment_summary":             f"Tidak ada komentar @{username} yang terdeteksi.",
        }

    _load_model()

    enriched: List[Dict] = []
    counts = {"POSITIVE": 0, "NEGATIVE": 0, "NEUTRAL": 0}
    scores: List[float] = []

    for c in user_comments:
        text = c.get("content") or ""
        sent = _analyze_single_sentiment(text)
        label = sent["label"]
        score = sent["score"]
        counts[label] += 1
        scores.append(score if label == "POSITIVE" else (1.0 - score if label == "NEGATIVE" else 0.5))
        enriched.append({**c, "sentiment": sent})

    total = max(len(enriched), 1)
    breakdown = {
        "POSITIVE": round(counts["POSITIVE"] / total * 100, 1),
        "NEGATIVE": round(counts["NEGATIVE"] / total * 100, 1),
        "NEUTRAL":  round(counts["NEUTRAL"]  / total * 100, 1),
    }

    # Overall
    if breakdown["POSITIVE"] >= breakdown["NEGATIVE"] and breakdown["POSITIVE"] >= breakdown["NEUTRAL"]:
        overall = "POSITIVE"
    elif breakdown["NEGATIVE"] >= breakdown["POSITIVE"] and breakdown["NEGATIVE"] >= breakdown["NEUTRAL"]:
        overall = "NEGATIVE"
    else:
        overall = "NEUTRAL"

    avg_score = round(sum(scores) / len(scores), 4) if scores else 0.5

    # ── Topik dari komentar ───────────────────────────────────────────────
    all_comment_text = " ".join(c.get("content") or "" for c in user_comments).lower()
    topic_hits: Dict[str, int] = {}
    for topic, keywords in _TOPIC_KEYWORDS.items():
        hits = sum(1 for kw in keywords if kw in all_comment_text)
        if hits > 0:
            topic_hits[topic] = hits
    comment_topics = sorted(topic_hits, key=lambda k: topic_hits[k], reverse=True)[:3]

    # ── Gaya bahasa ───────────────────────────────────────────────────────
    avg_len = sum(len((c.get("content") or "").split()) for c in user_comments) / total
    has_emoji = any(re.search(r"[^\w\s,.'!?-]", c.get("content") or "") for c in user_comments)
    if avg_len <= 3:
        style = "singkat/ekspresif"
    elif avg_len <= 8:
        style = "kasual"
    else:
        style = "deskriptif"
    if has_emoji:
        style += " dengan emoji"

    # ── Flags dari komentar ───────────────────────────────────────────────
    comment_red_flags: List[str] = []
    comment_green_flags: List[str] = []

    high_hits_list = [kw for kw in _HIGH_RISK_KEYWORDS if kw in all_comment_text]
    if high_hits_list:
        comment_red_flags.append(f"🚨 Kata berisiko dalam komentar: {', '.join(set(high_hits_list[:3]))}")
    if breakdown["NEGATIVE"] >= 40:
        comment_red_flags.append(f"🚨 {breakdown['NEGATIVE']}% komentar bersentimen negatif")
    if breakdown["POSITIVE"] >= 60:
        comment_green_flags.append(f"✅ {breakdown['POSITIVE']}% komentar bersentimen positif")
    if not high_hits_list:
        comment_green_flags.append("✅ Tidak ada kata berisiko dalam komentar")

    # ── Summary ───────────────────────────────────────────────────────────
    topic_str  = f", topik: {', '.join(comment_topics)}" if comment_topics else ""
    summary = (
        f"Dari {len(user_comments)} komentar terakhir @{username}: "
        f"{breakdown['POSITIVE']:.0f}% positif, "
        f"{breakdown['NEGATIVE']:.0f}% negatif, "
        f"{breakdown['NEUTRAL']:.0f}% netral. "
        f"Gaya bahasa: {style}{topic_str}."
    )

    print(f"   ↳ Comment analysis: {overall} | {breakdown}")

    return {
        "comment_sentiment_overall":   overall,
        "comment_sentiment_score":     avg_score,
        "comment_sentiment_breakdown": breakdown,
        "comment_topics":              comment_topics,
        "comment_style":               style,
        "comment_red_flags":           comment_red_flags,
        "comment_green_flags":         comment_green_flags,
        "comment_summary":             summary,
        # Kembalikan juga komentar yang sudah di-enrich dengan sentiment
        "enriched_user_comments":      enriched,
    }


# ─────────────────────────────────────────────────────────────────────────────
# FUNGSI UTAMA — dipanggil dari main.py
# ─────────────────────────────────────────────────────────────────────────────
def analyze_user_behavior(
    username: str,
    platform: str,
    tweets_text: str = "",           # kept for backward compatibility
    activities: Optional[List[Dict]] = None,
    profile: Optional[Dict] = None
) -> Dict[str, Any]:
    """
    Analisis lengkap perilaku user berdasarkan activities list.

    Parameters
    ----------
    username    : nama pengguna
    platform    : tiktok / instagram / x / facebook
    tweets_text : teks gabungan (legacy, masih diterima)
    activities  : list aktivitas dari scraper_engine (format baru)
    profile     : dict profil dari scraper_engine

    Returns
    -------
    Dict analytics_insight dengan semua field lengkap
    """
    if activities is None:
        activities = []
    if profile is None:
        profile = {}

    print(f"🧠 [AI] Mulai analisis @{username} | {len(activities)} postingan")

    # ── Pre-load model ────────────────────────────────────────────────────
    _load_model()

    # ── Sentimen PER POSTINGAN ────────────────────────────────────────────
    sentiment_counts = {"POSITIVE": 0, "NEGATIVE": 0, "NEUTRAL": 0}
    sentiment_scores: List[float] = []
    enriched_activities: List[Dict] = []

    for activity in activities:
        # ── Pilih input teks terbaik yang tersedia ────────────────────────
        # Prioritas: combined_text (caption+OCR+transcript) → caption → description
        # combined_text diisi oleh main.py setelah media extraction.
        # Jika extraction belum jalan / gagal, fallback ke caption (behavior lama).
        text = (
            activity.get("combined_text") or   # ← hasil gabungan OCR + transcript + caption
            activity.get("text") or            # ← caption mentah (fallback)
            activity.get("content_text") or
            activity.get("content_description") or
            ""
        )

        sent = _analyze_single_sentiment(text)
        label = sent["label"]
        score = sent["score"]

        sentiment_counts[label] += 1
        # normalise score ke arah 0–1 (POSITIVE mendekat 1, NEGATIVE mendekat 0)
        if label == "POSITIVE":
            sentiment_scores.append(score)
        elif label == "NEGATIVE":
            sentiment_scores.append(1.0 - score)
        else:
            sentiment_scores.append(0.5)

        # Update sentiment di activity dict (in-place)
        updated = dict(activity)
        updated["sentiment"] = {"label": label, "score": score}

        # ── Analisis isi konten per post ──────────────────────────────────
        content_analysis = _analyze_post_content(text, activity)
        updated["content_analysis"] = content_analysis

        # ── Sentimen per KOMENTAR ─────────────────────────────────────────
        enriched_comments = []
        for c in (activity.get("comments_data") or []):
            c_text = c.get("content") or c.get("text") or ""
            c_sent = _analyze_single_sentiment(c_text)
            enriched_c = dict(c)
            enriched_c["sentiment"] = c_sent
            enriched_comments.append(enriched_c)
        updated["comments_data"] = enriched_comments

        enriched_activities.append(updated)

    total = max(len(activities), 1)

    # ── Sentiment breakdown (persentase) ──────────────────────────────────
    sentiment_breakdown = {
        "POSITIVE": round(sentiment_counts["POSITIVE"] / total * 100, 1),
        "NEGATIVE": round(sentiment_counts["NEGATIVE"] / total * 100, 1),
        "NEUTRAL":  round(sentiment_counts["NEUTRAL"]  / total * 100, 1),
    }

    # ── Overall sentiment ─────────────────────────────────────────────────
    avg_score = round(sum(sentiment_scores) / len(sentiment_scores), 4) if sentiment_scores else 0.5

    if sentiment_breakdown["POSITIVE"] >= sentiment_breakdown["NEGATIVE"] and \
       sentiment_breakdown["POSITIVE"] >= sentiment_breakdown["NEUTRAL"]:
        sentiment_overall = "POSITIVE"
    elif sentiment_breakdown["NEGATIVE"] >= sentiment_breakdown["POSITIVE"] and \
         sentiment_breakdown["NEGATIVE"] >= sentiment_breakdown["NEUTRAL"]:
        sentiment_overall = "NEGATIVE"
    else:
        sentiment_overall = "NEUTRAL"

    print(
        f"   ↳ Sentimen: {sentiment_overall} | "
        f"POSITIVE={sentiment_breakdown['POSITIVE']}% "
        f"NEGATIVE={sentiment_breakdown['NEGATIVE']}% "
        f"NEUTRAL={sentiment_breakdown['NEUTRAL']}%"
    )

    # ── Risk score ────────────────────────────────────────────────────────
    risk_score = _compute_risk_score(enriched_activities, sentiment_breakdown)

    if risk_score <= 25:
        risk_level = "SANGAT RENDAH"
    elif risk_score <= 45:
        risk_level = "RENDAH"
    elif risk_score <= 65:
        risk_level = "SEDANG"
    elif risk_score <= 80:
        risk_level = "TINGGI"
    else:
        risk_level = "SANGAT TINGGI"

    print(f"   ↳ Risk: {risk_score}/100 ({risk_level})")

    # ── Personality ───────────────────────────────────────────────────────
    personality = _compute_personality(enriched_activities, sentiment_breakdown, profile)

    # ── Flags & rekomendasi ───────────────────────────────────────────────
    flags = _compute_flags(enriched_activities, sentiment_breakdown, risk_score, profile)

    # ── Summary objektif ──────────────────────────────────────────────────
    summary_text = _build_summary(
        username, platform, profile,
        enriched_activities, sentiment_breakdown,
        risk_score, risk_level
    )

    # ── AI Narrative — narasi investigasi panjang dan detail ─────────────
    ai_narrative = _build_narrative(
        username, platform, profile,
        enriched_activities, sentiment_breakdown,
        risk_score, risk_level,
        personality, flags
    )

    # ── AI Narrative Short — kesimpulan 2-3 kalimat ───────────────────────
    ai_narrative_short = _build_narrative_short(
        username, platform, profile,
        enriched_activities, sentiment_breakdown,
        risk_score, risk_level, flags
    )

    print(f"   ↳ Summary: {summary_text[:80]}...")

    return {
        # Aktivitas dengan sentimen sudah diisi
        "enriched_activities": enriched_activities,

        # Analytics
        "sentiment_overall": sentiment_overall,
        "sentiment_score": avg_score,
        "sentiment_breakdown": sentiment_breakdown,
        "risk_score": risk_score,
        "risk_level": risk_level,
        "personality": personality,
        "summary_text": summary_text,
        "ai_narrative": ai_narrative,
        "ai_narrative_short": ai_narrative_short,
        "red_flags": flags["red_flags"],
        "green_flags": flags["green_flags"],
        "recommendation": flags["recommendation"],
        "suitable_roles": flags["suitable_roles"],
    }
