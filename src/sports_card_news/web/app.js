const state = {
  health: null,
  activeJob: null,
  pollTimer: null,
};

const elements = {
  systemStatus: document.querySelector("#system-status"),
  editionDate: document.querySelector("#edition-date"),
  runLive: document.querySelector("#run-live"),
  runDemo: document.querySelector("#run-demo"),
  jobBox: document.querySelector("#job-box"),
  jobState: document.querySelector("#job-state"),
  jobPercent: document.querySelector("#job-percent"),
  jobMessage: document.querySelector("#job-message"),
  progressBar: document.querySelector("#progress-bar"),
  settingsForm: document.querySelector("#settings-form"),
  apiKey: document.querySelector("#api-key"),
  modelName: document.querySelector("#model-name"),
  saveSettings: document.querySelector("#save-settings"),
  formStatus: document.querySelector("#form-status"),
  editionGrid: document.querySelector("#edition-grid"),
  refreshEditions: document.querySelector("#refresh-editions"),
  dialog: document.querySelector("#edition-dialog"),
  dialogContent: document.querySelector("#dialog-content"),
  dialogClose: document.querySelector("#dialog-close"),
  toast: document.querySelector("#toast"),
};

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || `요청 실패 (${response.status})`);
  return data;
}

function seoulToday() {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: "Asia/Seoul", year: "numeric", month: "2-digit", day: "2-digit",
  }).formatToParts(new Date());
  const values = Object.fromEntries(parts.map((part) => [part.type, part.value]));
  return `${values.year}-${values.month}-${values.day}`;
}

async function loadHealth() {
  try {
    const health = await api("/api/health");
    state.health = health;
    elements.modelName.value = health.model;
    elements.systemStatus.classList.add("ready");
    elements.systemStatus.querySelector("strong").textContent = health.api_key_verified
      ? "API 연결 완료"
      : (health.api_key_configured ? "API 확인 필요" : "데모 실행 가능");
    elements.runLive.disabled = !health.api_key_verified || health.job_running;
    elements.runDemo.disabled = health.job_running;
    if (health.api_key_configured) {
      elements.apiKey.placeholder = "저장된 키 사용 중 · 새 키 입력 시 교체";
      if (health.api_key_verified) {
        setFormStatus("OpenAI 키가 로컬에 저장되었고 연결 확인을 통과했습니다.", "success");
      } else {
        setFormStatus("저장된 OpenAI 키의 연결 확인이 필요합니다. 새 키를 입력해 확인하세요.");
      }
    }
  } catch (error) {
    elements.systemStatus.querySelector("strong").textContent = "연결 오류";
    showToast(error.message);
  }
}

async function saveSettings(event) {
  event.preventDefault();
  elements.saveSettings.disabled = true;
  setFormStatus("키를 저장하고 연결을 확인하고 있습니다.");
  let saved = false;
  try {
    await api("/api/settings", {
      method: "POST",
      body: JSON.stringify({ api_key: elements.apiKey.value, model: elements.modelName.value }),
    });
    saved = true;
    elements.apiKey.value = "";
    const result = await api("/api/settings/test", { method: "POST" });
    setFormStatus(result.message, "success");
    showToast("OpenAI 연결이 완료되었습니다.");
    await loadHealth();
  } catch (error) {
    const prefix = saved ? "키는 저장했지만 연결 확인에 실패했습니다" : "저장하지 못했습니다";
    setFormStatus(`${prefix}: ${error.message}`, "error");
  } finally {
    elements.saveSettings.disabled = false;
  }
}

async function startJob(demo) {
  clearInterval(state.pollTimer);
  elements.runLive.disabled = true;
  elements.runDemo.disabled = true;
  updateJobUI({ status: "queued", message: "생성 작업을 등록하고 있습니다." });
  try {
    const job = await api("/api/jobs", {
      method: "POST",
      body: JSON.stringify({ edition_date: elements.editionDate.value, demo }),
    });
    state.activeJob = job.id;
    updateJobUI(job);
    state.pollTimer = setInterval(pollJob, 1500);
  } catch (error) {
    updateJobUI({ status: "failed", message: error.message, error: error.message });
    await loadHealth();
  }
}

async function pollJob() {
  if (!state.activeJob) return;
  try {
    const job = await api(`/api/jobs/${state.activeJob}`);
    updateJobUI(job);
    if (job.status === "completed" || job.status === "failed") {
      clearInterval(state.pollTimer);
      state.pollTimer = null;
      state.activeJob = null;
      await Promise.all([loadHealth(), loadEditions()]);
      if (job.status === "completed") {
        showToast(job.message);
        await openEdition(job.edition_date);
      }
    }
  } catch (error) {
    clearInterval(state.pollTimer);
    updateJobUI({ status: "failed", message: error.message, error: error.message });
  }
}

function updateJobUI(job) {
  const progress = { queued: 12, running: 58, completed: 100, failed: 100 }[job.status] || 0;
  const labels = { queued: "대기", running: "제작 중", completed: "완료", failed: "실패" };
  elements.jobBox.hidden = false;
  elements.jobState.textContent = labels[job.status] || "준비";
  elements.jobPercent.textContent = `${progress}%`;
  elements.progressBar.style.width = `${progress}%`;
  elements.progressBar.style.background = job.status === "failed" ? "var(--danger)" : "var(--acid)";
  elements.jobMessage.textContent = job.error || job.message;
}

async function loadEditions() {
  try {
    const data = await api("/api/editions");
    if (!data.items.length) {
      elements.editionGrid.innerHTML = '<p class="empty-state">아직 생성 기록이 없습니다. 데모 실행으로 전체 흐름을 확인해 보세요.</p>';
      return;
    }
    elements.editionGrid.innerHTML = data.items.map((item) => `
      <button class="edition-card" type="button" data-edition="${escapeHtml(item.edition_date)}">
        <img src="${escapeHtml(item.cover_url)}" alt="${escapeHtml(item.title)} 표지" loading="lazy" />
        <span class="edition-meta">
          <span class="edition-kicker"><span>${escapeHtml(item.sport)} · ${escapeHtml(item.league)}</span><span>${item.card_count} CARDS</span></span>
          <h3>${escapeHtml(item.title)}</h3>
          <p>${escapeHtml(item.edition_date)} · 사람 승인 대기</p>
        </span>
      </button>
    `).join("");
    elements.editionGrid.querySelectorAll("[data-edition]").forEach((button) => {
      button.addEventListener("click", () => openEdition(button.dataset.edition));
    });
  } catch (error) {
    elements.editionGrid.innerHTML = `<p class="empty-state">${escapeHtml(error.message)}</p>`;
  }
}

async function openEdition(editionDate) {
  try {
    const item = await api(`/api/editions/${encodeURIComponent(editionDate)}`);
    const gallery = item.cards.map((card) => `
      <img src="${escapeHtml(card.image_url)}" alt="${escapeHtml(card.alt_text)}" loading="lazy" />
    `).join("");
    const facts = item.facts.map((fact) => `
      <a href="${escapeHtml(fact.url)}" target="_blank" rel="noreferrer"><span>${escapeHtml(fact.id)}</span>${escapeHtml(fact.claim)}</a>
    `).join("");
    elements.dialogContent.innerHTML = `
      <div class="dialog-body">
        <p class="section-number">${escapeHtml(item.edition_date)} · ${escapeHtml(item.sport)} · ${escapeHtml(item.league)}</p>
        <h2>${escapeHtml(item.title)}</h2>
        <p>${escapeHtml(item.selection_reason)}</p>
        <div class="card-gallery">${gallery}</div>
        <h3>게시 캡션</h3>
        <div class="caption-box">${escapeHtml(item.caption)}\n\n${item.hashtags.map(escapeHtml).join(" ")}</div>
        <h3>연결된 원문</h3>
        <div class="fact-list">${facts}</div>
      </div>`;
    elements.dialog.showModal();
  } catch (error) {
    showToast(error.message);
  }
}

function setFormStatus(message, type = "") {
  elements.formStatus.textContent = message;
  elements.formStatus.className = `form-status ${type}`.trim();
}

function showToast(message) {
  elements.toast.textContent = message;
  elements.toast.hidden = false;
  window.setTimeout(() => { elements.toast.hidden = true; }, 3600);
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>'"]/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;",
  })[char]);
}

elements.settingsForm.addEventListener("submit", saveSettings);
elements.runLive.addEventListener("click", () => startJob(false));
elements.runDemo.addEventListener("click", () => startJob(true));
elements.refreshEditions.addEventListener("click", loadEditions);
elements.dialogClose.addEventListener("click", () => elements.dialog.close());
elements.dialog.addEventListener("click", (event) => {
  if (event.target === elements.dialog) elements.dialog.close();
});

elements.editionDate.value = seoulToday();
Promise.all([loadHealth(), loadEditions()]);
