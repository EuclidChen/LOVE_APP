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
    mode: Optional[str] = "normal"
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

LEVEL_DESC = {
    "A": "破冰、輕鬆、可快速回答，句子短一點。",
    "B": "稍微深入，聊到生活習慣、價值觀、小故事。",
    "C": "更深入，聊到情緒、關係模式、重要轉折。",
    "D": "最深入但不冒犯，聊到脆弱面、界線、人生觀與修復。",
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


def pick_question(level: str, relationship: str, used: set[str]) -> str:
    base_list = QUESTION_BANK.get(level, QUESTION_BANK["A"])
    candidates = [q for q in base_list if q not in used]
    if not candidates:
        return f"（加碼題）以「{relationship}」為前提：{random.choice(base_list)}"
    q = random.choice(candidates)
    return f"（{relationship}）{q}"


def ai_generate_question(level: str, relationship: str, recent_questions: list[str], mode: str) -> str:
    # 最近題目（有順序），只取最後 12 題避免 prompt 太長
    recent = recent_questions[-12:]
    used_text = "\n".join([f"- {q}" for q in recent]) if recent else "（無）"
    mode = (mode or "normal").lower()
    mode_hint = "正式、溫和、有界線、不逼問。" if mode == "normal" else "酒局氛圍、更直接更敢問、可以更好笑一點，但仍尊重界線不冒犯。"
    system = (
        "你是一個卡牌對話遊戲的出題器。"
        "你只能輸出『一題問題』，不要加任何前言、不要編號、不要解釋。"
        "問題必須是繁體中文，且符合指定的深度等級。"
        "問題要適合兩個人面對面互動，不要太長。"
        "避免性暗示、仇恨、歧視、暴力、個資、犯罪教唆。"
        "如果題目可能讓人不舒服，請改成更溫和、尊重界線的問法。"
    )

    user = f"""
遊戲者關係：{relationship}
題目等級：{level}（{LEVEL_DESC.get(level, "")}）
模式：{mode_hint}

請產生 1 題新的問題，並且避免與以下題目重複或太相似：
{used_text}

限制：
- 20~60 字左右（不要太短也不要太長）
- 以問號結尾
- 只輸出問題本身
""".strip()

    resp = get_client().responses.create(
        model="gpt-4.1-mini",
        input=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=0.9,
        max_output_tokens=90,
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
    SESSIONS[session_id] = {
        "relationship": (req.relationship or "").strip() or "朋友",
        "created_at": datetime.utcnow().isoformat(),
        "history": [],  # 這裡存有順序的題目歷史（AI 避免重複要靠它）
    }
    return StartResponse(session_id=session_id)


@app.post("/api/question", response_model=QuestionResponse)
def next_question(req: QuestionRequest):
    sess = SESSIONS.get(req.session_id)

    # 取得關係
    relationship = (sess["relationship"] if sess else "朋友")

    # 整合「有順序」的歷史：後端 session history + 前端 history（都保留順序，然後去重）
    sess_history = sess.get("history", []) if sess else []
    merged_history = dedupe_preserve_order(sess_history + (req.history or []))

    # level 正規化
    level = (req.level or "A").upper()
    if level not in ("A", "B", "C", "D"):
        level = "A"

    # 先準備 used set 給 fallback 題庫用（快速排除重複）
    used_set = set(merged_history)

    # AI 出題（有 key 就走 AI，沒 key 或出錯就 fallback）
    try:
        if os.environ.get("OPENAI_API_KEY"):
            q = ai_generate_question(level, relationship, merged_history, req.mode or "normal")
        else:
            q = pick_question(level, relationship, used_set)
    except Exception as e:
        # 你需要 debug 時可以把這行打開看錯誤：
        # print("AI error:", repr(e))
        q = pick_question(level, relationship, used_set)

    # 記錄到 session（保留順序）
    if sess:
        sess["history"].append(q)

    return QuestionResponse(level=level, question=q)
