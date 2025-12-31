const pages = {
  home: document.getElementById("page-home"),
  rules: document.getElementById("page-rules"),
  level: document.getElementById("page-level"),
  question: document.getElementById("page-question"),
};

function showPage(key) {
  Object.values(pages).forEach(p => p.classList.remove("active"));
  pages[key].classList.add("active");
}

const state = {
  session_id: null,
  relationship: "",
  level: "A",
  history: [],
};

const relationshipInput = document.getElementById("relationship");
const relationshipLabel = document.getElementById("relationship-label");
const badgeLevel = document.getElementById("badge-level");
const questionText = document.getElementById("question-text");

async function apiStart(relationship) {
  const res = await fetch("/api/start", {
    method: "POST",
    headers: {"Content-Type":"application/json"},
    body: JSON.stringify({relationship})
  });
  if (!res.ok) throw new Error("start failed");
  return res.json();
}

async function apiQuestion(level, action=null) {
  const res = await fetch("/api/question", {
    method: "POST",
    headers: {"Content-Type":"application/json"},
    body: JSON.stringify({
      session_id: state.session_id,
      level,
      action,
      history: state.history,
    })
  });
  if (!res.ok) throw new Error("question failed");
  return res.json();
}

async function loadNextQuestion(action=null) {
  badgeLevel.textContent = `LEVEL ${state.level}`;
  questionText.textContent = "（載入中…）";

  const data = await apiQuestion(state.level, action);
  badgeLevel.textContent = `LEVEL ${data.level}`;
  questionText.textContent = data.question;

  // 記錄題目（避免重複）
  state.history.push(data.question);
}

function bindEvents() {
  // Home -> Rules
  document.getElementById("btn-start").addEventListener("click", async () => {
    const rel = relationshipInput.value.trim();
    state.relationship = rel || "朋友";

    const {session_id} = await apiStart(state.relationship);
    state.session_id = session_id;

    relationshipLabel.textContent = state.relationship;
    showPage("rules");
  });

  // Rules navigation
  document.getElementById("btn-back-home").addEventListener("click", () => showPage("home"));
  document.getElementById("btn-to-level").addEventListener("click", () => {
    relationshipLabel.textContent = state.relationship;
    showPage("level");
  });

  // Level -> Question
  document.querySelectorAll(".wheel-btn").forEach(btn => {
    btn.addEventListener("click", async () => {
      state.level = btn.dataset.level;
      showPage("question");
      await loadNextQuestion();
    });
  });

  document.getElementById("btn-back-rules").addEventListener("click", () => showPage("rules"));
  document.getElementById("btn-to-level-2").addEventListener("click", () => showPage("level"));

  // Question actions -> next question
  document.getElementById("btn-skip").addEventListener("click", async () => {
    await loadNextQuestion("skip");
  });
  document.getElementById("btn-done").addEventListener("click", async () => {
    await loadNextQuestion("done");
  });
}

bindEvents();
showPage("home");
