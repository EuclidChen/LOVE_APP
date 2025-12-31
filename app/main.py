from __future__ import annotations

import os
import random
from uuid import uuid4
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from openai import OpenAI


# =========================
# App & Paths (更穩的寫法)
# =========================
app = FastAPI(title="Deep Card Game")

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
def index():
    return FileResponse(str(STATIC_DIR / "index.html"))


# =========================
# In-memory session store
# =========================
SESSIONS: dict[str, dict] = {}


# =========================
# Models
# =========================
class StartRequest(BaseModel):
    relationship: str


class StartResponse(BaseModel):
    session_id: str


class QuestionRequest(BaseModel):
    session_id: str
    level: str  # "A" | "B" | "C" | "D"
    action: Optional[str] = None  # "skip" | "done" | None
    history: list[str] = []       # 前端送過來的題目歷史（有順序）


class QuestionResponse(BaseModel):
    level: str
    question: str


# =========================
# Fallback Question Bank (保險用)
# =========================
QUESTION_BANK = {
    "A": [
        "你最近一次大笑是因為什麼？",
        "你今天心情用 1~10 分會給幾分？",
        "如果要用一種飲料形容你現在的狀態，會是什麼？",
        "你最近在迷什麼歌/影片？",
        "你最常用的口頭禪是什麼？",
    ],
    "B": [
        "你覺得自己最加分的特質是什麼？為什麼？",
        "你遇到壓力時，通常會怎麼排解？",
        "你對『安全感』的定義是什麼？",
        "你覺得朋友之間最重要的是什麼？",
        "你曾經因為一件小事對某人改觀嗎？",
    ],
    "C": [
        "你人生中有哪個時刻讓你覺得『我長大了』？",
        "你最害怕被別人誤解成什麼樣子？",
        "你覺得自己最難開口求助的是什麼事？",
        "你曾經後悔沒說出口的一句話是什麼？",
        "你覺得你在關係裡最常扮演什麼角色？",
    ],
    "D": [
        "你最深的自我懷疑通常長什麼樣子？",
        "你曾經最脆弱的一段時間發生了什麼？你怎麼走過來的？",
        "你現在最想和過去的自己說一句什麼？",
        "你覺得『被愛』對你來說代表什麼？",
        "如果明天一切重來，你最想改變哪個選擇？",
    ],
}


LEVEL_STYLE = {
    "A": "破冰/暖身：超好答、短句、具體生活化。避免抽象大道理與逼問。",
    "B": "好接續的深入題：聊習慣/偏好/價值觀，務必給台階。多用二選一或請舉一個小例子。",
    "C": "更深入但不沉重：聊關係互動/內在想法/人生節奏，語氣自然像聊天，不要審問。",
    "D": "最深入但溫柔：可觸及脆弱/界線/遺憾/修復；允許不答或輕描淡寫，不逼問隱私與創傷細節。",
}



# =========================
# Helpers
# =========================
_client: Optional[OpenAI] = None


def get_client() -> OpenAI:
    """Lazy init：真的要打 API 才初始化，沒 key 就讓它在外層 fallback。"""
    global _client
    if _client is None:
        _client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
    return _client


def dedupe_preserve_order(items: list[str]) -> list[str]:
    """去重但保留順序（用於 history）。"""
    seen = set()
    out = []
    for x in items:
        if not x:
            continue
        if x in seen:
            continue
        seen.add(x)
        out.append(x)
    return out


def pick_question(level: str, context: str, used: set[str]) -> str:
    base_list = QUESTION_BANK.get(level, QUESTION_BANK["A"])
    candidates = [q for q in base_list if q not in used]
    if not candidates:
        return random.choice(base_list)  # 題庫用完就隨機，不要加前綴
    return random.choice(candidates)     # 不要加（relationship）



def ai_generate_question(level: str, context: str, recent_questions: list[str], mode: str = "normal") -> str:
    # 最近題目（有順序）
    recent = recent_questions[-12:]
    used_text = "\n".join([f"- {q}" for q in recent]) if recent else "（無）"

    level_style = LEVEL_STYLE.get(level, "輕鬆、具體、好回答。")

    system = (
        "你是卡牌對話遊戲的出題器。"
        "只輸出一題問題，不要前言、不要編號、不要解釋。"
        "使用繁體中文，語氣像朋友聊天，不像面試。"
        "避免性暗示、仇恨、歧視、暴力、個資。"
    )

    user = f"""
使用者輸入的關係/情境/主題（請依此出題）：{context}
題目等級：{level}
等級風格：{level_style}

請產生 1 題新的問題，並避免與下列題目重複或太相似：
{used_text}

規則：
- 只輸出一題、單行
- 20~60 字
- 以問號結尾
- 優先「具體好回答」：帶畫面/例子/二選一
- 若怕答不上來，可在同一行用（…）給一句小台階
""".strip()

    resp = get_client().responses.create(
        model="gpt-5-mini",
        input=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=0.9,
        max_output_tokens=80,
    )

    q = resp.output_text.strip().replace("\n", " ").strip()
    if not (q.endswith("？") or q.endswith("?")):
        q += "？"
    return q



# =========================
# APIs
# =========================
@app.post("/api/start", response_model=StartResponse)
def start_game(req: StartRequest):
    session_id = str(uuid4())
    context = (req.relationship or "").strip() or "朋友"
    SESSIONS[session_id] = {
        "context": context,
        "created_at": datetime.utcnow().isoformat(),
        "history": [],  # 這裡存有順序的題目歷史（AI 避免重複要靠它）
    }
    return StartResponse(session_id=session_id)


@app.post("/api/question", response_model=QuestionResponse)
def next_question(req: QuestionRequest):
    sess = SESSIONS.get(req.session_id)

    if not sess:
        context = "朋友"
        used = set(req.history or [])
    else:
        context = sess.get("context", "朋友")
        used = set(sess.get("history", [])) | set(req.history or [])

    level = (req.level or "A").upper()
    if level not in ("A", "B", "C", "D"):
        level = "A"

    try:
        if os.environ.get("OPENAI_API_KEY"):
            recent_questions = (sess.get("history", []) if sess else []) + (req.history or [])
            recent_questions = dedupe_preserve_order(recent_questions)
            q = ai_generate_question(level=level, context=context, recent_questions=recent_questions)
        else:
            q = pick_question(level, context, used)
    except Exception:
        q = pick_question(level, context, used)

    if sess:
        sess["history"].append(q)

    return QuestionResponse(level=level, question=q)

