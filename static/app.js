const MAX_SEGMENT = 900;
const VIDEO_ID_RE = /^[A-Za-z0-9_-]{6,}$/;

const state = {
  video: null,
  start: 0,
  end: 1,
  exclusions: [],
  loading: false,
  processing: false,
  debounce: null,
};

const els = {
  url: document.querySelector("#urlInput"),
  urlError: document.querySelector("#urlError"),
  preview: document.querySelector("#preview"),
  thumbnail: document.querySelector("#thumbnail"),
  title: document.querySelector("#videoTitle"),
  duration: document.querySelector("#durationBadge"),
  startSlider: document.querySelector("#startSlider"),
  endSlider: document.querySelector("#endSlider"),
  track: document.querySelector("#rangeTrack"),
  startInput: document.querySelector("#startInput"),
  endInput: document.querySelector("#endInput"),
  excludeStartInput: document.querySelector("#excludeStartInput"),
  excludeEndInput: document.querySelector("#excludeEndInput"),
  addExclusion: document.querySelector("#addExclusionButton"),
  exclusionList: document.querySelector("#exclusionList"),
  exclusionSummary: document.querySelector("#exclusionSummary"),
  format: document.querySelector("#formatSelect"),
  quality: document.querySelector("#qualitySelect"),
  rangeError: document.querySelector("#rangeError"),
  extract: document.querySelector("#extractButton"),
  progressWrap: document.querySelector("#progressWrap"),
  progressBar: document.querySelector("#progressBar"),
  progressText: document.querySelector("#progressText"),
  download: document.querySelector("#downloadLink"),
  themeToggle: document.querySelector("#themeToggle"),
  themeMeta: document.querySelector('meta[name="theme-color"]'),
};

function preferredTheme() {
  const saved = window.localStorage.getItem("clipyt-theme");
  if (saved === "dark" || saved === "light") return saved;
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
  const isDark = theme === "dark";
  els.themeToggle.setAttribute("aria-pressed", String(isDark));
  els.themeToggle.setAttribute("aria-label", isDark ? "Cambiar a modo claro" : "Cambiar a modo oscuro");
  els.themeMeta.setAttribute("content", isDark ? "#111513" : "#f4f6f1");
}

function toggleTheme() {
  const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
  window.localStorage.setItem("clipyt-theme", next);
  applyTheme(next);
}

function toTime(seconds) {
  const safe = Math.max(0, Math.floor(Number(seconds) || 0));
  const h = String(Math.floor(safe / 3600)).padStart(2, "0");
  const m = String(Math.floor((safe % 3600) / 60)).padStart(2, "0");
  const s = String(safe % 60).padStart(2, "0");
  return `${h}:${m}:${s}`;
}

function fromTime(value) {
  const parts = String(value).trim().split(":").map((part) => Number(part));
  if (parts.some((part) => Number.isNaN(part) || part < 0)) return null;
  if (parts.length === 3) return parts[0] * 3600 + parts[1] * 60 + parts[2];
  if (parts.length === 2) return parts[0] * 60 + parts[1];
  if (parts.length === 1) return parts[0];
  return null;
}

function isYouTubeUrl(value) {
  try {
    const url = new URL(value);
    const host = url.hostname.replace(/^www\./, "").toLowerCase();
    const parts = url.pathname.split("/").filter(Boolean);
    let videoId = "";
    if (host === "youtu.be" && parts[0]) {
      videoId = parts[0];
    } else if (host === "youtube.com" || host === "m.youtube.com") {
      if (url.pathname === "/watch") videoId = url.searchParams.get("v") || "";
      if ((parts[0] === "shorts" || parts[0] === "embed") && parts[1]) videoId = parts[1];
    }
    return (url.protocol === "http:" || url.protocol === "https:") && VIDEO_ID_RE.test(videoId);
  } catch {
    return false;
  }
}

function clampRange() {
  if (!state.video) return;
  const duration = Math.max(1, state.video.duration);
  state.start = Math.max(0, Math.min(Math.floor(state.start), duration - 1));
  state.end = Math.max(state.start + 1, Math.min(Math.floor(state.end), duration));
  if (state.end - state.start > MAX_SEGMENT) {
    state.end = Math.min(duration, state.start + MAX_SEGMENT);
    if (state.end - state.start > MAX_SEGMENT) {
      state.start = Math.max(0, state.end - MAX_SEGMENT);
    }
  }
}

function normalizeExclusions() {
  if (!state.video) {
    state.exclusions = [];
    return;
  }
  const normalized = state.exclusions
    .map((exclusion) => ({
      start: Math.max(state.start, Math.min(Math.floor(exclusion.start), state.end)),
      end: Math.max(state.start, Math.min(Math.floor(exclusion.end), state.end)),
    }))
    .filter((exclusion) => exclusion.end > exclusion.start)
    .sort((a, b) => a.start - b.start || a.end - b.end);

  state.exclusions = normalized.reduce((merged, exclusion) => {
    const previous = merged.at(-1);
    if (previous && exclusion.start <= previous.end) {
      previous.end = Math.max(previous.end, exclusion.end);
    } else {
      merged.push({ ...exclusion });
    }
    return merged;
  }, []);
}

function finalDuration() {
  const removed = state.exclusions.reduce((total, exclusion) => total + exclusion.end - exclusion.start, 0);
  return Math.max(0, state.end - state.start - removed);
}

function setControlsEnabled(enabled) {
  const available = enabled && !state.processing;
  [
    els.startSlider,
    els.endSlider,
    els.startInput,
    els.endInput,
    els.excludeStartInput,
    els.excludeEndInput,
    els.addExclusion,
    els.format,
    els.quality,
  ].forEach((el) => {
    el.disabled = !available;
  });
}

function trackBackground(duration) {
  const stops = [`var(--line) 0 ${(state.start / duration) * 100}%`];
  let cursor = state.start;
  state.exclusions.forEach((exclusion) => {
    const start = (exclusion.start / duration) * 100;
    const end = (exclusion.end / duration) * 100;
    const cursorPercent = (cursor / duration) * 100;
    if (cursor < exclusion.start) {
      stops.push(`var(--accent) ${cursorPercent}% ${start}%`);
    }
    stops.push(`var(--removed) ${start}% ${end}%`);
    cursor = exclusion.end;
  });
  if (cursor < state.end) {
    stops.push(`var(--accent) ${(cursor / duration) * 100}% ${(state.end / duration) * 100}%`);
  }
  stops.push(`var(--line) ${(state.end / duration) * 100}% 100%`);
  return `linear-gradient(to right, ${stops.join(", ")})`;
}

function renderExclusions() {
  if (!state.video) {
    els.excludeStartInput.value = "00:00:00";
    els.excludeEndInput.value = "00:00:00";
    els.exclusionSummary.textContent = "Sin intervalos excluidos.";
    els.exclusionList.innerHTML = "";
    return;
  }

  const parsedStart = fromTime(els.excludeStartInput.value);
  const defaultStart = Math.min(state.end - 1, state.start);
  const inputStart =
    parsedStart === null || parsedStart < state.start || parsedStart >= state.end ? defaultStart : parsedStart;
  const parsedEnd = fromTime(els.excludeEndInput.value);
  const inputEnd =
    parsedEnd === null || parsedEnd <= inputStart || parsedEnd > state.end
      ? Math.min(state.end, inputStart + 5)
      : parsedEnd;
  els.excludeStartInput.value = toTime(inputStart);
  els.excludeEndInput.value = toTime(inputEnd);

  const duration = finalDuration();
  els.exclusionSummary.textContent = state.exclusions.length
    ? `Duración final aproximada: ${toTime(duration)}.`
    : `Sin intervalos excluidos. Duración final: ${toTime(duration)}.`;
  els.exclusionList.innerHTML = state.exclusions
    .map(
      (exclusion, index) => `
        <div class="exclusion-item">
          <span>${toTime(exclusion.start)} - ${toTime(exclusion.end)}</span>
          <button type="button" data-remove-exclusion="${index}" aria-label="Quitar intervalo ${toTime(exclusion.start)} a ${toTime(exclusion.end)}">Quitar</button>
        </div>
      `,
    )
    .join("");
}

function renderRange() {
  if (!state.video) {
    els.startInput.value = "00:00:00";
    els.endInput.value = "00:00:00";
    renderExclusions();
    els.extract.disabled = true;
    els.extract.textContent = "Extraer Clip";
    return;
  }
  clampRange();
  normalizeExclusions();
  const duration = Math.max(1, state.video.duration);
  els.startSlider.max = duration;
  els.endSlider.max = duration;
  els.startSlider.value = state.start;
  els.endSlider.value = state.end;
  els.startInput.value = toTime(state.start);
  els.endInput.value = toTime(state.end);

  els.track.style.background = trackBackground(duration);
  renderExclusions();

  const tooLong = state.end - state.start > MAX_SEGMENT;
  const emptyClip = finalDuration() <= 0;
  els.rangeError.textContent = tooLong
    ? "El fragmento no puede durar más de 15 minutos."
    : emptyClip
      ? "Los intervalos excluidos cubren todo el fragmento."
      : "";
  els.extract.disabled = state.processing || tooLong || emptyClip || !state.video || !els.quality.value;
  els.extract.textContent = state.processing ? "Extrayendo…" : "Extraer Clip";
}

function resetVideo(message = "") {
  state.video = null;
  state.start = 0;
  state.end = 1;
  state.exclusions = [];
  els.preview.hidden = true;
  els.thumbnail.removeAttribute("src");
  els.thumbnail.alt = "";
  els.quality.innerHTML = "";
  els.progressWrap.hidden = true;
  els.progressBar.style.width = "0%";
  els.progressBar.removeAttribute("aria-valuenow");
  els.progressText.textContent = "0%";
  els.download.hidden = true;
  setControlsEnabled(false);
  renderRange();
  els.urlError.textContent = message;
}

async function loadMetadata(url) {
  if (!isYouTubeUrl(url)) {
    resetVideo("Por favor, ingresa un enlace de YouTube válido.");
    return;
  }
  state.loading = true;
  resetVideo("Cargando información del video…");
  try {
    const response = await fetch("/api/metadata", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url }),
    });
    const payload = await response.json();
    if (!response.ok || !payload.ok) throw new Error(payload.error || "No se pudo cargar el video.");

    state.video = payload.video;
    state.start = 0;
    state.end = Math.min(MAX_SEGMENT, Math.max(1, state.video.duration));
    state.exclusions = [];
    els.excludeStartInput.value = toTime(state.start);
    els.excludeEndInput.value = toTime(Math.min(state.end, state.start + 5));
    els.thumbnail.src = state.video.thumbnail || "";
    els.thumbnail.alt = state.video.title ? `Miniatura de ${state.video.title}` : "Miniatura del video";
    els.title.textContent = state.video.title;
    els.duration.textContent = state.video.durationLabel;
    els.quality.innerHTML = state.video.qualities.map((quality) => `<option value="${quality}">${quality}p</option>`).join("");
    els.preview.hidden = false;
    els.urlError.textContent = "";
    setControlsEnabled(true);
    renderRange();
  } catch (error) {
    resetVideo(error.message || "El video es privado o la URL no es válida.");
  } finally {
    state.loading = false;
  }
}

function scheduleMetadataLoad() {
  window.clearTimeout(state.debounce);
  const url = els.url.value.trim();
  if (!url) {
    resetVideo("");
    return;
  }
  state.debounce = window.setTimeout(() => loadMetadata(url), 450);
}

function handleTimeInput(which) {
  const input = which === "start" ? els.startInput : els.endInput;
  const parsed = fromTime(input.value);
  if (parsed === null) {
    renderRange();
    return;
  }
  state[which] = parsed;
  renderRange();
}

function addExclusion() {
  if (!state.video || state.processing) return;
  const start = fromTime(els.excludeStartInput.value);
  const end = fromTime(els.excludeEndInput.value);
  if (start === null || end === null || end <= start) {
    els.rangeError.textContent = "El intervalo excluido necesita un inicio menor que su fin.";
    return;
  }
  if (start < state.start || end > state.end) {
    els.rangeError.textContent = "El intervalo excluido debe quedar dentro del rango principal.";
    return;
  }
  state.exclusions.push({ start, end });
  normalizeExclusions();
  const nextStart = Math.min(state.end - 1, end);
  els.excludeStartInput.value = toTime(nextStart);
  els.excludeEndInput.value = toTime(Math.min(state.end, nextStart + 5));
  renderRange();
}

function setProcessing(isProcessing) {
  state.processing = isProcessing;
  els.url.disabled = isProcessing;
  els.extract.setAttribute("aria-busy", String(isProcessing));
  setControlsEnabled(Boolean(state.video));
  renderRange();
}

function updateProgress(percent, message) {
  const safe = Math.max(0, Math.min(100, Number(percent) || 0));
  els.progressWrap.hidden = false;
  els.progressBar.style.width = `${safe}%`;
  els.progressBar.setAttribute("role", "progressbar");
  els.progressBar.setAttribute("aria-valuemin", "0");
  els.progressBar.setAttribute("aria-valuemax", "100");
  els.progressBar.setAttribute("aria-valuenow", String(safe));
  els.progressText.textContent = message ? `${safe}% · ${message}` : `${safe}%`;
}

async function pollJob(jobId) {
  const response = await fetch(`/api/jobs/${jobId}`);
  const job = await response.json();
  if (!response.ok || !job.ok) throw new Error(job.error || "No se pudo consultar el progreso.");
  updateProgress(job.progress, job.message);
  if (job.status === "done") {
    els.download.href = job.downloadUrl;
    els.download.download = job.filename || "";
    els.download.hidden = false;
    els.download.click();
    setProcessing(false);
    return;
  }
  if (job.status === "error") {
    throw new Error(job.error || "Ocurrió un error de procesamiento.");
  }
  window.setTimeout(() => pollJob(jobId).catch(handleProcessError), 900);
}

function handleProcessError(error) {
  els.rangeError.textContent = error.message || "Ocurrió un error de procesamiento.";
  setProcessing(false);
}

async function extractClip() {
  if (!state.video || state.processing) return;
  clampRange();
  renderRange();
  els.download.hidden = true;
  els.rangeError.textContent = "";
  updateProgress(0, "Preparando…");
  setProcessing(true);
  try {
    const response = await fetch("/api/extract", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        url: els.url.value.trim(),
        start: state.start,
        end: state.end,
        exclusions: state.exclusions,
        format: els.format.value,
        quality: Number(els.quality.value),
      }),
    });
    const payload = await response.json();
    if (!response.ok || !payload.ok) throw new Error(payload.error || "No se pudo iniciar la extracción.");
    pollJob(payload.jobId).catch(handleProcessError);
  } catch (error) {
    handleProcessError(error);
  }
}

els.url.addEventListener("input", scheduleMetadataLoad);
els.url.addEventListener("paste", () => window.setTimeout(scheduleMetadataLoad, 0));
els.startSlider.addEventListener("input", () => {
  state.start = Number(els.startSlider.value);
  renderRange();
});
els.endSlider.addEventListener("input", () => {
  state.end = Number(els.endSlider.value);
  renderRange();
});
els.startInput.addEventListener("blur", () => handleTimeInput("start"));
els.endInput.addEventListener("blur", () => handleTimeInput("end"));
els.startInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter") handleTimeInput("start");
});
els.endInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter") handleTimeInput("end");
});
els.addExclusion.addEventListener("click", addExclusion);
els.exclusionList.addEventListener("click", (event) => {
  const button = event.target.closest("[data-remove-exclusion]");
  if (!button || state.processing) return;
  state.exclusions.splice(Number(button.dataset.removeExclusion), 1);
  renderRange();
});
els.quality.addEventListener("change", renderRange);
els.format.addEventListener("change", renderRange);
els.extract.addEventListener("click", extractClip);
els.themeToggle.addEventListener("click", toggleTheme);

applyTheme(preferredTheme());
resetVideo("");
