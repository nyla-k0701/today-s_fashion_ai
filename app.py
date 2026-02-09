# app.py
# Streamlit prototype for "오늘 뭐 입지? OOTD" - wardrobe-based AI daily styling app
# Features:
# 1) Wardrobe: upload items, auto-tag scaffold, filter/search
# 2) OOTD recommendation: weather + TPO + body info -> outfit suggestion (rules-based / optional OpenAI)
# 3) Feed: post outfits, likes, trending

import os
import re
import json
import uuid
import math
import time
import datetime as dt
from dataclasses import dataclass, asdict
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

DEFAULT_CATEGORIES = [
    "상의", "하의", "원피스", "아우터", "신발", "양말", "악세서리", "가방"
]
DEFAULT_COLORS = ["블랙", "화이트", "그레이", "네이비", "베이지", "브라운", "레드", "블루", "그린", "옐로우", "핑크", "퍼플", "기타"]
DEFAULT_LENGTHS = ["크롭", "숏", "레귤러", "롱", "맥시", "기타"]
DEFAULT_NECKLINES = ["라운드", "브이넥", "셔츠카라", "터틀넥", "오프숄더", "기타"]
DEFAULT_TPO = ["학교", "직장", "결혼식", "운동", "여행", "데이트", "면접", "캐주얼 외출", "기타"]

# ----------------------------
# Storage helpers
# ----------------------------
def ensure_dirs():
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(IMG_DIR, exist_ok=True)

def load_db() -> Dict[str, Any]:
    ensure_dirs()
    if not os.path.exists(DB_PATH):
        db = {"items": [], "outfits": [], "posts": [], "likes": {}, "meta": {"created_at": time.time()}}
        save_db(db)
        return db
    with open(DB_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

def save_db(db: Dict[str, Any]) -> None:
    ensure_dirs()
    with open(DB_PATH, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)

def now_ts() -> float:
    return time.time()

def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"

# ----------------------------
# Simple tagger scaffold (rule-based)
# ----------------------------
def guess_tags_from_name(name: str) -> Dict[str, str]:
    """
    Very simple heuristic tagger based on item name text.
    In production, replace with image model / LLM.
    """
    n = (name or "").lower()

    # category guess
    cat_map = {
        "상의": ["티", "t", "셔츠", "블라우스", "니트", "맨투맨", "후드", "탑", "top"],
        "하의": ["바지", "팬츠", "청바지", "데님", "슬랙스", "스커트", "치마", "쇼츠", "반바지"],
        "원피스": ["원피스", "드레스", "dress"],
        "아우터": ["자켓", "재킷", "코트", "가디건", "패딩", "점퍼", "후리스", "블레이저"],
        "신발": ["신발", "스니커즈", "로퍼", "구두", "부츠", "샌들", "힐"],
        "악세서리": ["목걸이", "귀걸이", "반지", "팔찌", "시계", "모자", "캡"],
        "가방": ["가방", "백", "bag", "토트", "크로스", "백팩"],
        "양말": ["양말", "삭스", "socks"],
    }
    category = "기타"
    for c, kws in cat_map.items():
        if any(k in n for k in kws):
            category = c
            break
    if category == "기타":
        category = "상의"  # default fallback

    # color guess
    color_map = {
        "블랙": ["black", "검정", "블랙"],
        "화이트": ["white", "흰", "화이트"],
        "그레이": ["gray", "grey", "회색", "그레이"],
        "네이비": ["navy", "남색", "네이비"],
        "베이지": ["beige", "베이지"],
        "브라운": ["brown", "갈색", "브라운"],
        "레드": ["red", "빨강", "레드"],
        "블루": ["blue", "파랑", "블루"],
        "그린": ["green", "초록", "그린"],
        "옐로우": ["yellow", "노랑", "옐로우"],
        "핑크": ["pink", "핑크"],
        "퍼플": ["purple", "보라", "퍼플"],
    }
    color = "기타"
    for c, kws in color_map.items():
        if any(k in n for k in kws):
            color = c
            break

    # length / neckline are hard without metadata; default
    length = "레귤러"
    neckline = "기타"
    return {"category": category, "color": color, "length": length, "neckline": neckline}

# ----------------------------
# Weather helpers (optional Open-Meteo)
# ----------------------------
def fetch_weather_open_meteo(city: str) -> Optional[Dict[str, Any]]:
    """
    Uses Open-Meteo geocoding + forecast (if requests + internet available).
    Returns dict with temp_c, precipitation_prob, wind_kph, summary.
    """
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

        # lightweight "summary"
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
# Outfit logic (rules + optional OpenAI)
# ----------------------------
def season_from_temp(temp_c: Optional[float]) -> str:
    if temp_c is None:
        return "all"
    # rough bands
    if temp_c <= 5:
        return "winter"
    if temp_c <= 16:
        return "spring_fall"
    if temp_c <= 26:
        return "mild"
    return "summer"

def score_item_for_context(item: Dict[str, Any], ctx: Dict[str, Any]) -> float:
    """
    Score wardrobe item given context.
    item fields: category, color, tags, warmth, formality
    ctx: temp_c, precip_prob, tpo, formality_need, season
    """
    score = 0.0
    cat = item.get("category", "")
    tags = set(item.get("tags", []) or [])
    warmth = float(item.get("warmth", 0.5))
    formality = float(item.get("formality", 0.5))

    season = ctx.get("season", "all")
    tpo = ctx.get("tpo", "기타")
    formality_need = float(ctx.get("formality_need", 0.5))
    precip = ctx.get("precip_prob")

    # category baseline preference per tpo
    if tpo in ("직장", "면접", "결혼식"):
        if cat in ("상의", "하의", "아우터", "신발"):
            score += 0.6
        if "캐주얼" in tags:
            score -= 0.2
    if tpo in ("운동",):
        if "운동" in tags or cat in ("신발", "상의", "하의"):
            score += 0.6
    if tpo in ("여행", "데이트", "학교", "캐주얼 외출"):
        score += 0.2

    # season / warmth
    if season == "winter":
        score += 0.8 * (warmth - 0.3)
    elif season == "summer":
        score += 0.8 * (0.7 - warmth)
    else:
        score += 0.3 * (0.6 - abs(warmth - 0.6))

    # rain: prefer water-resistant / darker colors (simple)
    if precip is not None and precip >= 50:
        if "방수" in tags or "레인" in tags:
            score += 0.4
        if item.get("color") in ("블랙", "네이비", "그레이"):
            score += 0.1

    # formality match
    score += 0.8 * (1.0 - abs(formality - formality_need))

    # small randomness by stable hash
    score += (hash(item.get("id", "")) % 17) / 200.0
    return score

def pick_best_items(db: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Optional[Dict[str, Any]]]:
    items = db.get("items", [])
    # group by category
    by_cat: Dict[str, List[Dict[str, Any]]] = {}
    for it in items:
        by_cat.setdefault(it.get("category", "기타"), []).append(it)

    def best(cat: str) -> Optional[Dict[str, Any]]:
        cands = by_cat.get(cat, [])
        if not cands:
            return None
        scored = sorted(cands, key=lambda x: score_item_for_context(x, ctx), reverse=True)
        return scored[0]

    # basic outfit template
    outfit = {
        "상의": best("상의"),
        "하의": best("하의"),
        "원피스": best("원피스"),
        "아우터": best("아우터"),
        "신발": best("신발"),
        "악세서리": best("악세서리"),
        "가방": best("가방"),
    }

    # If a good dress exists and score higher than top+bottom, choose dress route
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
        if dress_score > (tb_score / 1.8):  # heuristic
            outfit["상의"] = None
            outfit["하의"] = None

    return outfit

def outfit_to_text(outfit: Dict[str, Optional[Dict[str, Any]]]) -> str:
    parts = []
    for cat in ["아우터", "상의", "하의", "원피스", "신발", "가방", "악세서리"]:
        it = outfit.get(cat)
        if it:
            parts.append(f"- {cat}: {it.get('name')} ({it.get('color','')})")
    return "\n".join(parts) if parts else "옷장에 아이템을 먼저 등록해줘!"

def build_reason(ctx: Dict[str, Any]) -> str:
    bits = []
    if ctx.get("temp_c") is not None:
        bits.append(f"기온 {ctx['temp_c']}°C 기준으로 계절감을 반영했어요.")
    if ctx.get("precip_prob") is not None:
        bits.append(f"강수확률 {ctx['precip_prob']}%를 고려했어요.")
    bits.append(f"TPO는 '{ctx.get('tpo','기타')}'로 설정했어요.")
    if ctx.get("body_shape"):
        bits.append(f"체형 정보({ctx.get('body_shape')})를 참고해 밸런스를 맞췄어요.")
    return " ".join(bits)

def openai_recommendation(
    wardrobe_items: List[Dict[str, Any]],
    ctx: Dict[str, Any],
    model: str = "gpt-4o-mini",
) -> Optional[Dict[str, Any]]:
    """
    Optional: Use OpenAI to generate a single outfit + explanation.
    Requires OPENAI_API_KEY and openai package.
    """
    if OpenAI is None:
        return None
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return None

    client = OpenAI(api_key=api_key)

    # Keep payload small
    compact_items = []
    for it in wardrobe_items[:120]:
        compact_items.append({
            "name": it.get("name"),
            "category": it.get("category"),
            "color": it.get("color"),
            "tags": it.get("tags", []),
            "warmth": it.get("warmth", 0.5),
            "formality": it.get("formality", 0.5),
        })

    prompt = {
        "role": "user",
        "content": (
            "너는 개인 스타일리스트야. 사용자의 옷장과 오늘의 조건(날씨/TPO/체형)을 보고 "
            "가장 적합한 코디 1세트를 추천해줘.\n\n"
            "요구사항:\n"
            "1) 카테고리 조합은 현실적으로(상의+하의 또는 원피스, 필요 시 아우터)\n"
            "2) 신발/가방/악세서리는 있으면 포함\n"
            "3) 추천 이유를 2~4문장으로 간단히 설명\n"
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
        # try to parse JSON
        match = re.search(r"\{.*\}", content, flags=re.S)
        if not match:
            return None
        data = json.loads(match.group(0))
        return data
    except Exception:
        return None

# ----------------------------
# UI helpers
# ----------------------------
def item_card(it: Dict[str, Any]):
    cols = st.columns([1, 2])
    with cols[0]:
        if it.get("image_path") and os.path.exists(it["image_path"]):
            st.image(it["image_path"], use_container_width=True)
        else:
            st.write("🧥")
    with cols[1]:
        st.subheader(it.get("name", "이름 없음"))
        st.caption(f"{it.get('category')} · {it.get('color')} · {it.get('length')} · {it.get('neckline')}")
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
    c1, c2 = st.columns([1, 5])
    with c1:
        if st.button(f"👍 {likes}", key=f"like_{post['id']}"):
            db["likes"][post["id"]] = likes + 1
            save_db(db)
            st.rerun()
    with c2:
        st.write("")

# ----------------------------
# Streamlit App
# ----------------------------
st.set_page_config(page_title=APP_TITLE, page_icon="👗", layout="wide")

db = load_db()

st.title(f"👗 {APP_TITLE}")
st.caption("내 옷장 기반으로 날씨·TPO·체형까지 반영해서 오늘의 코디를 추천하는 프로토타입")

tabs = st.tabs(["🏠 메인(추천)", "🗂️ 옷장 관리", "🔥 인기 코디 피드", "⚙️ 설정/데이터"])

# -------- Main Tab
with tabs[0]:
    st.subheader("오늘의 코디 추천 (오코추)")

    left, right = st.columns([1.2, 1])

    with left:
        st.markdown("#### 1) 오늘 조건 입력")
        use_auto_weather = st.toggle("날씨 자동 불러오기(Open-Meteo)", value=True, help="인터넷 연결이 되면 도시 기준 현재 날씨를 가져옵니다.")
        city = st.text_input("도시(예: Seoul, Seoul Korea, 서울)", value="Seoul")

        weather = None
        if use_auto_weather:
            weather = fetch_weather_open_meteo(city) if requests else None

        st.markdown("**날씨(수동 입력 가능)**")
        cA, cB, cC = st.columns(3)
        with cA:
            temp_c = st.number_input("기온(°C)", value=float(weather["temp_c"]) if weather and weather.get("temp_c") is not None else 18.0, step=1.0)
        with cB:
            precip_prob = st.number_input("강수확률(%)", value=float(weather["precip_prob"]) if weather and weather.get("precip_prob") is not None else 20.0, step=5.0, min_value=0.0, max_value=100.0)
        with cC:
            tpo = st.selectbox("TPO", DEFAULT_TPO, index=DEFAULT_TPO.index("학교") if "학교" in DEFAULT_TPO else 0)

        st.markdown("#### 2) 체형 정보(선택)")
        body_shape = st.selectbox("골격", ["", "스트레이트", "웨이브", "내추럴"], index=0)
        body_hint = st.text_input("추가 체형 메모(예: 어깨 넓음, 허리 라인 강조 등)", value="")

        st.markdown("#### 3) 톤/무드(선택)")
        mood = st.multiselect("원하는 무드", ["미니멀", "캐주얼", "포멀", "스트릿", "러블리", "스포티", "클래식"], default=["미니멀"])
        formality_need = st.slider("포멀함 선호도", 0.0, 1.0, 0.6, 0.05)

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

        if weather and weather.get("summary"):
            st.info(f"자동 날씨: {weather['summary']}")

        st.divider()

        use_openai = st.toggle("OpenAI로 더 똑똑하게 추천(선택)", value=False, help="OPENAI_API_KEY가 설정되어 있어야 합니다.")
        model = st.text_input("OpenAI 모델(선택)", value="gpt-4o-mini")

        if st.button("✨ 오늘의 코디 추천 받기", type="primary"):
            wardrobe_items = db.get("items", [])

            if not wardrobe_items:
                st.warning("옷장에 아이템이 없어요. 먼저 '옷장 관리'에서 옷을 등록해줘!")
            else:
                rec = None
                if use_openai:
                    rec = openai_recommendation(wardrobe_items, ctx, model=model)

                if rec and isinstance(rec, dict) and "outfit" in rec:
                    # LLM produced outfit names; show as text
                    outfit_obj = rec["outfit"]
                    reason = rec.get("reason", "")
                    outfit_text = "\n".join([f"- {k}: {v}" for k, v in outfit_obj.items() if v])
                    st.session_state["last_outfit"] = {
                        "id": new_id("outfit"),
                        "created_at": now_ts(),
                        "ctx": ctx,
                        "outfit_text": outfit_text,
                        "reason": reason,
                        "source": "openai",
                    }
                else:
                    # fallback: rule-based pick from wardrobe
                    outfit = pick_best_items(db, ctx)
                    outfit_text = outfit_to_text(outfit)
                    st.session_state["last_outfit"] = {
                        "id": new_id("outfit"),
                        "created_at": now_ts(),
                        "ctx": ctx,
                        "outfit": outfit,
                        "outfit_text": outfit_text,
                        "reason": build_reason(ctx),
                        "source": "rules",
                    }

                st.success("추천 완료! 오른쪽에서 확인해봐 👀")

    with right:
        st.markdown("#### 추천 결과")
        last = st.session_state.get("last_outfit")
        if not last:
            st.info("왼쪽에서 조건을 입력하고 추천을 눌러줘!")
        else:
            st.caption(f"추천 방식: {last.get('source')}")
            if last["ctx"].get("weather_summary"):
                st.write(f"날씨: {last['ctx']['weather_summary']}")
            st.code(last.get("outfit_text", ""), language="text")
            st.write("**추천 이유**")
            st.write(last.get("reason", ""))

            st.divider()
            st.markdown("#### 저장 / 피드 게시")
            colS1, colS2 = st.columns(2)

            with colS1:
                if st.button("💾 코디 저장"):
                    db["outfits"].append(last)
                    save_db(db)
                    st.success("코디를 저장했어!")
            with colS2:
                if st.button("📣 피드에 게시"):
                    title = f"{last['ctx'].get('tpo','오늘')} 코디"
                    caption = f"{', '.join(last['ctx'].get('mood', []) or [])} 무드로 골랐어요. {last['reason']}"
                    post = {
                        "id": new_id("post"),
                        "created_at": now_ts(),
                        "title": title,
                        "caption": caption,
                        "outfit_text": last.get("outfit_text", ""),
                        "ctx": last.get("ctx", {}),
                    }
                    db["posts"].insert(0, post)
                    db.setdefault("likes", {})[post["id"]] = 0
                    save_db(db)
                    st.success("피드에 게시했어! 🔥")

# -------- Wardrobe Tab
with tabs[1]:
    st.subheader("똑똑한 옷장 관리")

    left, right = st.columns([1.1, 1])

    with left:
        st.markdown("#### 옷 등록")
        with st.form("add_item", clear_on_submit=True):
            name = st.text_input("아이템 이름(예: 블랙 블레이저, 데님 팬츠)")
            uploaded = st.file_uploader("이미지 업로드(선택)", type=["png", "jpg", "jpeg", "webp"])
            link = st.text_input("구매 링크(선택)")
            auto = st.checkbox("이름 기반 자동 태깅(간단)", value=True)

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

            tags_text = st.text_input("태그(쉼표로 구분, 예: 미니멀, 포멀, 방수)")
            submitted = st.form_submit_button("➕ 등록", type="primary")

            if submitted:
                if not name.strip():
                    st.error("아이템 이름은 필수야!")
                else:
                    item_id = new_id("item")
                    image_path = None
                    if uploaded is not None:
                        img = Image.open(uploaded)
                        # save to disk
                        image_path = os.path.join(IMG_DIR, f"{item_id}.png")
                        img.save(image_path)

                    inferred = guess_tags_from_name(name) if auto else {}
                    # If user selected category/color manually, keep them; otherwise use inferred
                    final_category = category or inferred.get("category", "상의")
                    final_color = color or inferred.get("color", "기타")
                    final_length = length or inferred.get("length", "레귤러")
                    final_neckline = neckline or inferred.get("neckline", "기타")

                    tags = [t.strip() for t in tags_text.split(",") if t.strip()]
                    # sprinkle inferred lightweight tags
                    if auto:
                        if inferred.get("category") and inferred["category"] not in DEFAULT_CATEGORIES:
                            tags.append(inferred["category"])
                    tags = sorted(list(dict.fromkeys(tags)))  # unique preserve order

                    item = {
                        "id": item_id,
                        "created_at": now_ts(),
                        "name": name.strip(),
                        "image_path": image_path,
                        "link": link.strip() if link else "",
                        "category": final_category,
                        "color": final_color,
                        "length": final_length,
                        "neckline": final_neckline,
                        "tags": tags,
                        "warmth": float(warmth),
                        "formality": float(formality),
                    }
                    db["items"].insert(0, item)
                    save_db(db)
                    st.success("등록 완료!")

    with right:
        st.markdown("#### 내 옷장")
        items = db.get("items", [])

        # Filters
        f1, f2, f3 = st.columns(3)
        with f1:
            f_cat = st.selectbox("카테고리 필터", ["전체"] + DEFAULT_CATEGORIES, index=0)
        with f2:
            f_color = st.selectbox("색상 필터", ["전체"] + DEFAULT_COLORS, index=0)
        with f3:
            q = st.text_input("검색(이름/태그)", value="")

        def match(it: Dict[str, Any]) -> bool:
            if f_cat != "전체" and it.get("category") != f_cat:
                return False
            if f_color != "전체" and it.get("color") != f_color:
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

        for it in filtered[:60]:
            with st.container(border=True):
                item_card(it)
                cdel, cedit = st.columns([1, 3])
                with cdel:
                    if st.button("🗑️ 삭제", key=f"del_{it['id']}"):
                        # remove image file
                        if it.get("image_path") and os.path.exists(it["image_path"]):
                            try:
                                os.remove(it["image_path"])
                            except Exception:
                                pass
                        db["items"] = [x for x in db["items"] if x["id"] != it["id"]]
                        save_db(db)
                        st.rerun()
                with cedit:
                    st.caption("수정은 프로토타입에선 간단히: 삭제 후 다시 등록해줘!")

# -------- Feed Tab
with tabs[2]:
    st.subheader("인기 코디 피드 & 레퍼런스")

    posts = db.get("posts", [])
    if not posts:
        st.info("아직 게시물이 없어요. 메인에서 추천받은 코디를 '피드에 게시'해봐!")
    else:
        # Basic trending sort: likes desc + recency
        def trend_score(p: Dict[str, Any]) -> float:
            likes = db.get("likes", {}).get(p["id"], 0)
            age_hr = max(1.0, (now_ts() - p.get("created_at", now_ts())) / 3600.0)
            return likes / math.sqrt(age_hr)

        sort_mode = st.selectbox("정렬", ["최신순", "인기순(트렌딩)"], index=1)
        show = posts[:]
        if sort_mode.startswith("인기"):
            show = sorted(show, key=trend_score, reverse=True)

        for p in show[:40]:
            with st.container(border=True):
                post_card(p, db)

# -------- Settings/Data Tab
with tabs[3]:
    st.subheader("설정 / 데이터")
    st.markdown("#### OpenAI 사용(선택)")
    st.write("환경변수 `OPENAI_API_KEY`가 설정되어 있으면 메인 탭에서 OpenAI 추천을 켤 수 있어요.")
    if OpenAI is None:
        st.warning("openai 패키지가 설치되어 있지 않아 OpenAI 추천 기능은 비활성입니다. `pip install openai`로 설치해줘.")
    else:
        st.success("openai 패키지 로드됨")

    st.divider()
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
            # Remove images
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
            db = {"items": [], "outfits": [], "posts": [], "likes": {}, "meta": {"reset_at": now_ts()}}
            save_db(db)
            st.success("초기화 완료. 새로 시작해봐!")
            st.rerun()

    st.divider()
    st.markdown("#### 프로토타입 체크리스트")
    st.write(
        "- [x] 내 옷장 등록(이미지/링크)\n"
        "- [x] 자동 분류/태깅 스캐폴딩(이름 기반)\n"
        "- [x] 날씨 + TPO + 체형 입력\n"
        "- [x] 코디 추천(룰 기반 / OpenAI 선택)\n"
        "- [x] 코디 저장 및 피드 게시\n"
        "- [x] 좋아요 기반 트렌딩\n"
        "\n"
        "다음 단계(확장 아이디어):\n"
        "- 의류 이미지 분석(카테고리/색상/패턴/소재) 모델 연결\n"
        "- 유저 코디 유사도(임베딩)로 레퍼런스 추천 고도화\n"
        "- 코디 캡션/해시태그 자동생성\n"
        "- 아이템 수정 UI, 다중 사용자/로그인\n"
    )
