import os
import json
import uuid
import time
import base64
from pathlib import Path

import streamlit as st
from PIL import Image

# ========== 기본 설정 ==========
APP_TITLE = "오늘 뭐 입지? (OOTD)"
DATA_DIR = ".data"
IMG_DIR = f"{DATA_DIR}/images"
DB_PATH = f"{DATA_DIR}/db.json"
ASSET_DIR = Path("assets")

DEFAULT_CATEGORIES = ["상의", "하의", "원피스", "아우터", "신발", "가방", "악세서리"]
DEFAULT_COLORS = ["블랙", "화이트", "그레이", "네이비", "베이지", "브라운", "기타"]
DEFAULT_LENGTHS = ["크롭", "숏", "레귤러", "롱", "기타"]
DEFAULT_NECKLINES = ["라운드", "브이넥", "셔츠카라", "터틀넥", "기타"]

# ========== 초기화 ==========
def ensure_dirs():
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(IMG_DIR, exist_ok=True)

def load_db():
    ensure_dirs()
    if not os.path.exists(DB_PATH):
        db = {
            "items": [],
            "meta": {"onboarding_done": False}
        }
        save_db(db)
        return db
    with open(DB_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

def save_db(db):
    with open(DB_PATH, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)

db = load_db()

# ========== 사이드바 (API 키) ==========
with st.sidebar:
    st.markdown("### 🔑 OpenAI API 키")
    api_key = st.text_input(
        "API Key",
        type="password",
        placeholder="sk-...",
    )
    if api_key:
        st.session_state["OPENAI_API_KEY"] = api_key
        st.success("API 키 설정 완료")

# ========== 계절 배경 ==========
def season_from_month():
    m = time.localtime().tm_mon
    if m in (12, 1, 2):
        return "winter"
    if m in (3, 4, 5):
        return "spring"
    if m in (6, 7, 8):
        return "summer"
    return "fall"

def bg_for_season(season):
    p = ASSET_DIR / f"bg_{season}.jpg"
    if not p.exists():
        return None
    data = base64.b64encode(p.read_bytes()).decode()
    return f"data:image/jpeg;base64,{data}"

season = season_from_month()
bg = bg_for_season(season)

st.set_page_config(page_title=APP_TITLE, layout="wide")

st.markdown(
    f"""
<style>
.stApp {{
  background-image:
    linear-gradient(rgba(255,255,255,0.75), rgba(255,255,255,0.75)),
    url("{bg}");
  background-size: cover;
}}
.card {{
  background: rgba(255,255,255,0.9);
  padding: 16px;
  border-radius: 16px;
  margin-bottom: 16px;
}}
</style>
""",
    unsafe_allow_html=True,
)

# ========== 제목 ==========
st.markdown(
    f"""
<div class="card">
  <h1>👗 {APP_TITLE}</h1>
  <p>계절에 맞춰 오늘의 코디를 추천해줄게요</p>
</div>
""",
    unsafe_allow_html=True,
)

# ========== 탭 ==========
tab1, tab2, tab3 = st.tabs(["🏠 추천", "🗂️ 옷장", "⚙️ 초기화"])

# ========== 탭 1: 추천 ==========
with tab1:
    if not db.get("meta", {}).get("onboarding_done", False):
        st.markdown("### 🚀 빠른 시작")
        if st.button("프리셋 옷장 생성"):
            db["items"] = [
                {"id": str(uuid.uuid4()), "name": "화이트 셔츠", "category": "상의", "color": "화이트"},
                {"id": str(uuid.uuid4()), "name": "블랙 슬랙스", "category": "하의", "color": "블랙"},
                {"id": str(uuid.uuid4()), "name": "블랙 로퍼", "category": "신발", "color": "블랙"},
            ]
            db["meta"]["onboarding_done"] = True
            save_db(db)
            st.success("프리셋 옷장 생성 완료")
            st.experimental_rerun()
    else:
        st.success("오늘의 코디 예시")
        for it in db["items"]:
            st.write(f"- {it['name']} ({it['category']})")

# ========== 탭 2: 옷장 ==========
with tab2:
    st.markdown("### ➕ 옷 등록")

    with st.form("add_item"):
        name = st.text_input("아이템 이름")
        category = st.selectbox("카테고리", DEFAULT_CATEGORIES)
        color = st.selectbox("색상", DEFAULT_COLORS)
        uploaded = st.file_uploader("이미지(선택)", type=["png", "jpg", "jpeg"])

        submitted = st.form_submit_button("등록")

        if submitted:
            if not name:
                st.error("이름은 필수입니다")
            else:
                item = {
                    "id": str(uuid.uuid4()),
                    "name": name,
                    "category": category,
                    "color": color,
                }
                if uploaded:
                    img = Image.open(uploaded)
                    path = f"{IMG_DIR}/{item['id']}.png"
                    img.save(path)
                    item["image"] = path
                db["items"].append(item)
                save_db(db)
                st.success("등록 완료")
                st.experimental_rerun()

    st.markdown("### 👕 내 옷장")
    for it in db["items"]:
        st.write(f"- {it['name']} ({it['category']} / {it['color']})")

# ========== 탭 3: 초기화 ==========
with tab3:
    if st.button("⚠️ 전체 초기화"):
        if os.path.exists(DB_PATH):
            os.remove(DB_PATH)
        if os.path.exists(IMG_DIR):
            for f in os.listdir(IMG_DIR):
                os.remove(os.path.join(IMG_DIR, f))
        st.success("초기화 완료. 새로고침하세요.")
