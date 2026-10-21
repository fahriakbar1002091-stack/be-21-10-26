"""
fetch_linkedin.py - LinkedIn Scraper via Apify v2.0
Run 1: linkedintel-core/linkedin-profile-scraper-no-cookies
  -> followers, connections, about, experience, education,
     skills, certifications, languages, interests, dll
Run 2: harvestapi/linkedin-profile-posts
  -> posts, reactions, comments lengkap
"""

import re
import asyncio
from typing import Dict, List, Any
from functools import partial


# ── Helpers ──────────────────────────────────────────────────────────────────

def _safe_int(v: Any, d: int = 0) -> int:
    try:
        return int(v) if v is not None else d
    except (ValueError, TypeError):
        return d


def _safe_str(v: Any, d: str = "") -> str:
    return d if v is None else str(v).strip()


def _parse_li_date(raw: Any) -> str:
    if not raw:
        return ""
    if isinstance(raw, dict):
        s = raw.get("date") or ""
        if s and len(s) >= 10:
            return s[:10]
        ts = raw.get("timestamp")
        if ts:
            try:
                import time as _t
                return _t.strftime("%Y-%m-%d", _t.localtime(int(ts) / 1000))
            except Exception:
                pass
        return ""
    s = str(raw).strip()
    return s[:10] if len(s) >= 10 else s


def _clean_id(username: str) -> str:
    raw = username.strip()
    for p in ("https://", "http://", "www.linkedin.com", "linkedin.com"):
        raw = raw.replace(p, "")
    raw = raw.strip("/")
    if raw.startswith("in/"):
        raw = raw[3:]
    return raw.split("/")[0].replace("@", "").strip()


def _empty(username: str, error: str) -> Dict:
    return {
        "status": "error", "platform": "linkedin", "username": username,
        "full_name": "", "headline": "", "bio": "", "about": "",
        "profile_pic": "", "background_image": "", "linkedin_url": "",
        "website": "", "website_label": "", "location": "", "industry": "",
        "followers": 0, "connections_count": 0, "connections": "",
        "verified": False, "is_creator": False, "is_premium": False,
        "is_influencer": False, "is_open_to_work": False, "is_hiring": False,
        "join_date": "", "current_company": "", "current_title": "",
        "experience": [], "education": [], "skills": [],
        "certifications": [], "languages": [], "interests": [],
        "volunteering": [], "projects": [], "publications": [],
        "honors": [], "courses": [], "organizations": [],
        "contact_email": "", "contact_phone": "",
        "total_posts": 0, "total_likes": 0, "total_comments": 0,
        "total_shares": 0, "has_text": False,
        "posts": [], "photos": [], "user_comments": [], "reposts": [],
        "scrape_errors": [error], "data_limitations": [],
    }


# ── Profile parser (linkedintel-core multi-record output) ─────────────────────

def _parse_profile_records(records: List[Dict], username: str) -> Dict:
    pm: Dict = {}
    experience: List[Dict] = []
    education: List[Dict] = []
    skills: List[str] = []
    certifications: List[Dict] = []
    languages: List[str] = []
    interests: List[Dict] = []
    volunteering: List[Dict] = []
    projects: List[Dict] = []
    publications: List[Dict] = []
    honors: List[Dict] = []
    courses: List[str] = []
    organizations: List[Dict] = []

    for rec in records:
        rt = _safe_str(rec.get("type")).lower()

        if rt == "profile":
            pm = rec

        elif rt == "profileexperience":
            s = rec.get("startedOn") or rec.get("start") or {}
            e = rec.get("finishedOn") or rec.get("end") or {}
            # Format: YYYY/MM
            def _fmt_date(d: Any) -> str:
                if not d or not isinstance(d, dict):
                    return _safe_str(d)
                y = _safe_str(d.get("year", ""))
                m = _safe_str(d.get("month", ""))
                return f"{y}/{m.zfill(2)}" if m else y
            experience.append({
                "title":           _safe_str(rec.get("title")),
                "company":         _safe_str(rec.get("companyName") or rec.get("company")),
                "company_url":     _safe_str(rec.get("companyUrl")),
                "location":        _safe_str(rec.get("location")),
                "description":     _safe_str(rec.get("description"))[:500],
                "start":           _fmt_date(s),
                "end":             _fmt_date(e) if e else "Sekarang",
                "is_current":      bool(rec.get("isCurrent") or not e),
                "employment_type": _safe_str(
                    rec.get("employmentType") or rec.get("employment_type") or ""
                ),
            })

        elif rt == "profileeducation":
            s = rec.get("startedOn") or rec.get("start") or {}
            e = rec.get("finishedOn") or rec.get("end") or {}
            def _fmt_edu_date(d: Any) -> str:
                if not d or not isinstance(d, dict):
                    return _safe_str(d)
                y = _safe_str(d.get("year", ""))
                m = _safe_str(d.get("month", ""))
                return f"{y}/{m.zfill(2)}" if m else y
            education.append({
                "school":         _safe_str(rec.get("schoolName") or rec.get("school")),
                "school_url":     _safe_str(rec.get("schoolUrl")),
                "degree":         _safe_str(rec.get("degreeName") or rec.get("degree")),
                "field_of_study": _safe_str(rec.get("fieldOfStudy")),
                "grade":          _safe_str(rec.get("grade")),
                "description":    _safe_str(rec.get("description"))[:300],
                "start":          _fmt_edu_date(s),
                "end":            _fmt_edu_date(e) if e else "",
                "activities":     _safe_str(rec.get("activities") or rec.get("activitiesAndSocieties") or ""),
            })

        elif rt == "profileskill":
            n = _safe_str(rec.get("name") or rec.get("skillName"))
            if n:
                skills.append(n)

        elif rt == "profilecertification":
            # issuedOn / expiresOn bisa dict {year, month} atau string
            def _fmt_cert_date(raw: Any) -> str:
                if not raw:
                    return ""
                if isinstance(raw, dict):
                    y = _safe_str(raw.get("year", ""))
                    m = _safe_str(raw.get("month", ""))
                    return f"{y}/{m.zfill(2)}" if (y and m) else y
                return _safe_str(raw)[:10]
            certifications.append({
                "name":           _safe_str(rec.get("name")),
                "authority":      _safe_str(rec.get("authority") or rec.get("organization")),
                "license_no":     _safe_str(rec.get("licenseNumber") or rec.get("licenseNo")),
                "credential_url": _safe_str(rec.get("credentialUrl") or rec.get("url")),
                "issued":         _fmt_cert_date(rec.get("issuedOn") or rec.get("issued")),
                "expires":        _fmt_cert_date(rec.get("expiresOn") or rec.get("expires")),
            })

        elif rt == "profilelanguage":
            lang = _safe_str(rec.get("name") or rec.get("language"))
            if lang:
                level = _safe_str(rec.get("proficiency") or "")
                languages.append(f"{lang} ({level})" if level else lang)

        elif rt == "profileinterest":
            interests.append({
                "name":   _safe_str(rec.get("name")),
                "bucket": _safe_str(rec.get("bucket")),
                "url":    _safe_str(rec.get("url") or rec.get("entityUrl")),
            })

        elif rt == "profilevolunteering":
            volunteering.append({
                "role":         _safe_str(rec.get("role")),
                "organization": _safe_str(rec.get("companyName") or rec.get("organization")),
                "cause":        _safe_str(rec.get("cause")),
                "description":  _safe_str(rec.get("description"))[:300],
            })

        elif rt == "profileproject":
            projects.append({
                "title":       _safe_str(rec.get("title")),
                "description": _safe_str(rec.get("description"))[:400],
                "url":         _safe_str(rec.get("url")),
            })

        elif rt in ("profilepublication",):
            publications.append({
                "title":       _safe_str(rec.get("name") or rec.get("title")),
                "publisher":   _safe_str(rec.get("publisher")),
                "url":         _safe_str(rec.get("url")),
                "date":        _safe_str(rec.get("publishedOn") or ""),
                "description": _safe_str(rec.get("description"))[:300],
            })

        elif rt in ("profilehonor", "profilehonorsandaward"):
            honors.append({
                "title":       _safe_str(rec.get("title")),
                "issuer":      _safe_str(rec.get("issuer")),
                "date":        _safe_str(rec.get("issuedOn") or ""),
                "description": _safe_str(rec.get("description"))[:300],
            })

        elif rt == "profilecourse":
            n = _safe_str(rec.get("name"))
            if n:
                courses.append(n)

        elif rt == "profileorganization":
            organizations.append({
                "name":     _safe_str(rec.get("name")),
                "position": _safe_str(rec.get("position")),
            })

    return {
        "full_name":       _safe_str(pm.get("fullName") or pm.get("name") or username),
        "headline":        _safe_str(pm.get("headline")),
        "about":           _safe_str(pm.get("summary") or pm.get("about")),
        "profile_pic":     _safe_str(pm.get("profilePictureUrl") or pm.get("profilePicture")),
        "background_image":_safe_str(pm.get("backgroundImageUrl") or pm.get("backgroundImage")),
        "linkedin_url":    _safe_str(pm.get("profileUrl") or f"https://www.linkedin.com/in/{username}"),
        "location":        _safe_str(pm.get("locationFull") or pm.get("location") or pm.get("city")),
        "industry":        _safe_str(pm.get("industryName") or pm.get("industry")),
        "followers":       _safe_int(pm.get("followerCount") or pm.get("followers")),
        "connections_count":_safe_int(pm.get("connectionsCount") or pm.get("connections")),
        "connections":     _safe_str(pm.get("connectionsCount") or ""),
        "verified":        bool(pm.get("isVerified")),
        "is_creator":      bool(pm.get("isCreator")),
        "is_premium":      bool(pm.get("isPremium")),
        "is_influencer":   bool(pm.get("isInfluencer")),
        "is_open_to_work": bool(pm.get("isOpenToWork")),
        "is_hiring":       bool(pm.get("isHiring")),
        "current_company": _safe_str(pm.get("currentCompanyName")),
        "current_title":   _safe_str(pm.get("currentTitle")),
        "experience":      experience,
        "education":       education,
        "skills":          skills,
        "certifications":  certifications,
        "languages":       languages,
        "interests":       interests,
        "volunteering":    volunteering,
        "projects":        projects,
        "publications":    publications,
        "honors":          honors,
        "courses":         courses,
        "organizations":   organizations,
    }


# ── Post helpers ──────────────────────────────────────────────────────────────

def _parse_post_images(raw: Any) -> List[Dict]:
    result = []
    if not isinstance(raw, list):
        return result
    for img in raw:
        if not isinstance(img, dict):
            continue
        url = _safe_str(img.get("url"))
        if url:
            result.append({"url": url, "width": _safe_int(img.get("width")), "height": _safe_int(img.get("height"))})
    return result


def _parse_document(raw: Any) -> Dict:
    if not isinstance(raw, dict) or not raw:
        return {}
    covers = []
    for cp in (raw.get("coverPages") or []):
        if isinstance(cp, dict):
            for u in (cp.get("imageUrls") or []):
                if u:
                    covers.append(_safe_str(u))
    return {
        "title":        _safe_str(raw.get("title")),
        "document_url": _safe_str(raw.get("transcribedDocumentUrl")),
        "cover_images": covers,
        "total_pages":  _safe_int(raw.get("totalPageCount")),
    }


def _parse_reactions_breakdown(raw: Any) -> Dict[str, int]:
    result: Dict[str, int] = {}
    if not isinstance(raw, list):
        return result
    for r in raw:
        if isinstance(r, dict):
            t = _safe_str(r.get("type")).upper()
            if t:
                result[t] = _safe_int(r.get("count"))
    return result


def _parse_reactions_actors(raw: Any) -> List[Dict]:
    result = []
    if not isinstance(raw, list):
        return result
    for r in raw:
        if not isinstance(r, dict):
            continue
        a = r.get("actor") or {}
        result.append({
            "reaction_type":    _safe_str(r.get("reactionType")),
            "reactor_name":     _safe_str(a.get("name")),
            "reactor_url":      _safe_str(a.get("linkedinUrl")),
            "reactor_position": _safe_str(a.get("position")),
            "reactor_pic":      _safe_str(a.get("pictureUrl") or (a.get("picture") or {}).get("url")),
        })
    return result


def _is_target_comment(
    actor_name: str,
    actor_url: str,
    is_author: bool,
    target_username: str,
    target_full_name: str,
    name_tokens: set,
) -> tuple:
    """
    Multi-signal detection: apakah komentar ini dari target user?
    Return (is_target: bool, matched_signal: str)

    Signal 1: is_author flag dari LinkedIn/harvestapi (paling akurat)
    Signal 2: actor URL mengandung username target (clean)
    Signal 3: actor name == full_name (exact, case-insensitive)
    Signal 4: actor name == username (misal "satyanadella")
    Signal 5: partial name match — minimal 2 token cocok
    Signal 6: actor URL mengandung bagian dari URL profil target
    """
    aname = actor_name.lower().strip()
    aurl  = actor_url.lower().strip()
    tid   = target_username.lower().strip()
    fname = target_full_name.lower().strip()

    # Signal 1
    if is_author:
        return True, "S1:is_author"
    # Signal 2: URL mengandung username (bukan hash ACoAAA...)
    if tid and len(tid) > 3 and f"/in/{tid}" in aurl:
        return True, f"S2:url_contains_{tid}"
    # Signal 3: nama persis sama dengan full_name
    if fname and aname == fname:
        return True, "S3:exact_fullname"
    # Signal 4: nama == username
    if tid and aname == tid:
        return True, "S4:exact_username"
    # Signal 5: partial name — minimal 2 token (abaikan token < 3 char)
    if name_tokens:
        a_tokens = {t for t in aname.split() if len(t) > 2}
        overlap  = name_tokens & a_tokens
        if len(overlap) >= min(2, len(name_tokens)):
            return True, f"S5:partial_{overlap}"
    # Signal 6: URL mengandung salah satu token nama (jika nama unik)
    if name_tokens and len(name_tokens) == 1:
        lone = next(iter(name_tokens))
        if len(lone) > 4 and lone in aurl:
            return True, f"S6:url_token_{lone}"
    return False, ""


def _parse_comments(raw: Any, target_id: str, target_name: str = ""):
    """
    Parse comments dari harvestapi/datadoping output.
    Return (all_comments[:20], owner_comments).
    """
    all_c:   List[Dict] = []
    owner_c: List[Dict] = []

    if not isinstance(raw, list):
        return all_c, owner_c

    tid_lower  = target_id.lower().strip()
    name_lower = target_name.lower().strip()
    name_tokens = {t for t in name_lower.split() if len(t) > 2} if name_lower else set()

    for c in raw:
        if not isinstance(c, dict):
            continue
        a         = c.get("actor") or {}
        aurl      = _safe_str(a.get("linkedinUrl") or a.get("url") or "").lower()
        aname_raw = _safe_str(a.get("name") or c.get("actor_name") or "")
        is_author = bool(a.get("author") or c.get("is_author") or False)

        entry = {
            "comment_id":     _safe_str(c.get("id") or c.get("comment_id") or ""),
            "comment_url":    _safe_str(c.get("linkedinUrl") or c.get("comment_url") or ""),
            "content":        _safe_str(
                c.get("commentary") or c.get("text") or
                c.get("commentText") or c.get("content") or ""
            ),
            "created_at":     _safe_str(c.get("createdAt") or c.get("date") or "")[:10],
            "num_replies":    _safe_int(c.get("numComments") or c.get("replyCount") or 0),
            "likes":          _safe_int(c.get("likesCount") or c.get("likes") or 0),
            "pinned":         bool(c.get("pinned")),
            "edited":         bool(c.get("edited")),
            "actor_name":     aname_raw,
            "actor_url":      _safe_str(a.get("linkedinUrl") or a.get("url") or
                                         c.get("actor_url") or c.get("authorUrl") or ""),
            "actor_position": _safe_str(
                a.get("position") or a.get("headline") or
                c.get("actor_position") or c.get("authorHeadline") or ""
            ),
            "actor_pic":      _safe_str(
                a.get("pictureUrl") or (a.get("picture") or {}).get("url") or
                a.get("profilePicture") or c.get("actor_pic") or
                c.get("authorProfilePicture") or ""
            ),
            "is_author": is_author,
        }
        all_c.append(entry)

        is_tgt, signal = _is_target_comment(
            actor_name=aname_raw,
            actor_url=entry["actor_url"],
            is_author=is_author,
            target_username=tid_lower,
            target_full_name=name_lower,
            name_tokens=name_tokens,
        )
        if is_tgt:
            owner_c.append(entry)

    return all_c[:20], owner_c



# ─────────────────────────────────────────────────────────────────────────────
# LINKEDIN CONTENT ANALYSIS ENGINE
# ─────────────────────────────────────────────────────────────────────────────

_LI_TOPICS: Dict[str, List[str]] = {
    "Teknologi & Inovasi":      ["tech","technology","ai","artificial intelligence",
                                  "software","coding","programming","developer","devops",
                                  "cloud","cybersecurity","network","linux","server",
                                  "automation","machine learning","data science","mlops",
                                  "kubernetes","docker","api","microservices","blockchain",
                                  "teknologi","inovasi","kecerdasan buatan","keamanan siber"],
    "Karir & Profesional":      ["career","job","hiring","work","professional","workplace",
                                  "interview","salary","promotion","resume","linkedin",
                                  "opportunity","role","position","recruiter","internship",
                                  "magang","karir","pekerjaan","lowongan","rekrutmen",
                                  "profesional","kerja","jabatan","promosi"],
    "Kepemimpinan":             ["leadership","leader","manager","director","ceo","cto",
                                  "management","team","mentor","coaching","strategy",
                                  "kepemimpinan","pemimpin","manajer","direktur","strategi"],
    "Bisnis & Ekonomi":         ["business","economy","market","finance","startup","revenue",
                                  "profit","investor","funding","venture","entrepreneur",
                                  "bisnis","ekonomi","pasar","keuangan","wirausaha",
                                  "pendanaan","investasi","peluncuran","modal"],
    "Pendidikan & Pengetahuan": ["education","learning","course","study","training","workshop",
                                  "certification","degree","university","tutorial","tips",
                                  "insight","lesson","knowledge","skill","belajar","kursus",
                                  "sertifikasi","pendidikan","universitas","tips","ilmu"],
    "Motivasi & Inspirasi":     ["inspire","motivation","dream","success","believe","mindset",
                                  "achieve","growth","goal","purpose","passion","resilience",
                                  "inspirasi","motivasi","mimpi","sukses","percaya","semangat",
                                  "tumbuh","tujuan","perjuangan","kegigihan"],
    "Sains & Alam":             ["science","research","data","climate","environment","biology",
                                  "physics","chemistry","astronomy","study","experiment",
                                  "sains","penelitian","lingkungan","ilmu pengetahuan"],
    "Sosial & Kemanusiaan":     ["social","community","charity","humanitarian","volunteer",
                                  "ngo","nonprofit","diversity","inclusion","equality",
                                  "sosial","komunitas","kemanusiaan","sukarela","keberagaman"],
    "Kesehatan & Gaya Hidup":   ["health","wellness","fitness","mental health","lifestyle",
                                  "meditation","nutrition","balance","productivity",
                                  "kesehatan","kebugaran","kesehatan mental","gaya hidup"],
    "Networking & Kolaborasi":  ["network","collaboration","partnership","connect","community",
                                  "event","conference","meetup","forum","jaringan",
                                  "kolaborasi","kemitraan","koneksi","komunitas","acara"],
}

_LI_MOOD: Dict[str, str] = {
    "Teknologi & Inovasi":      "antusias, teknikal, visioner, inovatif",
    "Karir & Profesional":      "profesional, ambisius, percaya diri, informatif",
    "Kepemimpinan":             "bijaksana, strategis, menginspirasi, tegas",
    "Bisnis & Ekonomi":         "analitis, strategis, ambisius, berorientasi hasil",
    "Pendidikan & Pengetahuan": "intelektual, informatif, antusias belajar, berbagi",
    "Motivasi & Inspirasi":     "positif, penuh semangat, inspiring, memotivasi",
    "Sains & Alam":             "analitis, kritis, intelektual, berbasis data",
    "Sosial & Kemanusiaan":     "empatik, peduli, solidaritas, menggerakkan",
    "Kesehatan & Gaya Hidup":   "seimbang, positif, peduli diri, reflektif",
    "Networking & Kolaborasi":  "kolaboratif, terbuka, ramah, ekspansif",
}

_LI_OBJECTS: Dict[str, str] = {
    "Teknologi & Inovasi":      "stack teknologi, alat pengembangan, infrastruktur, kode, sistem",
    "Karir & Profesional":      "peluang kerja, pencapaian karir, keahlian profesional, portofolio",
    "Kepemimpinan":             "strategi organisasi, dinamika tim, keputusan manajerial, visi",
    "Bisnis & Ekonomi":         "data bisnis, tren pasar, model revenue, ekosistem startup",
    "Pendidikan & Pengetahuan": "materi pembelajaran, sertifikasi, insight industri, tips",
    "Motivasi & Inspirasi":     "kisah inspiratif, pelajaran hidup, pencapaian, nilai-nilai",
    "Sains & Alam":             "data penelitian, temuan ilmiah, metodologi, tren sains",
    "Sosial & Kemanusiaan":     "isu sosial, program kemanusiaan, nilai komunitas, dampak",
    "Kesehatan & Gaya Hidup":   "kebiasaan sehat, keseimbangan kerja-hidup, produktivitas",
    "Networking & Kolaborasi":  "koneksi profesional, acara, komunitas, peluang sinergi",
}

_LI_ACTIVITY: Dict[str, str] = {
    "Teknologi & Inovasi":      "berbagi project, insight teknologi, atau inovasi terbaru",
    "Karir & Profesional":      "mendokumentasikan perjalanan karir dan pencapaian profesional",
    "Kepemimpinan":             "berbagi perspektif kepemimpinan dan pelajaran manajemen",
    "Bisnis & Ekonomi":         "mendiskusikan tren bisnis dan peluang ekonomi",
    "Pendidikan & Pengetahuan": "berbagi pengetahuan, tips, dan insight yang bernilai",
    "Motivasi & Inspirasi":     "menginspirasi dan memotivasi komunitas LinkedIn",
    "Sains & Alam":             "mendiskusikan perkembangan sains dan penelitian",
    "Sosial & Kemanusiaan":     "mengangkat isu sosial dan mendorong aksi komunitas",
    "Kesehatan & Gaya Hidup":   "berbagi tips kesehatan dan gaya hidup produktif",
    "Networking & Kolaborasi":  "memperluas jaringan dan mendorong kolaborasi",
}


def _detect_linkedin_topic(text: str, hashtags: List[str] = None) -> str:
    all_lower = (text + " " + " ".join(hashtags or [])).lower()
    scores: Dict[str, int] = {}
    for topic, kws in _LI_TOPICS.items():
        hits = sum(1 for kw in kws if kw in all_lower)
        if hits:
            scores[topic] = hits
    return max(scores, key=lambda k: scores[k]) if scores else "Karir & Profesional"


def _detect_linkedin_mood(text: str, topic: str) -> str:
    return _LI_MOOD.get(topic, "profesional, informatif, ekspresif")


def _detect_linkedin_objects(text: str, topic: str, media_type: str = "text") -> str:
    base = _LI_OBJECTS.get(topic, "konten teks, informasi profesional, insight")
    if media_type == "image":
        return base + ", gambar/foto pendukung"
    elif media_type == "video":
        return base + ", rekaman video, konten visual bergerak"
    elif media_type == "document":
        return base + ", dokumen/slide deck, materi terstruktur"
    elif media_type == "article":
        return base + ", artikel panjang, konten mendalam"
    return base


def _detect_linkedin_activity(text: str, topic: str) -> str:
    return _LI_ACTIVITY.get(topic, "berbagi konten profesional dan berinteraksi dengan komunitas")


def _li_engagement_level(likes: int, comments: int, shares: int) -> str:
    total = likes + (comments * 5) + (shares * 3)
    if total >= 100_000: return "VIRAL"
    if total >= 10_000:  return "SANGAT TINGGI"
    if total >= 1_000:   return "TINGGI"
    if total >= 100:     return "SEDANG"
    return "RENDAH"


def _build_linkedin_visual_description(
    content: str,
    media_type: str,
    post_images: List[Dict],
    document: Dict,
    article: Dict,
    hashtags: List[str],
) -> str:
    """Buat visual description berdasarkan konten dan tipe media."""
    if media_type == "text":
        clean = re.sub(r"[#@]|\bhttps?://\S+", "", content).strip()[:200]
        return f"Postingan teks LinkedIn: \"{clean}\"." if clean else "Postingan teks tanpa media."
    elif media_type == "image" and post_images:
        count = len(post_images)
        return (
            f"{'Carousel ' if count > 1 else ''}Foto LinkedIn ({count} gambar) yang mendampingi "
            f"postingan bertema '{' '.join('#'+h for h in hashtags[:3])}'. "
            f"Gambar digunakan untuk memperkuat pesan teks secara visual."
        )
    elif media_type == "video":
        return (
            f"Video LinkedIn yang menampilkan konten terkait "
            f"'{' '.join('#'+h for h in hashtags[:3])}'. "
            f"Format video digunakan untuk menyampaikan pesan dengan lebih dinamis dan engaging."
        )
    elif media_type == "document" and document:
        title = document.get("title") or "dokumen"
        pages = document.get("total_pages") or 0
        return (
            f"Dokumen/slide deck berjudul '{title}'"
            + (f" ({pages} halaman)" if pages else "")
            + ". Format carousel dokumen LinkedIn digunakan untuk menyajikan konten terstruktur."
        )
    elif media_type == "article" and article:
        title = article.get("title") or "artikel"
        return f"Artikel LinkedIn berjudul '{title}'. Konten panjang yang ditulis untuk berbagi insight mendalam."
    return "Konten LinkedIn dengan media pendukung."


def _build_linkedin_ai_description(
    content: str,
    topic: str,
    mood: str,
    objects: str,
    activity: str,
    media_type: str,
    hashtags: List[str],
    mentions: List[str],
    likes: int,
    comments: int,
    shares: int,
    reactions_breakdown: Dict[str, int],
    document: Dict,
    article: Dict,
    author_name: str,
    created_at: str,
    is_repost: bool,
) -> str:
    """
    Generate ai_description LinkedIn yang sangat detail (100-300 kata).
    Menjelaskan isi, konteks profesional, engagement, dan dampak konten.
    """
    clean_text = re.sub(r"\s+", " ", re.sub(r"https?://\S+", "", content)).strip()
    word_count = len(clean_text.split())
    eng_level  = _li_engagement_level(likes, comments, shares)

    parts: List[str] = []

    # ── 1. Pembuka ────────────────────────────────────────────────────────
    author_ctx = f"{author_name}" if author_name else "Pengguna LinkedIn ini"
    if is_repost:
        parts.append(
            f"{author_ctx} membagikan ulang konten dari sumber lain pada {created_at or 'tanggal tidak diketahui'}. "
            f"Tindakan reshare ini menunjukkan bahwa {author_ctx} menganggap konten tersebut bernilai "
            f"dan relevan untuk dibagikan kepada jaringan profesionalnya."
        )
    elif media_type == "document" and document.get("title"):
        pages = document.get("total_pages", 0)
        parts.append(
            f"{author_ctx} mempublikasikan dokumen berjudul '{document['title']}'"
            + (f" ({pages} halaman)" if pages else "")
            + f" pada {created_at or 'tanggal tidak diketahui'}. "
            f"Format dokumen/slide deck dipilih untuk menyajikan informasi secara terstruktur dan visual."
        )
    elif media_type == "article" and article.get("title"):
        parts.append(
            f"{author_ctx} membagikan artikel berjudul '{article['title']}' "
            f"pada {created_at or 'tanggal tidak diketahui'}. "
            f"Artikel merupakan format konten panjang yang menunjukkan kedalaman pemikiran dan keahlian."
        )
    else:
        media_desc = {
            "image":   "dilengkapi gambar/foto",
            "video":   "disertai video",
            "text":    "berupa teks",
        }
        parts.append(
            f"{author_ctx} mempublikasikan postingan LinkedIn {media_desc.get(media_type, '')} "
            f"pada {created_at or 'tanggal tidak diketahui'}."
        )

    # ── 2. Isi konten ─────────────────────────────────────────────────────
    if clean_text:
        gaya = ("sangat panjang dan mendalam" if word_count >= 100
                else "cukup panjang" if word_count >= 50
                else "singkat namun padat" if word_count >= 15
                else "sangat singkat")
        if word_count >= 20:
            parts.append(
                f"Konten ditulis dengan gaya {gaya} ({word_count} kata): "
                f"\"{clean_text[:500]}{'...' if len(clean_text) > 500 else ''}\""
            )
        else:
            parts.append(f"Isi postingan: \"{clean_text}\".")

    # ── 3. Topik & konteks profesional ────────────────────────────────────
    _ctx_map = {
        "Teknologi & Inovasi":      "membahas perkembangan teknologi, inovasi, atau project teknikal",
        "Karir & Profesional":      "berkaitan dengan perjalanan karir dan pencapaian profesional",
        "Kepemimpinan":             "menyentuh aspek kepemimpinan dan manajemen",
        "Bisnis & Ekonomi":         "membahas bisnis, ekonomi, atau peluang pasar",
        "Pendidikan & Pengetahuan": "berbagi pengetahuan, tips, atau insight edukatif",
        "Motivasi & Inspirasi":     "menyampaikan pesan motivasi dan inspirasi",
        "Sains & Alam":             "mendiskusikan topik sains atau penelitian",
        "Sosial & Kemanusiaan":     "mengangkat isu sosial atau kemanusiaan",
        "Kesehatan & Gaya Hidup":   "membahas kesehatan dan gaya hidup produktif",
        "Networking & Kolaborasi":  "mendorong networking dan kolaborasi profesional",
    }
    ctx = _ctx_map.get(topic, "bersifat informatif dan profesional")
    parts.append(
        f"Konten ini {ctx}, dengan topik utama '{topic}' dan suasana {mood}. "
        f"Elemen konten yang menonjol: {objects}. "
        f"Tujuan utama: {activity}."
    )

    # ── 4. Hashtag & mentions ─────────────────────────────────────────────
    if hashtags:
        parts.append(
            f"Menggunakan {len(hashtags)} hashtag strategis: "
            f"{', '.join('#'+h for h in hashtags[:8])}, "
            f"untuk menjangkau komunitas profesional yang relevan di LinkedIn."
        )
    if mentions:
        parts.append(
            f"Menyebut atau menandai: {', '.join('@'+m for m in mentions[:5])}, "
            f"menunjukkan kolaborasi atau referensi ke pihak terkait."
        )

    # ── 5. Engagement analysis ────────────────────────────────────────────
    total_eng = likes + comments + shares
    if eng_level == "VIRAL":
        parts.append(
            f"Postingan ini mencapai engagement VIRAL yang luar biasa dengan {likes:,} reaksi, "
            f"{comments:,} komentar, dan {shares:,} berbagi (total {total_eng:,} interaksi). "
            f"Konten ini telah menyebar jauh melampaui jaringan langsung penulis."
        )
    elif eng_level == "SANGAT TINGGI":
        parts.append(
            f"Engagement SANGAT TINGGI: {likes:,} reaksi, {comments:,} komentar, "
            f"{shares:,} berbagi — menandakan resonansi kuat dengan audiens profesional LinkedIn."
        )
    elif eng_level == "TINGGI":
        parts.append(
            f"Engagement TINGGI dengan {likes:,} reaksi, {comments:,} komentar, "
            f"dan {shares:,} berbagi. Konten ini berhasil menarik perhatian komunitas."
        )
    elif total_eng > 0:
        parts.append(
            f"Mendapatkan {likes:,} reaksi, {comments:,} komentar, {shares:,} berbagi."
        )

    # ── 6. Reactions breakdown ────────────────────────────────────────────
    if reactions_breakdown and sum(reactions_breakdown.values()) > 0:
        label_map = {
            "LIKE": "👍 Suka", "APPRECIATION": "👏 Apresiasi",
            "EMPATHY": "❤️ Empati", "PRAISE": "🙌 Pujian",
            "INTEREST": "🤔 Tertarik", "ENTERTAINMENT": "😄 Hiburan",
        }
        top_rxns = sorted(
            [(k, v) for k, v in reactions_breakdown.items() if v > 0],
            key=lambda x: x[1], reverse=True
        )[:3]
        rxn_str = ", ".join(f"{label_map.get(k, k)}: {v:,}" for k, v in top_rxns)
        parts.append(f"Distribusi reaksi: {rxn_str}.")

    return " ".join(parts)


def _analyze_linkedin_post(
    content: str,
    media_type: str,
    hashtags: List[str],
    mentions: List[str],
    likes: int,
    comments: int,
    shares: int,
    reactions_breakdown: Dict[str, int],
    document: Dict,
    article: Dict,
    post_images: List[Dict],
    author_name: str,
    created_at: str,
    is_repost: bool,
) -> Dict:
    """Return content_analysis lengkap untuk satu LinkedIn post."""
    topic    = _detect_linkedin_topic(content, hashtags)
    mood     = _detect_linkedin_mood(content, topic)
    objects  = _detect_linkedin_objects(content, topic, media_type)
    activity = _detect_linkedin_activity(content, topic)
    eng_lvl  = _li_engagement_level(likes, comments, shares)

    clean_text = re.sub(r"\s+", " ", re.sub(r"[#@]|\bhttps?://\S+", "", content)).strip()
    summary = clean_text[:200] if clean_text else (hashtags[0] if hashtags else "")

    # Deteksi emosi dari konten
    tl = content.lower()
    emotions: List[str] = []
    if any(w in tl for w in ["bangga","proud","achievement","penghargaan","winner"]):
        emotions.append("Bangga")
    if any(w in tl for w in ["excited","antusias","semangat","passionate","excited"]):
        emotions.append("Antusias")
    if any(w in tl for w in ["inspired","inspirasi","tergerak","motivated","motivasi"]):
        emotions.append("Inspiratif")
    if any(w in tl for w in ["visioner","future","masa depan","inovasi","revolution"]):
        emotions.append("Visioner")
    if any(w in tl for w in ["grateful","syukur","terima kasih","appreciate","alhamdulillah"]):
        emotions.append("Rasa Syukur")
    if any(w in tl for w in ["reflektif","belajar dari","lesson","pelajaran","introspeksi"]):
        emotions.append("Reflektif")
    if any(w in tl for w in ["percaya diri","confident","yakin","optimis","believe"]):
        emotions.append("Percaya Diri")
    if not emotions:
        emotions = ["Profesional"]

    # Language detection
    id_kw = ["yang","dan","di","ke","dari","untuk","ini","itu","dengan","adalah","tidak","saya","kami"]
    lang = "id" if sum(1 for w in id_kw if f" {w} " in f" {tl} ") >= 3 else "en"

    # Word count & readability
    wc = len(content.split()) if content else 0
    avg_wl = (sum(len(w) for w in content.split()) / wc) if wc > 0 else 0
    readability = max(20, min(100, int(100 - (avg_wl - 4) * 8)))

    ai_description = _build_linkedin_ai_description(
        content=content, topic=topic, mood=mood, objects=objects, activity=activity,
        media_type=media_type, hashtags=hashtags, mentions=mentions,
        likes=likes, comments=comments, shares=shares,
        reactions_breakdown=reactions_breakdown,
        document=document, article=article,
        author_name=author_name, created_at=created_at, is_repost=is_repost,
    )

    visual_description = _build_linkedin_visual_description(
        content=content, media_type=media_type, post_images=post_images,
        document=document, article=article, hashtags=hashtags,
    )

    return {
        "topic":             topic,
        "mood":              mood,
        "objects":           objects,
        "activity":          activity,
        "content_summary":   summary,
        "ai_description":    ai_description,
        "visual_description": visual_description,
        "key_themes":        [topic] + hashtags[:5],
        "engagement_level":  eng_lvl,
        "word_count":        wc,
        "readability_score": readability,
        "language":          lang,
        "detected_emotions": emotions,
    }


def _build_ai_description(content: str, media_type: str, engagement: Dict,
                           reactions_breakdown: Dict, document: Dict,
                           article: Dict, hashtags: List[str], post_url: str) -> str:
    if not content and not document.get("title") and not article.get("title"):
        return ""

    parts = []

    # 1. Jenis konten
    type_map = {
        "text":     "Postingan teks murni",
        "image":    "Postingan dengan gambar",
        "video":    "Postingan video",
        "document": "Postingan dokumen/slide deck",
        "article":  "Postingan berbagi artikel",
    }
    parts.append(f"[Jenis] {type_map.get(media_type, 'Postingan')}")

    # 2. Isi konten
    if content:
        words = content.split()
        word_count = len(words)
        preview = content[:300].replace("\n", " ")
        if len(content) > 300:
            preview += "..."
        parts.append(f"[Konten] {preview} (total {word_count} kata)")

        # Deteksi tema
        content_lower = content.lower()
        themes = []
        if any(w in content_lower for w in ["award", "penghargaan", "winner", "juara", "proud"]):
            themes.append("pencapaian/penghargaan")
        if any(w in content_lower for w in ["hiring", "lowongan", "vacancy", "join our", "we are looking"]):
            themes.append("rekrutmen/lowongan kerja")
        if any(w in content_lower for w in ["launch", "rilis", "announce", "new product", "introducing"]):
            themes.append("peluncuran produk/pengumuman")
        if any(w in content_lower for w in ["lesson", "belajar", "tips", "how to", "cara", "insight"]):
            themes.append("edukasi/tips/insight profesional")
        if any(w in content_lower for w in ["thank", "terima kasih", "grateful", "appreciate"]):
            themes.append("apresiasi/rasa syukur")
        if any(w in content_lower for w in ["question", "pertanyaan", "what do you think", "thoughts?"]):
            themes.append("pertanyaan/diskusi komunitas")
        if any(w in content_lower for w in ["partner", "kerjasama", "collaboration", "proud to"]):
            themes.append("kemitraan/kolaborasi")
        if any(w in content_lower for w in ["promote", "promo", "discount", "buy now", "offer"]):
            themes.append("promosi/iklan")
        if themes:
            parts.append(f"[Tema] {', '.join(themes)}")

        # Tone/gaya
        tone_signals = []
        if content.count("!") >= 2:
            tone_signals.append("antusias")
        if "?" in content:
            tone_signals.append("interaktif/mengundang diskusi")
        if any(w in content_lower for w in ["excited", "amazing", "incredible", "luar biasa"]):
            tone_signals.append("positif/bersemangat")
        if any(w in content_lower for w in ["challenging", "difficult", "struggle", "tantangan"]):
            tone_signals.append("reflektif/personal")
        if tone_signals:
            parts.append(f"[Tone] {', '.join(tone_signals)}")

        # Hashtag konteks
        if hashtags:
            parts.append(f"[Hashtag] #{' #'.join(hashtags[:8])}")

    # 3. Dokumen/slide
    if document.get("title"):
        doc_info = f"Dokumen berjudul '{document['title']}'"
        if document.get("total_pages"):
            doc_info += f" ({document['total_pages']} halaman)"
        if document.get("cover_images"):
            doc_info += " — tersedia cover preview"
        parts.append(f"[Dokumen] {doc_info}")

    # 4. Artikel
    if article.get("title"):
        art_info = f"Membagikan artikel: '{article['title']}'"
        if article.get("description"):
            art_info += f" — {article['description'][:150]}"
        parts.append(f"[Artikel] {art_info}")

    # 5. Engagement
    likes    = _safe_int(engagement.get("likes"))
    comments = _safe_int(engagement.get("comments"))
    shares   = _safe_int(engagement.get("shares"))
    total_eng = likes + comments + shares
    if total_eng > 0:
        eng_str = f"{likes:,} reaksi, {comments:,} komentar, {shares:,} berbagi (total {total_eng:,} interaksi)"
        if total_eng >= 10000:
            eng_str += " — VIRAL/sangat tinggi"
        elif total_eng >= 1000:
            eng_str += " — engagement tinggi"
        elif total_eng >= 100:
            eng_str += " — engagement sedang"
        parts.append(f"[Engagement] {eng_str}")

    # 6. Reactions breakdown
    if reactions_breakdown:
        r_parts = []
        label_map = {
            "LIKE": "👍 Suka", "APPRECIATION": "👏 Apresiasi",
            "EMPATHY": "❤️ Empati", "PRAISE": "🙌 Pujian",
            "INTEREST": "🤔 Tertarik", "ENTERTAINMENT": "😄 Hiburan",
        }
        for rtype, count in sorted(reactions_breakdown.items(), key=lambda x: -x[1]):
            if count > 0:
                label = label_map.get(rtype, rtype)
                r_parts.append(f"{label}: {count:,}")
        if r_parts:
            parts.append(f"[Reaksi Detail] {' | '.join(r_parts)}")

    return " || ".join(parts)


# ── Sync scraper ──────────────────────────────────────────────────────────────

def _linkedin_scrape_sync(username: str, apify_token: str) -> Dict:
    if not apify_token:
        import os
        from dotenv import load_dotenv
        load_dotenv()
        apify_token = os.getenv("APIFY_TOKEN", "")
    if not apify_token:
        return _empty(username, "APIFY_TOKEN tidak ditemukan di .env")
    try:
        from apify_client import ApifyClient
    except ImportError:
        return _empty(username, "apify_client tidak terinstall — pip install apify-client")

    clean = _clean_id(username)
    profile_url = f"https://www.linkedin.com/in/{clean}"
    print(f"📡 [LinkedIn] Scraping {profile_url}...")

    try:
        client = ApifyClient(apify_token)

        # ── RUN 1: Profile Detail ─────────────────────────────────────────
        # Strategy cascade:
        # A. automation-lab/linkedin-profile-scraper (no login, no cookies)
        #    Output: name, headline, location, about, followerCount, connectionCount,
        #            currentPositions[{title,company,startDate}],
        #            education[{institution,degree,startYear,endYear}],
        #            languages, websites, profileImageUrl
        #    TIDAK butuh cookie — gratis di free plan
        #
        # B. linkedintel-core/linkedin-profile-scraper-no-cookies (fallback)
        #    Output lebih lengkap: skills, certifications, interests, dll
        #    tapi kadang 403 di free plan
        print("   ↳ [1/2] Profile via automation-lab/linkedin-profile-scraper (no login)...")
        prof_data: Dict = {}

        # Strategy A: automation-lab — no login, return flat JSON per profile
        try:
            _rA = client.actor("automation-lab/linkedin-profile-scraper").call(run_input={
                "profileUrls": [profile_url],
                "maxProfiles": 1,
            })
            _dsA = getattr(_rA, "default_dataset_id", None)
            if _dsA:
                _itemsA = client.dataset(_dsA).list_items().items or []
                print(f"   ↳ automation-lab: {len(_itemsA)} item")
                if _itemsA:
                    _p = _itemsA[0]
                    # currentPositions → experience
                    _exp = []
                    for pos in (_p.get("currentPositions") or []):
                        _exp.append({
                            "title":           _safe_str(pos.get("title")),
                            "company":         _safe_str(pos.get("company")),
                            "company_url":     "",
                            "location":        "",
                            "description":     "",
                            "start":           _safe_str(pos.get("startDate") or ""),
                            "end":             "Sekarang",
                            "is_current":      True,
                            "employment_type": "",
                        })
                    # education → list
                    _edu = []
                    for edu in (_p.get("education") or []):
                        _edu.append({
                            "school":         _safe_str(edu.get("institution")),
                            "school_url":     "",
                            "degree":         _safe_str(edu.get("degree") or ""),
                            "field_of_study": "",
                            "grade":          "",
                            "description":    "",
                            "start":          _safe_str(edu.get("startYear") or ""),
                            "end":            _safe_str(edu.get("endYear") or ""),
                            "activities":     "",
                        })
                    prof_data = {
                        "full_name":        _safe_str(_p.get("name") or clean),
                        "headline":         _safe_str(_p.get("headline")),
                        "about":            _safe_str(_p.get("about")),
                        "profile_pic":      _safe_str(_p.get("profileImageUrl")),
                        "background_image": "",
                        "linkedin_url":     _safe_str(_p.get("linkedinUrl") or profile_url),
                        "website":          _safe_str((_p.get("websites") or [""])[0]),
                        "website_label":    "",
                        "location":         _safe_str(_p.get("location")),
                        "industry":         "",
                        "followers":        _safe_int(_p.get("followerCount")),
                        "connections_count":_safe_int(
                            str(_p.get("connectionCount") or "").replace("+","").replace(",","") or 0
                        ),
                        "connections":      _safe_str(_p.get("connectionCount") or ""),
                        "verified":         False,
                        "is_creator":       False,
                        "is_premium":       False,
                        "is_influencer":    False,
                        "is_open_to_work":  False,
                        "is_hiring":        False,
                        "current_company":  _exp[0]["company"] if _exp else "",
                        "current_title":    _exp[0]["title"]   if _exp else "",
                        "experience":       _exp,
                        "education":        _edu,
                        "skills":           [],
                        "certifications":   [],
                        "languages":        [_safe_str(l) for l in (_p.get("languages") or [])],
                        "interests":        [],
                        "volunteering":     [],
                        "projects":         [],
                        "publications":     [],
                        "honors":           [],
                        "courses":          [],
                        "organizations":    [],
                        "contact_email":    "",
                        "contact_phone":    "",
                        "join_date":        "",
                    }
                    print(
                        f"   ↳ Profile OK: {prof_data['full_name']} | "
                        f"Followers: {prof_data['followers']:,} | "
                        f"Exp: {len(prof_data['experience'])} | "
                        f"Edu: {len(prof_data['education'])}"
                    )
        except Exception as _eA:
            print(f"   ⚠️ automation-lab error (non-fatal): {_eA}")

        # Strategy B: linkedintel-core — untuk skills + certifications + interests
        # Jalan meskipun Strategy A sudah berhasil, untuk enrich data
        print("   ↳ [1b] Enrich skills+certifications via linkedintel-core...")
        try:
            _rB = client.actor("linkedintel-core/linkedin-profile-scraper-no-cookies").call(
                run_input={
                    "profileUrls":            [profile_url],
                    "includeAbout":           True,
                    "includeInterests":       True,
                    "includeContactInfo":     True,
                    "includeSimilar":         False,
                    "includeRecommendations": False,
                }
            )
            _dsB = getattr(_rB, "default_dataset_id", None)
            if _dsB:
                recsB = client.dataset(_dsB).list_items().items or []
                print(f"   ↳ linkedintel-core: {len(recsB)} records")
                if recsB:
                    _pb = _parse_profile_records(recsB, clean)
                    # Merge: ambil data yang belum ada dari Strategy A
                    if not prof_data:
                        prof_data = _pb
                    else:
                        # Enrich fields yang kosong dari Strategy A
                        for _field in ["skills","certifications","interests","volunteering",
                                        "projects","publications","honors","courses","organizations",
                                        "about","join_date","contact_email","contact_phone",
                                        "is_open_to_work","is_hiring","is_creator","is_premium"]:
                            if not prof_data.get(_field) and _pb.get(_field):
                                prof_data[_field] = _pb[_field]
                        # Override experience/education jika linkedintel lebih lengkap
                        if len(_pb.get("experience", [])) > len(prof_data.get("experience", [])):
                            prof_data["experience"] = _pb["experience"]
                        if len(_pb.get("education", [])) > len(prof_data.get("education", [])):
                            prof_data["education"] = _pb["education"]
                        # Followers fallback
                        if not prof_data.get("followers") and _pb.get("followers"):
                            prof_data["followers"] = _pb["followers"]
                    print(
                        f"   ↳ Enrich OK: Skills={len(prof_data.get('skills',[]))} | "
                        f"Certs={len(prof_data.get('certifications',[]))} | "
                        f"Interests={len(prof_data.get('interests',[]))}"
                    )
        except Exception as _eB:
            print(f"   ⚠️ linkedintel-core error (non-fatal): {_eB}")

        # Final fallback jika kedua actor gagal
        if not prof_data:
            prof_data = {
                "full_name": clean, "headline": "", "about": "",
                "profile_pic": "", "background_image": "", "linkedin_url": profile_url,
                "location": "", "industry": "", "followers": 0,
                "connections_count": 0, "connections": "",
                "verified": False, "is_creator": False, "is_premium": False,
                "is_influencer": False, "is_open_to_work": False, "is_hiring": False,
                "current_company": "", "current_title": "",
                "experience": [], "education": [], "skills": [], "certifications": [],
                "languages": [], "interests": [], "volunteering": [],
                "projects": [], "publications": [], "honors": [],
                "courses": [], "organizations": [],
                "contact_email": "", "contact_phone": "", "join_date": "",
            }

        # ── RUN 2: Posts + Comments + Reactions ───────────────────────────
        # harvestapi/linkedin-profile-posts
        # Output: posts dengan reactions breakdown, siapa yang react,
        # comments[] dengan actor detail (name, position, picture)
        print("   ↳ [2/2] Posts + reactions + comments via harvestapi/linkedin-profile-posts...")
        posts:             List[Dict] = []
        reposts:           List[Dict] = []
        all_user_comments: List[Dict] = []
        all_photos:        List[Dict] = []

        public_id = (prof_data.get("linkedin_url") or profile_url).lower()
        # Ambil identifier dari URL untuk filter komentar
        id_for_filter = clean.lower()

        try:
            r2 = client.actor("harvestapi/linkedin-profile-posts").call(
                run_input={
                    "profileUrls": [profile_url],
                    "maxPosts":    15,
                }
            )
            ds2 = getattr(r2, "default_dataset_id", None)
            if not ds2:
                raise ValueError("Dataset ID posts tidak ditemukan")

            items = client.dataset(ds2).list_items().items or []
            print(f"   ↳ Posts raw: {len(items)}")

            # Fallback profil dari post items — ambil semua field yang bisa dari author
            if items:
                a0 = (items[0].get("author") or {})
                # Selalu update field yang masih kosong dari profile actor
                if not prof_data.get("full_name") or prof_data.get("full_name") == clean:
                    if a0.get("name"):
                        prof_data["full_name"] = _safe_str(a0.get("name"))
                if not prof_data.get("profile_pic"):
                    prof_data["profile_pic"] = _safe_str(
                        (a0.get("avatar") or {}).get("url") or a0.get("pictureUrl") or
                        a0.get("profilePic") or ""
                    )
                if not prof_data.get("headline"):
                    prof_data["headline"] = _safe_str(
                        a0.get("info") or a0.get("headline") or a0.get("title") or ""
                    )
                if not prof_data.get("linkedin_url") or prof_data["linkedin_url"] == profile_url:
                    prof_data["linkedin_url"] = _safe_str(a0.get("linkedinUrl") or profile_url)
                if not prof_data.get("website"):
                    prof_data["website"]       = _safe_str(a0.get("website") or "")
                    prof_data["website_label"] = _safe_str(a0.get("websiteLabel") or "")
                # followers bisa ada di author.followersCount
                if not prof_data.get("followers"):
                    prof_data["followers"] = _safe_int(
                        a0.get("followerCount") or a0.get("followersCount") or
                        a0.get("followers") or 0
                    )
                if not prof_data.get("connections_count"):
                    prof_data["connections_count"] = _safe_int(
                        a0.get("connectionsCount") or a0.get("connections") or 0
                    )
                if not prof_data.get("location"):
                    prof_data["location"] = _safe_str(a0.get("location") or "")
                if not prof_data.get("industry"):
                    prof_data["industry"] = _safe_str(a0.get("industry") or "")

            for item in items:
                if item.get("type") and item.get("type") != "post":
                    continue
                post_id  = _safe_str(item.get("id"))
                post_url = _safe_str(item.get("linkedinUrl") or "")
                if not post_id and not post_url:
                    continue

                content    = _safe_str(
                    item.get("content") or
                    item.get("text") or
                    item.get("commentary") or       # harvestapi v2 pakai field ini
                    item.get("description") or
                    item.get("body") or
                    (item.get("resharedPost") or {}).get("content") or
                    ""
                )
                posted_at  = _parse_li_date(item.get("postedAt"))
                eng        = item.get("engagement") or {}
                likes      = _safe_int(eng.get("likes"))
                comments_n = _safe_int(eng.get("comments"))
                shares     = _safe_int(eng.get("shares"))

                rb         = _parse_reactions_breakdown(eng.get("reactions") or [])
                if not likes and rb:
                    likes = sum(rb.values())
                ra         = _parse_reactions_actors(item.get("reactions") or [])

                # Parse comments dari harvestapi output (mungkin ada, mungkin tidak)
                # Pass full_name juga agar filter multi-signal bisa match nama
                target_full_name = prof_data.get("full_name") or clean
                all_c, owner_c = _parse_comments(
                    item.get("comments") or [],
                    id_for_filter,
                    target_name=target_full_name
                )
                for oc in owner_c:
                    all_user_comments.append({
                        "post_url":    post_url,
                        "post_caption": content[:100],
                        "post_author": clean,
                        "content":     oc["content"],
                        "likes":       _safe_int(oc.get("likes")),
                        "replies":     oc["num_replies"],
                        "is_reply":    False,
                        "reply_to":    "",
                        "created_at":  oc["created_at"],
                        "comment_url": oc["comment_url"],
                        "sentiment":   {"label": "NEUTRAL", "score": 0.5},
                    })

                post_images = _parse_post_images(item.get("postImages") or [])
                document    = _parse_document(item.get("document"))
                image_url   = post_images[0]["url"] if post_images else (
                    document.get("cover_images", [""])[0] if document.get("cover_images") else ""
                )
                video_raw   = item.get("video") or {}
                video_url   = _safe_str(video_raw.get("url") or video_raw.get("streamUrl") or "") \
                              if isinstance(video_raw, dict) else ""
                art_raw     = item.get("article") or {}
                article     = {
                    "title":       _safe_str(art_raw.get("title")),
                    "url":         _safe_str(art_raw.get("url")),
                    "description": _safe_str(art_raw.get("description")),
                    "thumbnail":   _safe_str((art_raw.get("image") or {}).get("url") or art_raw.get("thumbnail") or ""),
                } if isinstance(art_raw, dict) and art_raw else {}

                media_type = (
                    "video"    if video_url else
                    "document" if document.get("title") else
                    "image"    if post_images else
                    "article"  if article else
                    "text"
                )
                hashtags = re.findall(r"#(\w+)", content)
                mentions = re.findall(r"@(\w+)", content)

                item_author_id = _safe_str(
                    (item.get("author") or {}).get("publicIdentifier") or ""
                ).lower()
                is_repost = (
                    bool(item.get("isRepost")) or
                    bool(item.get("resharedPost")) or
                    (item_author_id and item_author_id not in (id_for_filter, clean.lower()))
                )

                for img in post_images:
                    all_photos.append({
                        "image_url": img["url"], "post_url": post_url,
                        "caption": content[:150], "date": posted_at,
                        "width": img["width"], "height": img["height"],
                    })

                # AI description super detail
                ai_desc = _build_ai_description(
                    content, media_type,
                    {"likes": likes, "comments": comments_n, "shares": shares},
                    rb, document, article, hashtags, post_url
                )

                # ── Content analysis lengkap ──────────────────────────────
                # Kalau content kosong tapi ada document/article, pakai title sebagai fallback
                _content_for_analysis = content
                if not _content_for_analysis:
                    if document.get("title"):
                        _content_for_analysis = document["title"]
                    elif article.get("title"):
                        _content_for_analysis = article["title"]
                    elif hashtags:
                        _content_for_analysis = " ".join(hashtags)

                target_author = prof_data.get("full_name") or clean
                ca = _analyze_linkedin_post(
                    content=_content_for_analysis, media_type=media_type,
                    hashtags=hashtags, mentions=mentions,
                    likes=likes, comments=comments_n, shares=shares,
                    reactions_breakdown=rb,
                    document=document, article=article,
                    post_images=post_images,
                    author_name=target_author,
                    created_at=posted_at,
                    is_repost=is_repost,
                )

                # ── Timestamps ────────────────────────────────────────────
                import time as _tm
                ts_int = 0
                if posted_at:
                    try:
                        ts_int = int(_tm.mktime(_tm.strptime(posted_at, "%Y-%m-%d")))
                    except Exception:
                        pass
                created_iso = (
                    _tm.strftime("%Y-%m-%dT%H:%M:%S.000Z", _tm.gmtime(ts_int))
                    if ts_int else ""
                )

                # ── media_list ────────────────────────────────────────────
                media_list_full: List[Dict] = []
                for pi in post_images:
                    media_list_full.append({
                        "type":    "image",
                        "url":     pi.get("url", ""),
                        "width":   pi.get("width", 0),
                        "height":  pi.get("height", 0),
                        "size_mb": 0,
                    })
                if video_url:
                    media_list_full.append({"type": "video", "url": video_url, "width": 0, "height": 0, "size_mb": 0})

                entry = {
                    "id":                   post_id,
                    "post_id":              post_id,
                    "content":              content,
                    "post_url":             post_url,
                    "created_at":           posted_at,
                    "created_at_timestamp": ts_int,
                    "created_at_iso":       created_iso,
                    "likes":                likes,
                    "comments":             comments_n,
                    "shares":               shares,
                    "plays":                0,
                    "reactions_breakdown":  rb,
                    "reactions_total":      sum(rb.values()) if rb else likes,
                    "reactions_actors":     ra[:10],
                    "image_url":            image_url,
                    "video_url":            video_url,
                    "cover_url":            image_url or video_url,
                    "media_type":           media_type,
                    "media_count":          len(post_images) + (1 if video_url else 0),
                    "media_list":           media_list_full,
                    "hashtags":             hashtags,
                    "mentions":             mentions,
                    "tagged_users":         [],
                    "urls":                 [u for u in re.findall(r"https?://\S+", content)
                                             if "linkedin.com" not in u],
                    "is_repost":            is_repost,
                    "is_reply":             False,
                    "is_ad":                False,
                    "is_sponsored":         False,
                    "is_pinned":            False,
                    "is_article":           media_type == "article",
                    "document":             document,
                    "article":              article,
                    "post_images":          post_images,
                    "comments_data":        all_c,
                    "comments_count_total": comments_n,
                    "comments_count_visible": len(all_c),
                    # ── Content Analysis ──────────────────────────────────
                    "visual_description":   ca["visual_description"],
                    "topic":                ca["topic"],
                    "mood":                 ca["mood"],
                    "objects":              ca["objects"],
                    "activity":             ca["activity"],
                    "sentiment":            {"label": "NEUTRAL", "score": 0.5},
                    "content_analysis":     ca,
                    # ── Legacy (backward compat) ──────────────────────────
                    "ai_description":       ca["ai_description"],
                    "duration_sec":         0,
                    "music":                {"title": "", "author": ""},
                }

                if is_repost:
                    rs = item.get("resharedPost") or {}
                    oa = rs.get("author") or item.get("author") or {}
                    # Konten asli dari resharedPost
                    orig_content = _safe_str(rs.get("content") or rs.get("text") or rs.get("commentary") or content)
                    orig_hashtags = re.findall(r"#(\w+)", orig_content)
                    # Gunakan _analyze_linkedin_post untuk repost juga
                    ca_repost = _analyze_linkedin_post(
                        content=orig_content, media_type=media_type,
                        hashtags=orig_hashtags, mentions=re.findall(r"@(\w+)", orig_content),
                        likes=likes, comments=comments_n, shares=shares,
                        reactions_breakdown=rb, document=document, article=article,
                        post_images=post_images,
                        author_name=_safe_str(oa.get("name") or ""),
                        created_at=posted_at, is_repost=True,
                    )
                    reposts.append({
                        "video_url":           post_url,
                        "original_author":     _safe_str(oa.get("name")),
                        "original_author_url": _safe_str(oa.get("linkedinUrl")),
                        "original_caption":    orig_content[:300],
                        "repost_date":         posted_at,
                        "hashtags":            orig_hashtags,
                        "media_type":          media_type,
                        "metrics":             {"likes": likes, "comments": comments_n, "shares": shares, "plays": 0},
                        "reactions_breakdown": rb,
                        "sentiment":           {"label": "NEUTRAL", "score": 0.5},
                        "content_analysis":    ca_repost,
                        "content_description": ca_repost["ai_description"],
                    })
                else:
                    posts.append(entry)

        except Exception as e2:
            print(f"   ⚠️ Posts scraper error (non-fatal): {e2}")

        # ── FALLBACK: Comments via crawlerbros/linkedin-comments-scraper ────
        # Actor ini return authorName, authorProfileUrl, commentText, isReply, parentCommentId
        # Butuh li_at cookie dari .env (LINKEDIN_LI_AT)
        # Scan 2 sumber:
        #   Sumber 1: post target sendiri (top 3) → cari REPLY dari target
        #   Sumber 2: reposts (top 2) → cari KOMENTAR dari target di post orang lain
        import os as _os
        from dotenv import load_dotenv as _lde
        _lde()
        _li_at = _os.getenv("LINKEDIN_LI_AT", "").strip()

        target_full_name = prof_data.get("full_name") or clean
        name_tokens_fb   = {t for t in target_full_name.lower().split() if len(t) > 2}

        _src1 = [p for p in posts if p.get("comments", 0) > 0][:3]
        _src2 = [r for r in reposts if r.get("video_url")][:2]

        _urls_to_scan: List[tuple] = []
        for _p in _src1:
            if _p.get("post_url"):
                _urls_to_scan.append((_p["post_url"], _p.get("content","")[:100], True))
        for _r in _src2:
            if _r.get("video_url"):
                _urls_to_scan.append((_r["video_url"], _r.get("original_caption","")[:100], False))

        if not _li_at:
            print(
                f"   ⚠️ LINKEDIN_LI_AT kosong di .env — skip comment scan.\n"
                f"   ↳ Cara ambil: linkedin.com → F12 → Application → Cookies → li_at → copy value\n"
                f"   ↳ Tambahkan ke .env: LINKEDIN_LI_AT=nilai_li_at"
            )
        elif _urls_to_scan:
            print(
                f"   ↳ [Comments] Scan {len(_urls_to_scan)} URL via crawlerbros/linkedin-comments-scraper "
                f"({len(_src1)} own posts + {len(_src2)} reposts)..."
            )
            for _purl, _pcap, _is_own in _urls_to_scan:
                try:
                    _rc = client.actor("crawlerbros/linkedin-comments-scraper").call(run_input={
                        "postUrls":          [_purl],
                        "cookie":            _li_at,
                        "maxCommentsPerPost": 50,
                        "includeReplies":    True,   # ambil nested replies juga
                        "proxyConfiguration": {"useApifyProxy": True},
                    })
                    _dsc = getattr(_rc, "default_dataset_id", None)
                    if not _dsc:
                        continue
                    _ci = client.dataset(_dsc).list_items().items or []
                    src_label = "own" if _is_own else "repost"
                    print(f"   ↳ [{src_label}] {_purl[-55:]}: {len(_ci)} komentar")

                    _fallback_comments: List[Dict] = []
                    for _c in _ci:
                        # crawlerbros schema: authorName, authorProfileUrl, authorHeadline,
                        # authorAvatar, commentText, commentedAt, reactionsCount,
                        # repliesCount, isReply, parentCommentId, commentId
                        _aname = _safe_str(_c.get("authorName") or "")
                        _aurl  = _safe_str(_c.get("authorProfileUrl") or "").lower()
                        _apos  = _safe_str(_c.get("authorHeadline") or "")
                        _apic  = _safe_str(_c.get("authorAvatar") or "")
                        _ctext = _safe_str(_c.get("commentText") or "")
                        _clikes = _safe_int(_c.get("reactionsCount") or 0)
                        _cnrep  = _safe_int(_c.get("repliesCount") or 0)
                        _cdate  = _safe_str(_c.get("commentedAt") or "")[:10]
                        _cid    = _safe_str(_c.get("commentId") or "")
                        _curl   = _safe_str(_c.get("postUrl") or _purl)
                        _is_reply_item = bool(_c.get("isReply"))
                        _parent_id = _safe_str(_c.get("parentCommentId") or "")

                        if not _ctext:
                            continue

                        _entry = {
                            "comment_id":     _cid,
                            "comment_url":    _curl,
                            "content":        _ctext,
                            "created_at":     _cdate,
                            "num_replies":    _cnrep,
                            "likes":          _clikes,
                            "pinned":         False,
                            "edited":         False,
                            "actor_name":     _aname,
                            "actor_url":      _aurl,
                            "actor_position": _apos,
                            "actor_pic":      _apic,
                            "is_author":      False,
                            "is_reply":       _is_reply_item,
                            "parent_comment_id": _parent_id,
                        }
                        _fallback_comments.append(_entry)

                        # Multi-signal detection
                        _is_tgt, _signal = _is_target_comment(
                            actor_name=_aname,
                            actor_url=_aurl,
                            is_author=False,
                            target_username=id_for_filter,
                            target_full_name=target_full_name,
                            name_tokens=name_tokens_fb,
                        )

                        if _is_tgt:
                            print(f"   ✅ user_comment [{_signal}]: '{_aname}': '{_ctext[:60]}'")
                            _ca_c = _analyze_linkedin_post(
                                content=_ctext, media_type="text",
                                hashtags=re.findall(r"#(\w+)", _ctext),
                                mentions=re.findall(r"@(\w+)", _ctext),
                                likes=_clikes, comments=0, shares=0,
                                reactions_breakdown={}, document={}, article={},
                                post_images=[],
                                author_name=target_full_name,
                                created_at=_cdate, is_repost=False,
                            )
                            all_user_comments.append({
                                "post_url":       _purl,
                                "post_caption":   _pcap,
                                "post_author":    clean,
                                "content":        _ctext,
                                "comment_id":     _cid,
                                "comment_url":    _curl,
                                "likes":          _clikes,
                                "replies":        _cnrep,
                                "num_replies":    _cnrep,
                                "is_reply":       _is_reply_item or _is_own,
                                "reply_to":       _parent_id,
                                "created_at":     _cdate,
                                "sentiment":      {"label": "NEUTRAL", "score": 0.5},
                                "content_analysis": {
                                    "topic":            _ca_c["topic"],
                                    "mood":             _ca_c["mood"],
                                    "objects":          _ca_c["objects"],
                                    "activity":         _ca_c["activity"],
                                    "ai_description":   _ca_c["ai_description"],
                                    "engagement_level": _ca_c["engagement_level"],
                                },
                            })

                    # Inject comments_data ke own posts
                    if _is_own and _fallback_comments:
                        for _idx, _pp in enumerate(posts):
                            if _pp.get("post_url") == _purl:
                                posts[_idx]["comments_data"] = _fallback_comments[:20]
                                posts[_idx]["comments_count_visible"] = len(_fallback_comments[:20])
                                break

                except Exception as _ec:
                    print(f"   ⚠️ Comments scan error (non-fatal): {_ec}")
                    continue

        print(f"   ↳ user_comments final: {len(all_user_comments)}")

        # ── User comments summary ─────────────────────────────────────────
        _uc_summary: Dict = {}
        if all_user_comments:
            _uc_summary = {
                "total":              len(all_user_comments),
                "average_likes":      round(
                    sum(c["likes"] for c in all_user_comments) / len(all_user_comments), 1
                ),
                "top_comment":        max(all_user_comments, key=lambda x: x["likes"])["content"][:150],
                "top_comment_likes":  max(all_user_comments, key=lambda x: x["likes"])["likes"],
                "most_active_post":   max(
                    set(c["post_url"] for c in all_user_comments),
                    key=lambda x: sum(1 for c in all_user_comments if c["post_url"] == x)
                ),
            }

        posts             = posts[:20]
        reposts           = reposts[:10]
        all_user_comments = all_user_comments[:15]
        all_photos        = all_photos[:20]

        total_likes    = sum(p["likes"]    for p in posts)
        total_comments = sum(p["comments"] for p in posts)
        total_shares   = sum(p["shares"]   for p in posts)

        print(
            f"   ↳ Posts: {len(posts)} | Reposts: {len(reposts)} | "
            f"user_comments: {len(all_user_comments)} | Photos: {len(all_photos)}"
        )

        return {
            "status": "success", "platform": "linkedin", "username": clean,
            # Profile
            "full_name":        prof_data.get("full_name", clean),
            "headline":         prof_data.get("headline", ""),
            "bio":              prof_data.get("headline", ""),
            "about":            prof_data.get("about", ""),
            "profile_pic":      prof_data.get("profile_pic", ""),
            "background_image": prof_data.get("background_image", ""),
            "linkedin_url":     prof_data.get("linkedin_url", profile_url),
            "website":          prof_data.get("website", ""),
            "website_label":    prof_data.get("website_label", ""),
            "location":         prof_data.get("location", ""),
            "industry":         prof_data.get("industry", ""),
            "followers":        prof_data.get("followers", 0),
            "connections_count":prof_data.get("connections_count", 0),
            "connections":      prof_data.get("connections", ""),
            "following":        0,
            "verified":         prof_data.get("verified", False),
            "is_creator":       prof_data.get("is_creator", False),
            "is_premium":       prof_data.get("is_premium", False),
            "is_influencer":    prof_data.get("is_influencer", False),
            "is_open_to_work":  prof_data.get("is_open_to_work", False),
            "is_hiring":        prof_data.get("is_hiring", False),
            "join_date":        prof_data.get("join_date", ""),
            "current_company":  prof_data.get("current_company", ""),
            "current_title":    prof_data.get("current_title", ""),
            "experience":       prof_data.get("experience", []),
            "education":        prof_data.get("education", []),
            "skills":           prof_data.get("skills", []),
            "certifications":   prof_data.get("certifications", []),
            "languages":        prof_data.get("languages", []),
            "interests":        prof_data.get("interests", []),
            "volunteering":     prof_data.get("volunteering", []),
            "projects":         prof_data.get("projects", []),
            "publications":     prof_data.get("publications", []),
            "honors":           prof_data.get("honors", []),
            "courses":          prof_data.get("courses", []),
            "organizations":    prof_data.get("organizations", []),
            "contact_email":    prof_data.get("contact_email", ""),
            "contact_phone":    prof_data.get("contact_phone", ""),
            # Stats
            "total_posts":    len(posts),
            "total_likes":    total_likes,
            "total_comments": total_comments,
            "total_shares":   total_shares,
            "has_text":       any(p["content"] for p in posts),
            # Data
            "posts":         posts,
            "photos":        all_photos,
            "user_comments": all_user_comments,
            "user_comments_summary": _uc_summary,
            "reposts":       reposts,
            # Meta
            "scrape_errors": [],
            "data_limitations": [
                "private_posts: tidak bisa diakses",
                "dm: tidak bisa diakses",
                "connections_list: selalu privat",
                "email_phone: hanya tersedia jika user set public",
                "video_views: tidak di-expose free API",
                "comment_likes: tidak di-expose actor",
            ],
        }

    except Exception as e:
        import traceback
        err = f"LinkedIn scrape error: {str(e)}"
        print(f"   ❌ {err}")
        print(traceback.format_exc())
        return _empty(clean, err)


# ── Async wrapper ─────────────────────────────────────────────────────────────

async def _linkedin_scrape_real(username: str, apify_token: str = "") -> Dict:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, partial(_linkedin_scrape_sync, username, apify_token))
