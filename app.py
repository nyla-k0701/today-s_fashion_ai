# app.py
# "오늘 뭐 입지? OOTD" Streamlit prototype
# Added: Onboarding -> "빠른 시작용 기본 옷장 프리셋" 자동 생성 (보완전략 2)

import os
import re
import json
import uuid
import math
import time
import datetime as dt
from typing import Dict, List, Optional, Any, Tuple

import streamlit as st
from PIL import Image

# Optional deps
try:
    import requests
except Exception:
    requests = None

try:
    from openai import OpenAI
except Exception:
    OpenAI = None


APP_TITLE = "오늘 뭐 입지? OOTD"

DATA_DIR = ".data"
IMG_DIR = os.path.join(DATA_DIR, "images")
DB_PATH = os.path.join(DATA_DIR, "db.json")

DEFAULT_CATEGORIES = ["상의", "하의", "원피스", "아우터", "신발", "양말", "악세서리", "가방"]
DEFAULT_COLORS = ["블랙", "화이트", "그레이", "네이비", "베이지", "브라운", "레드", "블루", "그린", "옐로우", "핑크", "퍼플", "기타"]
DEFAULT_LENGTHS = ["크롭", "숏", "레귤러", "롱", "맥시", "기타"]
DEFAULT_NECKLINES = ["라운드", "브이넥", "셔츠카라", "터틀넥", "오프숄더", "기타"]

DEFAULT_TPO = ["학교", "직장", "결혼식", "운동", "여행", "데이트", "면접", "캐주얼 외출", "기타"]
DEFAULT_MOODS = ["미니멀", "캐주얼", "포멀", "스트릿", "러블리", "스포티", "클래식"]

# Onboarding preset options
ONBOARD_STYLE = ["미니멀", "캐주얼", "포멀", "스트릿", "러블리", "스포티", "클래식"]
ONBOARD_CONTEXT = ["학교", "직장", "학교+직장", "외출/데이트", "운동/활동", "여행", "기타"]
ONBOARD_COLOR_PREF = ["무채(블랙/화이트/그레이)", "톤다운(네이비/브라운/베이지)", "컬러포인트(레드/블루/그린 등)", "상관없음"]
ONBOARD_WARDROBE_SIZE = ["적음(10벌 이하)", "보통(10~30벌)", "많음(30벌 이상)"]


# ----------------------------
# Storage helpers
# ----------------------------
def ensure_dirs():
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(IMG_DIR, exist_ok=True)

def load_db() -> Dict[str, Any]:
    ensure_dirs()
    if not os.path.exists(DB_PATH):
        db = {
            "items": [],
            "outfits": [],
            "posts": [],
            "likes": {},
            "meta": {"created_at": time.time(), "onboarding_completed": False, "onboarding_profile": None},
        }
        save_db(db)
        return db
    with open(DB_PATH, "r", encoding="utf-8") as f:
        db = json.load(f)
    # Backward-compatible defaults
    db.setdefault("items", [])
    db.setdefault("outfits", [])
    db.setdefault("posts", [])
    db.setdefault("likes", {})
    db.setdefault("meta", {})
    db["meta"].setdefault("onboarding_completed", False)
    db["meta"].setdefault("onboarding_profile", None)
    return db

def save_db(db: Dict[str, Any]) -> None:
    ensure_dirs()
    with open(DB_PATH, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)

def now_ts() -> float:
    return time.time()

def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"

def has_any_real_items(db: Dict[str, Any]) -> bool:
    # "preset"이 아닌 실제 아이템이 1개라도 있으면 True
    for it in db.get("items", []):
        if not it.get("is_preset", False):
            return True
    return False

def has_any_items(db: Dict[str, Any]) -> bool:
    return len(db.get("items", [])) > 0


# ----------------------------
# Weather helpers (optional Open-Meteo)
# ----------------------------
def fetch_weather_open_meteo(city: str) -> Optional[Dict[str, Any]]:
    if requests is None:
        return None
    city = (city or "").strip()
    if not city:
        return None
    try:
        geo = requests.get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={"name": city, "count": 1, "language": "ko", "format": "json"},
            timeout=6,
        ).json()
        if "results" not in geo or not geo["results"]:
            return None
        lat = geo["results"][0]["latitude"]
        lon = geo["results"][0]["longitude"]

        fc = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": lat,
                "longitude": lon,
                "current": "temperature_2m,precipitation_probability,wind_speed_10m",
                "timezone": "Asia/Seoul",
            },
            timeout=6,
        ).json()

        cur = fc.get("current", {})
        temp = cur.get("temperature_2m")
        pop = cur.get("precipitation_probability")
        wind = cur.get("wind_speed_10m")

        summary_bits = []
        if temp is not None:
            summary_bits.append(f"{temp}°C")
        if pop is not None:
            summary_bits.append(f"강수확률 {pop}%")
        if wind is not None:
            summary_bits.append(f"바람 {wind}m/s")
        return {
            "temp_c": temp,
            "precip_prob": pop,
            "wind_ms": wind,
            "summary": " · ".join(summary_bits) if summary_bits else "현재 날씨",
            "source": "open-meteo",
        }
    except Exception:
        return None


# ----------------------------
# Context & UI theming (gradient vibe)
# ----------------------------
def season_from_temp(temp_c: Optional[float]) -> str:
    if temp_c is None:
        return "all"
    if temp_c <= 5:
        return "winter"
    if temp_c <= 16:
        return "spring_fall"
    if temp_c <= 26:
        return "mild"
    return "summer"

def theme_for_season(season: str) -> Dict[str, str]:
    if season == "winter":
        return {
            "title_emoji": "❄️",
            "bg": """
            radial-gradient(circle at 10% 20%, rgba(255,255,255,0.70), rgba(255,255,255,0.0) 35%),
            radial-gradient(circle at 80% 30%, rgba(255,255,255,0.55), rgba(255,255,255,0.0) 40%),
            linear-gradient(135deg, rgba(230,240,255,1), rgba(245,250,255,1))
            """,
            "decor": "❄️  ✨  ❄️  ✨",
            "tagline": "차가운 공기에도 따뜻하게—오늘의 코디를 골라드릴게요",
        }
    if season == "summer":
        return {
            "title_emoji": "☀️",
            "bg": """
            radial-gradient(circle at 70% 25%, rgba(255,235,160,0.85), rgba(255,235,160,0.0) 45%),
            radial-gradient(circle at 25% 65%, rgba(255,200,120,0.35), rgba(255,200,120,0.0) 55%),
            linear-gradient(135deg, rgba(255,250,235,1), rgba(235,248,255,1))
            """,
            "decor": "☀️  🌤️  ✨  🕶️",
            "tagline": "가볍게, 시원하게—상황에 딱 맞는 OOTD 추천",
        }
    if season == "mild":
        return {
            "title_emoji": "🌤️",
            "bg": """
            radial-gradient(circle at 80% 25%, rgba(255,245,200,0.55), rgba(255,245,200,0.0) 50%),
            linear-gradient(135deg, rgba(240,250,255,1), rgba(245,255,250,1))
            """,
            "decor": "🌤️  ✨  🌿  ✨",
            "tagline": "따뜻한 날씨엔 산뜻한 밸런스로—오코추 눌러볼래요?",
        }
    return {
        "title_emoji": "🌸",
        "bg": """
        radial-gradient(circle at 25% 20%, rgba(255,210,230,0.55), rgba(255,210,230,0.0) 50%),
        radial-gradient(circle at 80% 70%, rgba(255,200,150,0.25), rgba(255,200,150,0.0) 55%),
        linear-gradient(135deg, rgba(255,245,250,1), rgba(245,255,250,1))
        """,
        "decor": "🌸  🍂  ✨  🌸",
        "tagline": "살랑이는 계절감—레이어링까지 센스 있게 추천",
    }

def inject_global_css(theme: Dict[str, str]):
    st.markdown(
        f"""
<style>
.stApp {{
  background-image: {theme["bg"]};
  background-attachment: fixed;
}}
.ootd-hero {{
  padding: 20px 22px;
  border-radius: 18px;
  background: rgba(255,255,255,0.72);
  border: 1px solid rgba(255,255,255,0.55);
  box-shadow: 0 10px 30px rgba(0,0,0,0.05);
  margin-bottom: 16px;
}}
.ootd-hero h1 {{ margin: 0; font-size: 28px; }}
.ootd-hero .sub {{ margin-top: 6px; font-size: 14px; opacity: 0.8; }}
.ootd-hero .decor {{ margin-top: 10px; font-size: 18px; letter-spacing: 2px; opacity: 0.9; }}

.ootd-card {{
  padding: 14px 14px;
  border-radius: 16px;
  background: rgba(255,255,255,0.78);
  border: 1px solid rgba(255,255,255,0.55);
  box-shadow: 0 10px 24px rgba(0,0,0,0.04);
}}

div.stButton > button {{
  border-radius: 999px !important;
  padding: 12px 18px !important;
}}
.ootd-cta-wrap {{
  display: flex;
  justify-content: center;
  margin: 14px 0 8px 0;
}}
.ootd-cta-note {{
  text-align:center;
  font-size: 13px;
  opacity: 0.75;
  margin-top: 6px;
}}
</style>
        """,
        unsafe_allow_html=True,
    )


# ----------------------------
# Preset wardrobe generator (보완전략 2 핵심)
# ----------------------------
def color_palette_from_pref(pref: str) -> List[str]:
    if pref.startswith("무채"):
        return ["블랙", "화이트", "그레이"]
    if pref.startswith("톤다운"):
        return ["네이비", "베이지", "브라운", "그레이"]
    if pref.startswith("컬러포인트"):
        return ["블루", "그린", "레드", "네이비", "화이트"]
    return ["블랙", "화이트", "그레이", "네이비", "베이지"]

def formality_from_style(style: str) -> float:
    return {
        "미니멀": 0.6,
        "캐주얼": 0.3,
        "포멀": 0.85,
        "스트릿": 0.35,
        "러블리": 0.5,
        "스포티": 0.25,
        "클래식": 0.75,
    }.get(style, 0.5)

def tags_from_style(style: str) -> List[str]:
    base = [style]
    if style in ("포멀", "클래식"):
        base += ["단정", "오피스"]
    if style == "스포티":
        base += ["운동", "활동"]
    if style == "캐주얼":
        base += ["데일리"]
    if style == "미니멀":
        base += ["무채", "베이직"]
    if style == "러블리":
        base += ["데이트", "여리"]
    if style == "스트릿":
        base += ["힙", "레이어드"]
    return list(dict.fromkeys(base))

def preset_catalog(style: str, palette: List[str]) -> List[Dict[str, Any]]:
    """
    최소 구성: 상의 4, 하의 3, 아우터 2, 신발 2, 가방 1, 악세서리 1
    총 13개 정도(너무 많으면 부담이라 '빠른 시작' 느낌 유지)
    """
    f = formality_from_style(style)
    tags = tags_from_style(style)

    # pick colors deterministically
    def c(i: int) -> str:
        return palette[i % len(palette)]

    items = [
        # Tops
        {"category": "상의", "name": f"{c(0)} 베이직 티셔츠", "color": c(0), "warmth": 0.35, "formality": max(0.2, f - 0.15), "tags": tags + ["상의", "기본"]},
        {"category": "상의", "name": f"{c(1)} 셔츠/블라우스", "color": c(1), "warmth": 0.4, "formality": min(1.0, f + 0.1), "tags": tags + ["상의", "단정"]},
        {"category": "상의", "name": f"{c(2)} 니트/스웨터", "color": c(2), "warmth": 0.75, "formality": min(1.0, f + 0.05), "tags": tags + ["상의", "보온"]},
        {"category": "상의", "name": f"{c(3)} 맨투맨/후디", "color": c(3), "warmth": 0.65, "formality": max(0.15, f - 0.25), "tags": tags + ["상의", "캐주얼"]},

        # Bottoms
        {"category": "하의", "name": f"{c(0)} 데님 팬츠", "color": c(0), "warmth": 0.55, "formality": max(0.2, f - 0.1), "tags": tags + ["하의", "데일리"]},
        {"category": "하의", "name": f"{c(1)} 슬랙스/와이드 팬츠", "color": c(1), "warmth": 0.55, "formality": min(1.0, f + 0.15), "tags": tags + ["하의", "단정"]},
        {"category": "하의", "name": f"{c(2)} 스커트/쇼츠", "color": c(2), "warmth": 0.35, "formality": min(1.0, f + 0.05), "tags": tags + ["하의", "포인트"]},

        # Outer
        {"category": "아우터", "name": f"{c(0)} 자켓/블레이저", "color": c(0), "warmth": 0.55, "formality": min(1.0, f + 0.2), "tags": tags + ["아우터", "레이어드"]},
        {"category": "아우터", "name": f"{c(1)} 코트/패딩(계절용)", "color": c(1), "warmth": 0.9, "formality": min(1.0, f + 0.05), "tags": tags + ["아우터", "보온"]},

        # Shoes
        {"category": "신발", "name": f"{c(0)} 스니커즈", "color": c(0), "warmth": 0.35, "formality": max(0.15, f - 0.25), "tags": tags + ["신발", "데일리"]},
        {"category": "신발", "name": f"{c(1)} 로퍼/구두", "color": c(1), "warmth": 0.35, "formality": min(1.0, f + 0.2), "tags": tags + ["신발", "포멀"]},

        # Bag & accessory
        {"category": "가방", "name": f"{c(2)} 데일리 백", "color": c(2), "warmth": 0.2, "formality": min(1.0, f + 0.05), "tags": tags + ["가방"]},
        {"category": "악세서리", "name": f"{c(1)} 심플 악세서리", "color": c(1), "warmth": 0.2, "formality": min(1.0, f + 0.05), "tags": tags + ["악세서리", "심플"]},
    ]

    # Classic / Formal: reduce sporty hoodie vibe a bit
    if style in ("포멀", "클래식"):
        items[3]["name"] = f"{c(3)} 가디건/니트 가벼운 레이어"
        items[3]["formality"] = min(1.0, f + 0.05)
        items[3]["tags"] = tags + ["상의", "레이어드"]

    # Sporty: swap loafers to running shoes
    if style == "스포티":
        items[10]["name"] = f"{c(1)} 러닝화"
        items[10]["formality"] = 0.15
        items[10]["tags"] = tags + ["신발", "운동"]

    return items

def create_preset_wardrobe(db: Dict[str, Any], profile: Dict[str, Any]) -> None:
    """
    Generates preset wardrobe items and stores them in db with is_preset=True.
    """
    style = profile.get("style", "미니멀")
    color_pref = profile.get("color_pref", "무채(블랙/화이트/그레이)")
    palette = color_palette_from_pref(color_pref)
    items = preset_catalog(style, palette)

    # Insert preset items
    for it in items:
        item = {
            "id": new_id("preset"),
            "created_at": now_ts(),
            "name": it["name"],
            "image_path": None,
            "link": "",
            "category": it["category"],
            "color": it["color"],
            "length": "레귤러",
            "neckline": "기타",
            "tags": list(dict.fromkeys(it.get("tags", []) + ["프리셋"])),
            "warmth": float(it.get("warmth", 0.5)),
            "formality": float(it.get("formality", 0.5)),
            "is_preset": True,
        }
        db["items"].append(item)

    db["meta"]["onboarding_completed"] = True
    db["meta"]["onboarding_profile"] = profile

def delete_preset_items(db: Dict[str, Any]) -> None:
    db["items"] = [it for it in db.get("items", []) if not it.get("is_preset", False)]


# ----------------------------
# Outfit logic (rules + optional OpenAI)
# ----------------------------
def score_item_for_context(item: Dict[str, Any], ctx: Dict[str, Any]) -> float:
    score = 0.0
    cat = item.get("category", "")
    tags = set(item.get("tags", []) or [])
    warmth = float(item.get("warmth", 0.5))
    formality = float(item.get("formality", 0.5))

    season = ctx.get("season", "all")
    tpo = ctx.get("tpo", "기타")
    formality_need = float(ctx.get("formality_need", 0.5))
    precip = ctx.get("precip_prob")

    # TPO preferences
    if tpo in ("직장", "면접", "결혼식"):
        if cat in ("상의", "하의", "아우터", "신발", "원피스"):
            score += 0.6
        if "캐주얼" in tags:
            score -= 0.2
        if "포멀" in tags or "오피스" in tags:
            score += 0.2
    if tpo == "운동":
        if "운동" in tags or cat in ("신발", "상의", "하의"):
            score += 0.6
        if "포멀" in tags:
            score -= 0.2
    if tpo in ("여행", "데이트", "학교", "캐주얼 외출"):
        score += 0.2

    # Season/warmth
    if season == "winter":
        score += 0.8 * (warmth - 0.3)
    elif season == "summer":
        score += 0.8 * (0.7 - warmth)
    else:
        score += 0.3 * (0.6 - abs(warmth - 0.6))

    # Rain
    if precip is not None and precip >= 50:
        if "방수" in tags or "레인" in tags:
            score += 0.4
        if item.get("color") in ("블랙", "네이비", "그레이"):
            score += 0.1

    # Formality match
    score += 0.8 * (1.0 - abs(formality - formality_need))

    score += (hash(item.get("id", "")) % 17) / 200.0
    return score

def pick_best_items(db: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Optional[Dict[str, Any]]]:
    items = db.get("items", [])
    by_cat: Dict[str, List[Dict[str, Any]]] = {}
    for it in items:
        by_cat.setdefault(it.get("category", "기타"), []).append(it)

    def best(cat: str) -> Optional[Dict[str, Any]]:
        cands = by_cat.get(cat, [])
        if not cands:
            return None
        scored = sorted(cands, key=lambda x: score_item_for_context(x, ctx), reverse=True)
        return scored[0]

    outfit = {
        "아우터": best("아우터"),
        "상의": best("상의"),
        "하의": best("하의"),
        "원피스": best("원피스"),
        "신발": best("신발"),
        "가방": best("가방"),
        "악세서리": best("악세서리"),
    }

    # dress vs top+bottom heuristic
    top = outfit["상의"]
    bottom = outfit["하의"]
    dress = outfit["원피스"]
    if dress is not None:
        dress_score = score_item_for_context(dress, ctx)
        tb_score = 0.0
        if top is not None:
            tb_score += score_item_for_context(top, ctx)
        if bottom is not None:
            tb_score += score_item_for_context(bottom, ctx)
        if dress_score > (tb_score / 1.8):
            outfit["상의"] = None
            outfit["하의"] = None
    return outfit

def outfit_to_text(outfit: Dict[str, Optional[Dict[str, Any]]]) -> str:
    parts = []
    for cat in ["아우터", "상의", "하의", "원피스", "신발", "가방", "악세서리"]:
        it = outfit.get(cat)
        if it:
            mark = " (프리셋)" if it.get("is_preset") else ""
            parts.append(f"- {cat}: {it.get('name')} ({it.get('color','')}){mark}")
    return "\n".join(parts) if parts else "옷장에 아이템을 먼저 등록해줘!"

def reason_cards(ctx: Dict[str, Any]) -> Tuple[str, str, str]:
    w = []
    if ctx.get("temp_c") is not None:
        w.append(f"기온 {ctx['temp_c']}°C 기준으로 계절감 반영")
    if ctx.get("precip_prob") is not None:
        w.append(f"강수확률 {ctx['precip_prob']}% 고려")
    if ctx.get("weather_summary"):
        w.append(f"({ctx['weather_summary']})")
    weather_reason = " · ".join(w) if w else "날씨 정보가 없어서 기본 계절감으로 추천했어요."

    tpo = ctx.get("tpo", "기타")
    mood = ", ".join(ctx.get("mood", []) or [])
    formality = ctx.get("formality_need", 0.5)
    tpo_reason = f"상황(TPO)은 '{tpo}'로 설정 · 무드: {mood if mood else '기본'} · 포멀 선호 {formality:.2f}"

    body_shape = ctx.get("body_shape") or "미입력"
    note = (ctx.get("body_note") or "").strip()
    body_reason = f"골격: {body_shape}" + (f" · 메모: {note}" if note else " · 추가 체형 메모 없음")
    return weather_reason, tpo_reason, body_reason

def openai_recommendation(
    wardrobe_items: List[Dict[str, Any]],
    ctx: Dict[str, Any],
    model: str = "gpt-4o-mini",
) -> Optional[Dict[str, Any]]:
    if OpenAI is None:
        return None
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return None

    client = OpenAI(api_key=api_key)

    compact_items = []
    for it in wardrobe_items[:120]:
        compact_items.append({
            "name": it.get("name"),
            "category": it.get("category"),
            "color": it.get("color"),
            "tags": it.get("tags", []),
            "warmth": it.get("warmth", 0.5),
            "formality": it.get("formality", 0.5),
            "is_preset": it.get("is_preset", False),
        })

    prompt = {
        "role": "user",
        "content": (
            "너는 개인 스타일리스트야. 사용자의 옷장과 오늘의 조건(날씨/TPO/체형)을 보고 "
            "가장 적합한 코디 1세트를 추천해줘.\n\n"
            "요구사항:\n"
            "1) 카테고리 조합은 현실적으로(상의+하의 또는 원피스, 필요 시 아우터)\n"
            "2) 신발/가방/악세서리는 있으면 포함\n"
            "3) 추천 이유를 2~4문장으로 간단히\n"
            "4) 결과는 JSON으로만 반환\n\n"
            f"[조건]\n{json.dumps(ctx, ensure_ascii=False)}\n\n"
            f"[옷장]\n{json.dumps(compact_items, ensure_ascii=False)}\n\n"
            "반환 JSON 스키마:\n"
            "{"
            "\"outfit\": {\"아우터\": str|null, \"상의\": str|null, \"하의\": str|null, \"원피스\": str|null, \"신발\": str|null, \"가방\": str|null, \"악세서리\": str|null},"
            "\"reason\": str"
            "}"
        ),
    }

    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[prompt],
            temperature=0.6,
        )
        content = resp.choices[0].message.content or ""
        match = re.search(r"\{.*\}", content, flags=re.S)
        if not match:
            return None
        return json.loads(match.group(0))
    except Exception:
        return None


# ----------------------------
# Similar references (popular feed)
# ----------------------------
def bucket_temp(temp: float) -> int:
    return int(math.floor(temp / 5.0))

def bucket_precip(p: float) -> int:
    if p < 20: return 0
    if p < 50: return 1
    if p < 80: return 2
    return 3

def jaccard(a: List[str], b: List[str]) -> float:
    A, B = set(a or []), set(b or [])
    if not A and not B:
        return 1.0
    if not A or not B:
        return 0.0
    return len(A & B) / max(1, len(A | B))

def ctx_similarity(a: Dict[str, Any], b: Dict[str, Any]) -> float:
    score = 0.0
    w_sum = 0.0

    if a.get("temp_c") is not None and b.get("temp_c") is not None:
        ta, tb = bucket_temp(float(a["temp_c"])), bucket_temp(float(b["temp_c"]))
        score += (1.0 if ta == tb else 0.3 if abs(ta - tb) == 1 else 0.0) * 0.28
        w_sum += 0.28

    if a.get("precip_prob") is not None and b.get("precip_prob") is not None:
        pa, pb = bucket_precip(float(a["precip_prob"])), bucket_precip(float(b["precip_prob"]))
        score += (1.0 if pa == pb else 0.4 if abs(pa - pb) == 1 else 0.0) * 0.18
        w_sum += 0.18

    if a.get("tpo") and b.get("tpo"):
        score += (1.0 if a["tpo"] == b["tpo"] else 0.0) * 0.26
        w_sum += 0.26

    score += jaccard(a.get("mood", []), b.get("mood", [])) * 0.18
    w_sum += 0.18

    if a.get("formality_need") is not None and b.get("formality_need") is not None:
        fa, fb = float(a["formality_need"]), float(b["formality_need"])
        score += (1.0 - min(1.0, abs(fa - fb))) * 0.10
        w_sum += 0.10

    if w_sum <= 0:
        return 0.0
    return max(0.0, min(1.0, score / w_sum))

def trending_score(post: Dict[str, Any], likes: int) -> float:
    age_hr = max(1.0, (now_ts() - post.get("created_at", now_ts())) / 3600.0)
    return likes / math.sqrt(age_hr)

def get_similar_references(db: Dict[str, Any], ctx: Dict[str, Any], top_k: int = 3) -> List[Dict[str, Any]]:
    posts = db.get("posts", []) or []
    likes_map = db.get("likes", {}) or {}

    scored = []
    for p in posts:
        pctx = p.get("ctx", {}) or {}
        sim = ctx_similarity(ctx, pctx)
        likes = int(likes_map.get(p.get("id", ""), 0))
        trend = trending_score(p, likes)
        final = sim * 0.75 + (min(1.0, trend / 5.0)) * 0.25
        scored.append((final, sim, likes, p))

    scored.sort(key=lambda x: x[0], reverse=True)
    out = []
    for _, sim, likes, p in scored[:top_k]:
        cp = dict(p)
        cp["_sim"] = sim
        cp["_likes"] = likes
        out.append(cp)
    return out


# ----------------------------
# UI components
# ----------------------------
def item_card(it: Dict[str, Any]):
    cols = st.columns([1, 2])
    with cols[0]:
        if it.get("image_path") and os.path.exists(it["image_path"]):
            st.image(it["image_path"], use_container_width=True)
        else:
            st.write("🧥" if it.get("category") in ("아우터",) else "👗")
    with cols[1]:
        preset_badge = " · 프리셋" if it.get("is_preset") else ""
        st.subheader(it.get("name", "이름 없음"))
        st.caption(f"{it.get('category')}{preset_badge} · {it.get('color')} · {it.get('length')} · {it.get('neckline')}")
        tags = it.get("tags", [])
        if tags:
            st.write("태그:", ", ".join(tags))
        st.progress(float(it.get("warmth", 0.5)), text=f"보온감 {it.get('warmth', 0.5)}")
        st.progress(float(it.get("formality", 0.5)), text=f"포멀함 {it.get('formality', 0.5)}")

def post_card(post: Dict[str, Any], db: Dict[str, Any]):
    st.subheader(post.get("title", "코디"))
    st.caption(dt.datetime.fromtimestamp(post.get("created_at", now_ts())).strftime("%Y-%m-%d %H:%M"))

    outfit_text = post.get("outfit_text", "")
    if outfit_text:
        st.code(outfit_text, language="text")
    if post.get("caption"):
        st.write(post["caption"])

    likes = db.get("likes", {}).get(post["id"], 0)
    c1, c2, c3 = st.columns([1, 1.2, 5])
    with c1:
        if st.button(f"👍 {likes}", key=f"like_{post['id']}"):
            db["likes"][post["id"]] = likes + 1
            save_db(db)
            st.rerun()
    with c2:
        if post.get("_sim") is not None:
            st.caption(f"유사도 {post['_sim']:.2f}")
    with c3:
        st.write("")


# ----------------------------
# Streamlit App
# ----------------------------
st.set_page_config(page_title=APP_TITLE, page_icon="👗", layout="wide")
db = load_db()

# Session state init
if "main_view" not in st.session_state:
    st.session_state["main_view"] = "home"  # home | result
if "last_outfit" not in st.session_state:
    st.session_state["last_outfit"] = None

# Theme
temp_for_theme = None
if st.session_state.get("last_outfit") and st.session_state["last_outfit"].get("ctx"):
    temp_for_theme = st.session_state["last_outfit"]["ctx"].get("temp_c")
season = season_from_temp(float(temp_for_theme)) if temp_for_theme is not None else "mild"
theme = theme_for_season(season)
inject_global_css(theme)

# HERO
st.markdown(
    f"""
<div class="ootd-hero">
  <h1>{theme["title_emoji"]} {APP_TITLE}</h1>
  <div class="sub">{theme["tagline"]}</div>
  <div class="decor">{theme["decor"]}</div>
</div>
""",
    unsafe_allow_html=True,
)

tabs = st.tabs(["🏠 메인(추천)", "🗂️ 옷장 관리", "🔥 인기 코디 피드", "⚙️ 설정/데이터"])


# -------- Main Tab
with tabs[0]:
    # --- ONBOARDING (Preset Wardrobe) ---
    need_onboarding = (not db["meta"].get("onboarding_completed", False)) and (not has_any_items(db))
    if need_onboarding:
        st.markdown("### 🚀 빠른 시작 설정")
        st.info(
            "처음이라 옷장이 비어 있어요.\n\n"
            "아래 3~4개 질문만 답하면 **기본 옷장(프리셋)**을 자동으로 만들어서 "
            "**바로 코디 추천을 체험**할 수 있게 해줄게요!"
        )

        with st.form("onboarding_form"):
            style = st.selectbox("주로 선호하는 스타일", ONBOARD_STYLE, index=ONBOARD_STYLE.index("미니멀"))
            context = st.selectbox("주 활동 상황", ONBOARD_CONTEXT, index=ONBOARD_CONTEXT.index("학교"))
            color_pref = st.selectbox("선호 색감", ONBOARD_COLOR_PREF, index=0)
            wardrobe_size = st.selectbox("옷장 규모(대략)", ONBOARD_WARDROBE_SIZE, index=1)

            submitted = st.form_submit_button("✨ 기본 옷장 만들고 시작하기", type="primary")

        cskip1, cskip2 = st.columns([1, 1])
        with cskip1:
            if st.button("건너뛰기(직접 옷장 등록할래요)"):
                db["meta"]["onboarding_completed"] = True
                db["meta"]["onboarding_profile"] = {"skipped": True}
                save_db(db)
                st.success("좋아요! 옷장 관리 탭에서 바로 등록해줘.")
                st.rerun()
        with cskip2:
            st.caption("Tip: 프리셋은 나중에 옷장 탭에서 한 번에 삭제할 수 있어요.")

        if submitted:
            profile = {
                "style": style,
                "context": context,
                "color_pref": color_pref,
                "wardrobe_size": wardrobe_size,
            }
            create_preset_wardrobe(db, profile)
            save_db(db)
            st.success("기본 옷장을 만들었어! 이제 오코추로 바로 추천 받아봐 ✨")
            st.rerun()

        st.stop()  # 온보딩 완료 전에는 메인 추천 UI 아래로 내려가지 않음

    # --- MAIN FLOW: home/result ---
    view = st.session_state.get("main_view", "home")

    if view == "home":
        st.markdown("### 오늘의 조건을 입력하고, 오코추를 눌러줘 ✨")

        left, right = st.columns([1.15, 0.85], gap="large")

        with left:
            st.markdown('<div class="ootd-card">', unsafe_allow_html=True)

            st.markdown("#### 1) 날씨")
            use_auto_weather = st.toggle("날씨 자동 불러오기(Open-Meteo)", value=True)
            city = st.text_input("도시(예: Seoul, 서울)", value="Seoul")

            weather = None
            if use_auto_weather:
                weather = fetch_weather_open_meteo(city) if requests else None

            cA, cB, cC = st.columns(3)
            with cA:
                temp_c = st.number_input("기온(°C)", value=float(weather["temp_c"]) if weather and weather.get("temp_c") is not None else 18.0, step=1.0)
            with cB:
                precip_prob = st.number_input("강수확률(%)", value=float(weather["precip_prob"]) if weather and weather.get("precip_prob") is not None else 20.0, step=5.0, min_value=0.0, max_value=100.0)
            with cC:
                tpo = st.selectbox("상황(TPO)", DEFAULT_TPO, index=DEFAULT_TPO.index("학교") if "학교" in DEFAULT_TPO else 0)

            if weather and weather.get("summary"):
                st.info(f"자동 날씨: {weather['summary']}")

            st.markdown("#### 2) 체형 (선택)")
            cc1, cc2 = st.columns([1, 2])
            with cc1:
                body_shape = st.selectbox("골격", ["", "스트레이트", "웨이브", "내추럴"], index=0)
            with cc2:
                body_hint = st.text_input("추가 메모(예: 어깨 넓음, 허리 강조)", value="")

            st.markdown("#### 3) 무드/선호 (선택)")
            mood = st.multiselect("원하는 무드", DEFAULT_MOODS, default=["미니멀"])
            formality_need = st.slider("포멀함 선호도", 0.0, 1.0, 0.6, 0.05)

            st.markdown("#### 4) 추천 방식 (선택)")
            use_openai = st.toggle("OpenAI로 더 똑똑하게 추천", value=False, help="OPENAI_API_KEY가 설정되어 있어야 합니다.")
            model = st.text_input("OpenAI 모델", value="gpt-4o-mini")

            st.markdown("</div>", unsafe_allow_html=True)

            ctx = {
                "temp_c": float(temp_c),
                "precip_prob": float(precip_prob),
                "tpo": tpo,
                "body_shape": body_shape,
                "body_note": body_hint,
                "mood": mood,
                "formality_need": float(formality_need),
                "season": season_from_temp(float(temp_c)),
                "city": city,
                "weather_summary": weather.get("summary") if weather else None,
            }

            st.markdown('<div class="ootd-cta-wrap">', unsafe_allow_html=True)
            ccta1, ccta2, ccta3 = st.columns([1, 1.2, 1])
            with ccta2:
                go = st.button("✨ 오늘의 코디 추천 (오코추)", type="primary", use_container_width=True)
            st.markdown("</div>", unsafe_allow_html=True)
            st.markdown('<div class="ootd-cta-note">버튼 한 번이면 오늘의 OOTD가 완성돼요</div>', unsafe_allow_html=True)

            if go:
                wardrobe_items = db.get("items", [])
                if not wardrobe_items:
                    st.warning("옷장에 아이템이 없어요. 옷장 관리에서 등록해줘!")
                else:
                    rec = None
                    if use_openai:
                        rec = openai_recommendation(wardrobe_items, ctx, model=model)

                    if rec and isinstance(rec, dict) and "outfit" in rec:
                        outfit_obj = rec["outfit"]
                        reason = rec.get("reason", "")
                        outfit_text = "\n".join([f"- {k}: {v}" for k, v in outfit_obj.items() if v])
                        st.session_state["last_outfit"] = {
                            "id": new_id("outfit"),
                            "created_at": now_ts(),
                            "ctx": ctx,
                            "outfit_text": outfit_text,
                            "reason_text": reason,
                            "source": "openai",
                        }
                    else:
                        outfit = pick_best_items(db, ctx)
                        outfit_text = outfit_to_text(outfit)
                        w_r, t_r, b_r = reason_cards(ctx)
                        st.session_state["last_outfit"] = {
                            "id": new_id("outfit"),
                            "created_at": now_ts(),
                            "ctx": ctx,
                            "outfit": outfit,
                            "outfit_text": outfit_text,
                            "reason_text": "",
                            "reason_weather": w_r,
                            "reason_tpo": t_r,
                            "reason_body": b_r,
                            "source": "rules",
                        }

                    st.session_state["main_view"] = "result"
                    st.rerun()

        with right:
            st.markdown('<div class="ootd-card">', unsafe_allow_html=True)
            st.markdown("#### 👀 상태")
            st.metric("내 옷장 아이템 수", len(db.get("items", [])))
            st.metric("프리셋 아이템 수", sum(1 for it in db.get("items", []) if it.get("is_preset")))
            st.metric("피드 게시물 수", len(db.get("posts", [])))

            prof = db["meta"].get("onboarding_profile")
            if prof and not prof.get("skipped"):
                st.markdown("#### 🎛️ 내 프리셋 기준")
                st.caption(f"스타일: {prof.get('style')} · 상황: {prof.get('context')} · 색감: {prof.get('color_pref')}")
                st.caption("프리셋은 ‘추천 체험’용이에요. 실제 옷으로 바꾸면 추천이 더 정확해져요!")

            st.markdown("</div>", unsafe_allow_html=True)

    else:
        # Result view
        last = st.session_state.get("last_outfit")
        if not last:
            st.session_state["main_view"] = "home"
            st.rerun()

        ctx = last.get("ctx", {}) or {}
        st.markdown("### ✅ 오늘의 추천 OOTD")

        top_row = st.columns([1.1, 0.9])
        with top_row[0]:
            st.markdown('<div class="ootd-card">', unsafe_allow_html=True)
            st.markdown("#### 코디 구성")
            st.caption(f"추천 방식: {last.get('source')}")
            if ctx.get("weather_summary"):
                st.write(f"날씨: {ctx['weather_summary']}")
            st.code(last.get("outfit_text", ""), language="text")
            st.markdown("</div>", unsafe_allow_html=True)

        with top_row[1]:
            st.markdown('<div class="ootd-card">', unsafe_allow_html=True)
            st.markdown("#### 저장 / 공유")
            c1, c2 = st.columns(2)

            with c1:
                if st.button("💾 코디 저장", use_container_width=True):
                    db["outfits"].append(last)
                    save_db(db)
                    st.success("코디를 저장했어!")

            with c2:
                if st.button("📣 피드에 게시", use_container_width=True):
                    title = f"{ctx.get('tpo','오늘')} 코디"
                    if last.get("reason_text"):
                        caption = last["reason_text"]
                    else:
                        w_r, t_r, b_r = reason_cards(ctx)
                        caption = f"{w_r}\n{t_r}\n{b_r}"
                    post = {
                        "id": new_id("post"),
                        "created_at": now_ts(),
                        "title": title,
                        "caption": caption,
                        "outfit_text": last.get("outfit_text", ""),
                        "ctx": ctx,
                    }
                    db["posts"].insert(0, post)
                    db.setdefault("likes", {})[post["id"]] = 0
                    save_db(db)
                    st.success("피드에 게시했어! 🔥")
            if st.button("⬅️ 조건 다시 입력하기", use_container_width=True):
                st.session_state["main_view"] = "home"
                st.rerun()
            st.markdown("</div>", unsafe_allow_html=True)

        st.markdown("### 🧠 추천 이유")
        w_r, t_r, b_r = reason_cards(ctx)
        w_r = last.get("reason_weather", w_r)
        t_r = last.get("reason_tpo", t_r)
        b_r = last.get("reason_body", b_r)

        r1, r2, r3 = st.columns(3, gap="large")
        with r1:
            st.markdown('<div class="ootd-card">', unsafe_allow_html=True)
            st.markdown("#### 🌦️ 날씨")
            st.write(w_r)
            st.markdown("</div>", unsafe_allow_html=True)
        with r2:
            st.markdown('<div class="ootd-card">', unsafe_allow_html=True)
            st.markdown("#### 🎯 상황(TPO)")
            st.write(t_r)
            st.markdown("</div>", unsafe_allow_html=True)
        with r3:
            st.markdown('<div class="ootd-card">', unsafe_allow_html=True)
            st.markdown("#### 🧍 체형")
            st.write(b_r)
            st.markdown("</div>", unsafe_allow_html=True)

        st.markdown("### 🔥 유사 인기 코디 레퍼런스")
        refs = get_similar_references(db, ctx, top_k=3)
        if not refs:
            st.info("아직 피드 게시물이 없어요. 코디를 게시하면 유사 레퍼런스가 여기에 뜹니다!")
        else:
            for p in refs:
                with st.container(border=True):
                    post_card(p, db)


# -------- Wardrobe Tab
with tabs[1]:
    st.subheader("똑똑한 옷장 관리")

    # Preset controls
    st.markdown('<div class="ootd-card">', unsafe_allow_html=True)
    st.markdown("#### 프리셋(빠른 시작 옷장) 관리")
    preset_count = sum(1 for it in db.get("items", []) if it.get("is_preset"))
    if preset_count > 0:
        cA, cB = st.columns([1, 1])
        with cA:
            st.info(f"현재 프리셋 아이템 {preset_count}개가 있어요. (추천 체험용)")
        with cB:
            if st.button("🧹 프리셋 아이템 전체 삭제", use_container_width=True):
                delete_preset_items(db)
                save_db(db)
                st.success("프리셋 아이템을 삭제했어!")
                st.rerun()
    else:
        st.caption("프리셋 아이템이 없어요.")
    st.markdown("</div>", unsafe_allow_html=True)

    left, right = st.columns([1.1, 1], gap="large")

    with left:
        st.markdown('<div class="ootd-card">', unsafe_allow_html=True)
        st.markdown("#### 옷 등록(실제 옷)")
        with st.form("add_item", clear_on_submit=True):
            name = st.text_input("아이템 이름(예: 블랙 블레이저, 데님 팬츠)")
            uploaded = st.file_uploader("이미지 업로드(선택)", type=["png", "jpg", "jpeg", "webp"])
            link = st.text_input("구매 링크(선택)")

            c1, c2, c3, c4 = st.columns(4)
            with c1:
                warmth = st.slider("보온감", 0.0, 1.0, 0.5, 0.05)
            with c2:
                formality = st.slider("포멀함", 0.0, 1.0, 0.5, 0.05)
            with c3:
                category = st.selectbox("카테고리", DEFAULT_CATEGORIES, index=0)
            with c4:
                color = st.selectbox("색상", DEFAULT_COLORS, index=0)

            c5, c6 = st.columns(2)
            with c5:
                length = st.selectbox("기장", DEFAULT_LENGTHS, index=2)
            with c6:
                neckline = st.selectbox("넥라인", DEFAULT_NECKLINES, index=len(DEFAULT_NECKLINES) - 1)

            tags_text = st.text_input("태그(쉼표로 구분, 예: 미니멀, 포멀, 운동, 방수)")
            submitted = st.form_submit_button("➕ 등록", type="primary")

            if submitted:
                if not name.strip():
                    st.error("아이템 이름은 필수야!")
                else:
                    item_id = new_id("item")
                    image_path = None
                    if uploaded is not None:
                        img = Image.open(uploaded)
                        image_path = os.path.join(IMG_DIR, f"{item_id}.png")
                        img.save(image_path)

                    tags = [t.strip() for t in tags_text.split(",") if t.strip()]
                    item = {
                        "id": item_id,
                        "created_at": now_ts(),
                        "name": name.strip(),
                        "image_path": image_path,
                        "link": link.strip() if link else "",
                        "category": category,
                        "color": color,
                        "length": length,
                        "neckline": neckline,
                        "tags": list(dict.fromkeys(tags)),
                        "warmth": float(warmth),
                        "formality": float(formality),
                        "is_preset": False,
                    }
                    db["items"].insert(0, item)
                    save_db(db)
                    st.success("등록 완료!")
        st.markdown("</div>", unsafe_allow_html=True)

    with right:
        st.markdown('<div class="ootd-card">', unsafe_allow_html=True)
        st.markdown("#### 내 옷장")
        items = db.get("items", [])

        f1, f2, f3, f4 = st.columns(4)
        with f1:
            f_cat = st.selectbox("카테고리", ["전체"] + DEFAULT_CATEGORIES, index=0)
        with f2:
            f_color = st.selectbox("색상", ["전체"] + DEFAULT_COLORS, index=0)
        with f3:
            f_kind = st.selectbox("구분", ["전체", "실제 옷", "프리셋"], index=0)
        with f4:
            q = st.text_input("검색", value="")

        def match(it: Dict[str, Any]) -> bool:
            if f_cat != "전체" and it.get("category") != f_cat:
                return False
            if f_color != "전체" and it.get("color") != f_color:
                return False
            if f_kind == "실제 옷" and it.get("is_preset"):
                return False
            if f_kind == "프리셋" and not it.get("is_preset"):
                return False
            if q.strip():
                qq = q.strip().lower()
                if qq not in (it.get("name", "").lower()):
                    tags = " ".join(it.get("tags", [])).lower()
                    if qq not in tags:
                        return False
            return True

        filtered = [it for it in items if match(it)]
        st.caption(f"총 {len(filtered)}개 / 전체 {len(items)}개")

        for it in filtered[:80]:
            with st.container(border=True):
                item_card(it)
                cdel, cedit = st.columns([1, 3])
                with cdel:
                    # 프리셋도 개별 삭제 가능
                    if st.button("🗑️ 삭제", key=f"del_{it['id']}"):
                        if it.get("image_path") and os.path.exists(it["image_path"]):
                            try:
                                os.remove(it["image_path"])
                            except Exception:
                                pass
                        db["items"] = [x for x in db["items"] if x["id"] != it["id"]]
                        save_db(db)
                        st.rerun()
                with cedit:
                    st.caption("수정은 간단 버전: 삭제 후 다시 등록해줘!")
        st.markdown("</div>", unsafe_allow_html=True)


# -------- Feed Tab
with tabs[2]:
    st.subheader("인기 코디 피드 & 레퍼런스")
    posts = db.get("posts", [])
    if not posts:
        st.info("아직 게시물이 없어요. 메인에서 추천받은 코디를 '피드에 게시'해봐!")
    else:
        sort_mode = st.selectbox("정렬", ["최신순", "인기순(트렌딩)"], index=1)
        likes_map = db.get("likes", {}) or {}

        show = posts[:]
        if sort_mode.startswith("인기"):
            show = sorted(show, key=lambda p: trending_score(p, int(likes_map.get(p.get("id",""), 0))), reverse=True)

        for p in show[:60]:
            with st.container(border=True):
                post_card(p, db)


# -------- Settings/Data Tab
with tabs[3]:
    st.subheader("설정 / 데이터")

    st.markdown('<div class="ootd-card">', unsafe_allow_html=True)
    st.markdown("#### OpenAI 사용(선택)")
    st.write("환경변수 `OPENAI_API_KEY`가 설정되어 있으면 메인 탭에서 OpenAI 추천을 켤 수 있어요.")
    if OpenAI is None:
        st.warning("openai 패키지가 설치되어 있지 않아 OpenAI 추천 기능은 비활성입니다. `pip install openai`로 설치해줘.")
    else:
        st.success("openai 패키지 로드됨")
    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("---")

    st.markdown('<div class="ootd-card">', unsafe_allow_html=True)
    st.markdown("#### 온보딩 리셋(테스트용)")
    st.caption("처음 화면(프리셋 생성)부터 다시 테스트하고 싶을 때 사용해.")
    if st.button("🔁 온보딩 상태 초기화", use_container_width=True):
        db["meta"]["onboarding_completed"] = False
        db["meta"]["onboarding_profile"] = None
        # 프리셋도 함께 삭제하는 게 테스트에 편함
        delete_preset_items(db)
        save_db(db)
        st.success("초기화 완료. 메인 탭으로 가면 온보딩이 다시 뜹니다.")
        st.session_state["main_view"] = "home"
        st.session_state["last_outfit"] = None
        st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("---")

    st.markdown('<div class="ootd-card">', unsafe_allow_html=True)
    st.markdown("#### 데이터 내보내기/초기화")
    c1, c2 = st.columns(2)
    with c1:
        st.download_button(
            "⬇️ DB(JSON) 다운로드",
            data=json.dumps(db, ensure_ascii=False, indent=2).encode("utf-8"),
            file_name="ootd_db.json",
            mime="application/json",
        )
    with c2:
        if st.button("⚠️ 전체 데이터 초기화", type="secondary"):
            try:
                if os.path.exists(IMG_DIR):
                    for fn in os.listdir(IMG_DIR):
                        fp = os.path.join(IMG_DIR, fn)
                        try:
                            os.remove(fp)
                        except Exception:
                            pass
            except Exception:
                pass
            db = {
                "items": [],
                "outfits": [],
                "posts": [],
                "likes": {},
                "meta": {"reset_at": now_ts(), "onboarding_completed": False, "onboarding_profile": None},
            }
            save_db(db)
            st.success("초기화 완료. 새로 시작해봐!")
            st.session_state["main_view"] = "home"
            st.session_state["last_outfit"] = None
            st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)
