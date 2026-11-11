const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const DRAFT_STORAGE_KEY = "markdown-to-handwrite-draft-v1";
const SCAN_SESSION_KEY = "markdown-to-handwrite-scan-session-v1";
const PRESET_NAMES = { formal: "纸间清风体", personal_v6: "游丝细行体", anjingchen: "行云映墨体", shaohua: "平方韶华体", caveat: "Caveat", kalam: "Kalam" };
const SAMPLE_PAGE_COUNT = 3;
const MAX_SCAN_FILE_BYTES = 18 * 1024 * 1024;
const RED_LINED_PAPER = "background/提取的红线纸.png";
const GREEN_LINED_PAPER = "background/提取的绿线纸.png";

const state = {
  csrfToken: "",
  module: "text",
  defaults: null,
  config: null,
  sections: [],
  presets: {},
  selectedPreset: "formal",
  paperLayoutVersion: 1,
  assets: { fonts: [], backgrounds: [] },
  pages: [],
  exportPages: [],
  jobId: null,
  edits: [],
  savedEdits: [],
  editHistory: [],
  activeTool: "comment",
  draftMark: null,
  pendingCommentPoint: null,
  commentWidth: 0.028,
  commentDrag: null,
  commentImages: [],
  editing: false,
  editSaveQueued: false,
  files: { pdf: null, docx: null },
  outputFormat: "image",
  page: 0,
  zoom: 1.06,
  rendering: false,
  renderStartedAt: 0,
  renderTimer: null,
  toastTimer: null,
  draftTimer: null,
  importWarnings: [],
  renderWarnings: [],
  scanPages: [],
  scanPage: 0,
  scanZoom: 1,
  scanMode: "smart",
  scanOrientation: "auto",
  scanFormat: "jpg",
  scanProcessing: false,
  scanCropEditing: false,
  scanRestoreEditing: false,
  draftScanCrop: null,
};

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

function persistScanSession() {
  try {
    const pages = state.scanPages.map(({filterPreviews, filterPreviewKey, restoring, ...page}) => page);
    localStorage.setItem(SCAN_SESSION_KEY, JSON.stringify({
      pages, page: state.scanPage, mode: state.scanMode,
      orientation: state.scanOrientation, format: state.scanFormat,
    }));
  } catch { /* Keep the active session usable when browser storage is full. */ }
}

function restoreScanSession() {
  try {
    const saved = JSON.parse(localStorage.getItem(SCAN_SESSION_KEY) || "null");
    if (!saved || !Array.isArray(saved.pages)) return;
    state.scanPages = saved.pages.filter(page => page && /^[0-9a-f]{16}$/.test(page.scanId) && typeof page.url === "string")
      .slice(0, 30).map(page => ({...page, restoring: false, filterPreviewKey: null, filterPreviews: {}}));
    state.scanPage = Math.max(0, Math.min(state.scanPages.length - 1, Number.isInteger(saved.page) ? saved.page : 0));
    for (const [key, selector, dataKey] of [
      ["mode", "[data-scan-mode]", "scanMode"],
      ["orientation", "[data-scan-orientation]", "scanOrientation"],
      ["format", "[data-scan-format]", "scanFormat"],
    ]) {
      const buttons = $$(selector);
      if (!buttons.some(button => button.dataset[dataKey] === saved[key] && button.dataset.unavailable !== "true")) continue;
      state[dataKey] = saved[key];
      buttons.forEach(button => {
        const active = button.dataset[dataKey] === saved[key];
        button.classList.toggle("active", active);
        button.setAttribute("aria-pressed", String(active));
      });
    }
  } catch { /* Ignore a damaged local session. */ }
}

function readDraft() {
  try {
    const draft = JSON.parse(localStorage.getItem(DRAFT_STORAGE_KEY) || "null");
    return draft && typeof draft.markdown === "string" ? draft : null;
  } catch {
    return null;
  }
}

function persistDraft() {
  if (!state.config) return false;
  try {
    localStorage.setItem(DRAFT_STORAGE_KEY, JSON.stringify({
      markdown: $("#markdown-editor").value,
      config: state.config,
      preset: state.selectedPreset,
      presetVersion: 2,
      anjingchenFormulaVersion: 3,
      anjingchenTableInkVersion: 1,
      caveatTableInkVersion: 1,
      caveatMathInkVersion: 2,
      caveatCorrectionVersion: 1,
      paperLayoutVersion: state.paperLayoutVersion,
      savedAt: Date.now(),
    }));
    return true;
  } catch {
    return false;
  }
}

function saveDraftNow() {
  if (state.draftTimer) clearTimeout(state.draftTimer);
  state.draftTimer = null;
  const saved = persistDraft();
  $("#save-state").textContent = saved ? "草稿已自动保存" : "本地草稿保存失败";
  $("#save-state").style.color = saved ? "var(--sage-deep)" : "var(--accent)";
}

function scheduleDraftSave() {
  if (state.draftTimer) clearTimeout(state.draftTimer);
  state.draftTimer = setTimeout(saveDraftNow, 450);
}

function getPath(object, path) {
  return path.split(".").reduce((current, key) => current?.[key], object);
}

function setPath(object, path, value) {
  const parts = path.split(".");
  const leaf = parts.pop();
  const parent = parts.reduce((current, key) => current[key], object);
  parent[leaf] = value;
}

function mergeDeep(target, source) {
  if (!source || typeof source !== "object" || Array.isArray(source)) return target;
  Object.entries(source).forEach(([key, value]) => {
    if (value && typeof value === "object" && !Array.isArray(value) && target[key]) {
      mergeDeep(target[key], value);
    } else if (key in target) {
      target[key] = value;
    }
  });
  return target;
}

function formatNumber(value, step) {
  if (value === null || value === undefined) return "自动";
  const decimals = String(step).includes(".") ? String(step).split(".")[1].length : 0;
  return Number(value).toFixed(Math.min(decimals, 3)).replace(/\.0+$/, "").replace(/(\.\d*?)0+$/, "$1");
}

function updateRangePaint(input) {
  const min = Number(input.min);
  const max = Number(input.max);
  const value = Number(input.value);
  const progress = max === min ? 0 : ((value - min) / (max - min)) * 100;
  input.style.setProperty("--range-progress", `${Math.max(0, Math.min(100, progress))}%`);
}

function fieldShell(meta) {
  const field = document.createElement("div");
  field.className = "config-field";
  field.dataset.search = `${meta.label} ${meta.help || ""} ${meta.path}`.toLowerCase();
  field.dataset.path = meta.path;
  return field;
}

function addFieldHelp(field, meta) {
  if (!meta.help) return;
  const help = document.createElement("p");
  help.className = "field-help";
  help.textContent = meta.help;
  field.append(help);
}

function createRangeControl(meta, nullable = false) {
  const field = fieldShell(meta);
  const currentValue = getPath(state.config, meta.path);
  let workingValue = currentValue ?? Math.max(meta.min, Math.min(meta.max, getPath(state.defaults, meta.path) ?? meta.min));
  const preserveInteger = Number.isInteger(getPath(state.defaults, meta.path)) && Number.isInteger(meta.step);

  const head = document.createElement("div");
  head.className = "field-head";
  const label = document.createElement("label");
  label.className = "field-label";
  label.textContent = meta.label;
  const display = document.createElement("span");
  display.className = "field-value";
  display.textContent = currentValue === null ? "自动" : `${formatNumber(currentValue, meta.step)}${meta.unit || ""}`;
  head.append(label, display);

  const row = document.createElement("div");
  row.className = "range-row";
  const range = document.createElement("input");
  range.type = "range";
  range.min = meta.min;
  range.max = meta.max;
  range.step = meta.step;
  range.value = workingValue;
  range.id = `field-${meta.path.replaceAll(".", "-")}`;
  label.htmlFor = range.id;

  const numberWrap = document.createElement("div");
  numberWrap.className = "number-wrap";
  const number = document.createElement("input");
  number.type = "number";
  number.min = meta.min;
  number.max = meta.max;
  number.step = meta.step;
  number.value = workingValue;
  number.setAttribute("aria-label", `${meta.label}精确值`);
  const unit = document.createElement("span");
  unit.textContent = meta.unit || "";
  numberWrap.append(number, unit);
  row.append(range, numberWrap);

  const commit = (rawValue) => {
    let value = Number(rawValue);
    if (!Number.isFinite(value)) return;
    value = Math.max(meta.min, Math.min(meta.max, value));
    if (preserveInteger) value = Math.round(value);
    workingValue = value;
    setPath(state.config, meta.path, value);
    range.value = value;
    number.value = value;
    display.textContent = `${formatNumber(value, meta.step)}${meta.unit || ""}`;
    updateRangePaint(range);
    markChanged();
  };
  range.addEventListener("input", () => commit(range.value));
  number.addEventListener("change", () => commit(number.value));
  updateRangePaint(range);

  field.append(head, row);
  if (nullable) {
    const autoRow = document.createElement("div");
    autoRow.className = "auto-row";
    const autoLabel = document.createElement("label");
    autoLabel.className = "auto-check";
    const auto = document.createElement("input");
    auto.type = "checkbox";
    auto.checked = currentValue === null;
    autoLabel.append(auto, document.createTextNode("自动计算"));
    autoRow.append(autoLabel);
    const syncAuto = () => {
      const isAuto = auto.checked;
      range.disabled = isAuto;
      number.disabled = isAuto;
      setPath(state.config, meta.path, isAuto ? null : Number(workingValue));
      display.textContent = isAuto ? "自动" : `${formatNumber(workingValue, meta.step)}${meta.unit || ""}`;
      markChanged();
    };
    auto.addEventListener("change", syncAuto);
    range.disabled = auto.checked;
    number.disabled = auto.checked;
    field.append(autoRow);
  }
  addFieldHelp(field, meta);
  return field;
}

function createToggleControl(meta) {
  const field = fieldShell(meta);
  const row = document.createElement("div");
  row.className = "toggle-row";
  const copy = document.createElement("div");
  const label = document.createElement("label");
  label.className = "field-label";
  label.textContent = meta.label;
  copy.append(label);
  if (meta.help) {
    const help = document.createElement("p");
    help.className = "field-help";
    help.textContent = meta.help;
    copy.append(help);
  }
  const switchLabel = document.createElement("label");
  switchLabel.className = "switch";
  const input = document.createElement("input");
  input.type = "checkbox";
  input.checked = Boolean(getPath(state.config, meta.path));
  input.id = `field-${meta.path.replaceAll(".", "-")}`;
  label.htmlFor = input.id;
  const track = document.createElement("span");
  track.className = "switch-track";
  switchLabel.append(input, track);
  input.addEventListener("change", () => {
    setPath(state.config, meta.path, input.checked);
    markChanged();
  });
  row.append(copy, switchLabel);
  field.append(row);
  return field;
}

function createSelectControl(meta) {
  const field = fieldShell(meta);
  const label = document.createElement("label");
  label.className = "field-label";
  label.textContent = meta.label;
  const select = document.createElement("select");
  select.className = "select-control";
  select.id = `field-${meta.path.replaceAll(".", "-")}`;
  label.htmlFor = select.id;
  meta.options.forEach((option) => {
    const element = document.createElement("option");
    element.value = option.value;
    element.textContent = option.label;
    select.append(element);
  });
  select.value = getPath(state.config, meta.path);
  select.addEventListener("change", () => {
    setPath(state.config, meta.path, select.value);
    if (meta.path === "background.style" && select.value !== "image") {
      setPath(state.config, "background.image", null);
      const imageInput = document.querySelector("#field-background-image");
      if (imageInput) imageInput.value = "";
    }
    markChanged();
  });
  field.append(label, select);
  addFieldHelp(field, meta);
  return field;
}

function createColorControl(meta) {
  const field = fieldShell(meta);
  const label = document.createElement("label");
  label.className = "field-label";
  label.textContent = meta.label;
  const row = document.createElement("div");
  row.className = "color-row";
  const picker = document.createElement("input");
  picker.type = "color";
  picker.value = getPath(state.config, meta.path);
  picker.setAttribute("aria-label", `${meta.label}选择器`);
  const text = document.createElement("input");
  text.type = "text";
  text.value = getPath(state.config, meta.path);
  text.setAttribute("aria-label", `${meta.label}色值`);
  picker.addEventListener("input", () => {
    text.value = picker.value;
    setPath(state.config, meta.path, picker.value);
    markChanged();
  });
  text.addEventListener("change", () => {
    if (/^#[0-9a-f]{6}$/i.test(text.value)) picker.value = text.value;
    setPath(state.config, meta.path, text.value.trim());
    markChanged();
  });
  row.append(picker, text);
  field.append(label, row);
  addFieldHelp(field, meta);
  return field;
}

function createTextControl(meta) {
  const field = fieldShell(meta);
  const label = document.createElement("label");
  label.className = "field-label";
  label.textContent = meta.label;
  const input = document.createElement("input");
  input.className = "text-control";
  input.type = "text";
  input.value = getPath(state.config, meta.path) ?? "";
  input.placeholder = meta.control === "font-path" ? "选择字体文件或输入路径" : meta.control === "background-path" ? "选择背景文件或输入路径" : "";
  input.id = `field-${meta.path.replaceAll(".", "-")}`;
  label.htmlFor = input.id;
  if (meta.control === "font-path" || meta.control === "background-path") {
    const list = document.createElement("datalist");
    list.id = `${input.id}-options`;
    const assets = meta.control === "font-path" ? state.assets.fonts : state.assets.backgrounds;
    assets.forEach((asset) => {
      const option = document.createElement("option");
      option.value = asset.value;
      option.label = asset.label;
      list.append(option);
    });
    input.setAttribute("list", list.id);
    field.append(label, input, list);
  } else {
    field.append(label, input);
  }
  input.addEventListener("change", () => {
    const value = input.value.trim();
    setPath(state.config, meta.path, value === "" && meta.path !== "handwriting.seed" ? null : value);
    if (meta.path === "background.image" && value) {
      setPath(state.config, "background.style", "image");
      const styleSelect = document.querySelector("#field-background-style");
      if (styleSelect) styleSelect.value = "image";
    }
    markChanged();
  });
  addFieldHelp(field, meta);
  return field;
}

function createField(meta) {
  if (meta.control === "range") return createRangeControl(meta);
  if (meta.control === "nullable-range") return createRangeControl(meta, true);
  if (meta.control === "toggle") return createToggleControl(meta);
  if (meta.control === "select") return createSelectControl(meta);
  if (meta.control === "color") return createColorControl(meta);
  return createTextControl(meta);
}

function renderConfigSections() {
  const container = $("#config-sections");
  container.replaceChildren();
  let fieldCount = 0;
  const quickPaths = new Set([
    "background.style",
    "handwriting.correction_probability",
    "handwriting.position_disorder",
  ]);
  state.sections.forEach((section, index) => {
    const card = document.createElement("details");
    card.className = "config-card";
    card.dataset.sectionSearch = `${section.title} ${section.description} ${section.eyebrow}`.toLowerCase();
    card.open = false;
    const summary = document.createElement("summary");
    const sectionIndex = document.createElement("span");
    sectionIndex.className = "section-index";
    sectionIndex.textContent = String(index + 1).padStart(2, "0");
    const name = document.createElement("span");
    name.className = "section-name";
    const title = document.createElement("strong");
    title.textContent = section.title;
    const description = document.createElement("small");
    description.textContent = section.description;
    name.append(title, description);
    const count = document.createElement("span");
    count.className = "section-count";
    count.textContent = `${section.fields.length} 项`;
    summary.append(sectionIndex, name, count);
    const fields = document.createElement("div");
    fields.className = "config-fields";
    section.fields.filter((meta) => !quickPaths.has(meta.path)).forEach((meta) => fields.append(createField(meta)));
    fieldCount += fields.children.length;
    card.append(summary, fields);
    container.append(card);
  });
  $("#field-count").textContent = `${fieldCount} 项参数`;
  applyConfigSearch();
  updateSummary();
}

function renderQuickControls() {
  const container = $("#quick-controls");
  container.replaceChildren();
  const quickPaths = [
    "handwriting.correction_probability",
    "handwriting.position_disorder",
  ];
  quickPaths.forEach((path) => {
    const meta = state.sections.flatMap((section) => section.fields).find((field) => field.path === path);
    if (meta) container.append(createField(meta));
  });
  syncPaperOptions();
}

function syncPaperOptions() {
  const background = state.config.background;
  const isRedLined = background.style === "image" && background.image === RED_LINED_PAPER;
  const isGreenLined = background.style === "image" && background.image === GREEN_LINED_PAPER;
  const activeStyle = isRedLined ? "lined" : isGreenLined ? "green" : background.style;
  document.body.dataset.paperStyle = activeStyle;
  if (isRedLined) $("#empty-paper").style.backgroundImage = 'url("/paper/red-lined.png")';
  if (isGreenLined) $("#empty-paper").style.backgroundImage = 'url("/paper/green-lined.png")';
  $$("[data-paper-style]").forEach((button) => {
    const selected = button.dataset.paperStyle === activeStyle;
    button.classList.toggle("active", selected);
    button.setAttribute("aria-pressed", String(selected));
  });
}

function configurePaperStyle(style) {
  const background = state.config.background;
  if ((style === "lined" || style === "green" || style === "dot") && !state.paperLayoutVersion) {
    if (state.config.page.margin_top_mm > 30) state.config.page.margin_top_mm = 22;
    state.paperLayoutVersion = 1;
  }
  if (style === "dot") style = "green";
  background.style = style === "lined" || style === "green" ? "image" : style;
  background.image = style === "lined" ? RED_LINED_PAPER : style === "green" ? GREEN_LINED_PAPER : null;
  background.paper_color = style === "lined" ? "#fffdf4" : "#ffffff";
  background.line_color = style === "lined" ? "#d7e4ef" : style === "dot" ? "#b4c5d3" : "#cedce9";
  background.draw_margin_line = style === "lined";
  if (style === "dot") background.dot_radius_px = Math.max(1, Math.min(6, Math.round(3 * state.config.page.dpi / 300)));
}

function resetConfiguration() {
  state.config = clone(state.defaults);
  state.selectedPreset = null;
  renderConfigSections();
  renderQuickControls();
  markChanged();
  showToast("参数已恢复", "已恢复默认设置，点击“开始转换”应用更改。");
}

function applyConfigSearch() {
  const query = $("#config-search").value.trim().toLowerCase();
  let visibleSections = 0;
  $$(".config-card").forEach((card) => {
    let visibleFields = 0;
    $$(".config-field", card).forEach((field) => {
      const visible = !query || field.dataset.search.includes(query) || card.dataset.sectionSearch.includes(query);
      field.hidden = !visible;
      if (visible) visibleFields += 1;
    });
    card.hidden = visibleFields === 0;
    if (visibleFields > 0) visibleSections += 1;
    if (query && visibleFields > 0) card.open = true;
  });
  const oldEmpty = $(".no-results", $("#config-sections"));
  if (oldEmpty) oldEmpty.remove();
  if (!visibleSections) {
    const empty = document.createElement("div");
    empty.className = "no-results";
    empty.textContent = "没有找到匹配的参数";
    $("#config-sections").append(empty);
  }
}

function markChanged() {
  $("#save-state").textContent = "有未生成的更改";
  $("#save-state").style.color = "var(--accent)";
  updateStyleSelection();
  updateSummary();
  scheduleDraftSave();
}

function updateStyleSelection() {
  $("#font-preset").value = state.selectedPreset || "custom";
  $(".preset-monogram").textContent = ({ personal_v6: "游", anjingchen: "行", shaohua: "韶", caveat: "C", kalam: "K" })[state.selectedPreset] || "纸";
  $("#font-preset-name").textContent = PRESET_NAMES[state.selectedPreset] || "自定义笔迹";
  $$('[data-font-option]').forEach((option) => option.setAttribute("aria-selected", String(option.dataset.fontOption === state.selectedPreset)));
  $$("[data-preset]").forEach((button) => {
    const selected = button.dataset.preset === state.selectedPreset;
    button.classList.toggle("active", selected);
    button.setAttribute("aria-pressed", String(selected));
  });
}

function updateSummary() {
  if (!state.config) return;
  $("#render-summary-title").textContent = PRESET_NAMES[state.selectedPreset] || "自定义笔迹";
  $("#render-summary-meta").textContent = "中文 · English · 公式";
}

function updateDocumentStats() {
  const value = $("#markdown-editor").value;
  $("#char-count").textContent = value.length.toLocaleString("zh-CN");
  $("#line-count").textContent = (value ? value.split(/\r?\n/).length : 0).toLocaleString("zh-CN");
  $("#save-state").textContent = "文稿已更新";
  $("#save-state").style.color = "var(--ink-soft)";
}

function updateWarnings() {
  const warnings = [
    ...state.importWarnings.map((message) => ({ message })),
    ...state.renderWarnings,
  ];
  const panel = $("#render-warnings");
  const list = $("#render-warnings-list");
  $("#render-warnings-title").textContent = `转换提示（${warnings.length}）`;
  list.replaceChildren();
  warnings.forEach((warning) => {
    const item = document.createElement("li");
    item.append(document.createTextNode(warning.message || "公式需要检查。"));
    if (warning.formula) {
      const formula = document.createElement("code");
      formula.textContent = warning.formula;
      item.append(formula);
    }
    list.append(item);
  });
  panel.hidden = warnings.length === 0;
}

async function loadExample(name, notify = true) {
  if (!name) return;
  try {
    const response = await fetch(`/api/examples/${encodeURIComponent(name)}`);
    if (!response.ok) throw new Error("示例读取失败");
    $("#markdown-editor").value = await response.text();
    state.importWarnings = [];
    state.renderWarnings = [];
    updateWarnings();
    updateDocumentStats();
    scheduleDraftSave();
    if (notify) showToast("示例已载入", "可以继续编辑，或直接生成预览。");
  } catch (error) {
    showToast("无法载入示例", error.message, true);
  }
}

function applyPreset(name, notify = true, save = true) {
  const values = state.presets[name];
  if (!values) return;
  Object.entries(values).forEach(([path, value]) => setPath(state.config, path, value));
  state.selectedPreset = name;
  if (state.sections.length) { renderConfigSections(); renderQuickControls(); }
  updateStyleSelection();
  updateSummary();
  $("#save-state").textContent = "风格已选择，尚未生成";
  $("#save-state").style.color = "var(--accent)";
  if (save) scheduleDraftSave();
  if (notify) {
    showToast("笔迹已切换", `已选择“${PRESET_NAMES[name]}”，生成手稿即可查看效果。`);
  }
}

function setRendering(rendering) {
  state.rendering = rendering;
  $("#render-overlay").hidden = !rendering;
  ["#render-top", "#render-main", "#render-empty"].forEach((selector) => {
    const button = $(selector);
    button.disabled = rendering;
    button.classList.toggle("loading", rendering);
  });
  const dot = $(".status-dot");
  dot.classList.toggle("busy", rendering);
  dot.classList.remove("error");
  $("#service-status").textContent = rendering ? "正在书写与排版" : "本地渲染器已连接";
  if (rendering) {
    state.renderStartedAt = Date.now();
    $("#render-time").textContent = "00:00";
    const outputLabel = { image: "图片", docx: "Word", pdf: "PDF" }[state.outputFormat] || "图片";
    $("#render-step").textContent = `正在排版、书写并生成${outputLabel}…`;
    state.renderTimer = window.setInterval(() => {
      const seconds = Math.floor((Date.now() - state.renderStartedAt) / 1000);
      $("#render-time").textContent = `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;

    }, 500);
  } else if (state.renderTimer) {
    clearInterval(state.renderTimer);
    state.renderTimer = null;
  }
  updateUndoButton();
}

function updateUndoButton() {
  const button = $("#undo-page-edit");
  if (!button) return;
  const hasHistory = Boolean(state.pages.length && state.editHistory[state.page]?.length);
  button.disabled = !hasHistory || state.rendering;
  button.setAttribute("aria-disabled", String(button.disabled));
}

async function renderDocument() {
  if (state.rendering || state.editing || state.draftMark) return;
  if (state.pendingCommentPoint) {
    showToast("请先完成批注", "添加或取消当前批注后再开始转换。");
    return;
  }
  const markdown = $("#markdown-editor").value;
  if (!markdown.trim()) {
    showToast("文稿为空", "请先输入或载入 Markdown 内容。", true);
    return;
  }
  saveDraftNow();
  setRendering(true);
  try {
    const response = await fetch("/api/render", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Miaobi-Token": state.csrfToken },
      body: JSON.stringify({ markdown, config: state.config }),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "生成失败");
    state.pages = result.pages;
    state.commentWidth = Math.max(0.001, Math.min(0.08, (state.config.handwriting.body_font_pt * 25.4 / 72) / state.config.page.width_mm));
    state.exportPages = result.exportPages || result.pages;
    state.jobId = result.jobId;
    state.commentImages = [];
    state.edits = Array.from({ length: result.pageCount }, () => ({ rotation: 0, crop: null, marks: [] }));
    state.savedEdits = clone(state.edits);
    state.editHistory = Array.from({ length: result.pageCount }, () => []);
    state.renderWarnings = result.warnings || [];
    updateWarnings();
    state.page = 0;
    $("#page-count").textContent = result.pageCount;
    state.files = { pdf: result.pdf, docx: result.docx, image: result.image };
    syncMainExportButton();
    $("#download-output").classList.remove("disabled");
    $("#download-output").setAttribute("aria-disabled", "false");
    $("#download-png").disabled = false;
    $("#download-png").classList.remove("disabled");
    $("#format-pdf").disabled = false;
    $("#format-image").disabled = false;
    $("#empty-paper").hidden = true;
    ensurePreviewImage().hidden = false;
    setActiveEditTool("comment");
    showCurrentPage();
    $("#save-state").textContent = "预览已是最新";
    $("#save-state").style.color = "var(--sage-deep)";
    const seconds = ((Date.now() - state.renderStartedAt) / 1000).toFixed(1);
    showToast("手稿已生成", `${result.pageCount} 页 · 用时 ${seconds} 秒`);
    closePanels();
  } catch (error) {
    $(".status-dot").classList.add("error");
    $("#service-status").textContent = "生成遇到问题";
    showToast("生成失败", error.message, true);
  } finally {
    setRendering(false);
  }
}

function ensurePreviewImage() {
  let image = $("#preview-image");
  if (!image) {
    image = document.createElement("img");
    image.id = "preview-image";
    image.alt = "生成的手写报告页面";
    image.hidden = true;
    $("#paper-shell").insertBefore(image, $("#edit-layer"));
  }
  return image;
}

function showCurrentPage() {
  if (!state.pages.length) return;
  const image = ensurePreviewImage();
  image.src = state.pages[state.page];
  image.alt = `手写报告第 ${state.page + 1} 页`;
  image.onload = () => { syncEditLayer(); drawEditPreview(state.draftMark); };
  image.onerror = () => syncEditLayer();
  renderPageComments();
  $("#current-page").textContent = state.page + 1;
  $("#page-count").textContent = state.pages.length;
  $("#footer-current-page").textContent = state.page + 1;
  $("#footer-page-count").textContent = state.pages.length;
  $("#prev-page").disabled = state.page <= 0;
  $("#next-page").disabled = state.page >= state.pages.length - 1;
  $("#prev-page-bottom").disabled = state.page <= 0;
  $("#next-page-bottom").disabled = state.page >= state.pages.length - 1;
  const isA4 = state.config.page.width_mm === 210 && state.config.page.height_mm === 297;
  const pageSize = isA4 ? "A4" : `${state.config.page.width_mm} × ${state.config.page.height_mm} mm`;
  $("#preview-meta").textContent = `${state.pages.length} 页 · ${pageSize} · ${state.config.page.dpi} DPI`;
  $("#canvas-viewport").scrollTo({ top: 0, behavior: "smooth" });
  syncEditLayer();
  updateUndoButton();
}

function syncEditLayer() {
  const canvas = $("#edit-layer");
  if (!canvas) return;
  $("#comment-layer").classList.toggle("is-saving", state.editing);
  $("#comment-layer").classList.toggle("comment-mode", state.activeTool === "comment");
  const image = $("#preview-image");
  const width = image?.naturalWidth || 520;
  const height = image?.naturalHeight || 655;
  if (canvas.width !== width) canvas.width = width;
  if (canvas.height !== height) canvas.height = height;
  canvas.classList.toggle("is-editing", Boolean(state.pages.length && state.activeTool && !state.editing));
  canvas.classList.toggle("is-saving", state.editing);
  canvas.classList.toggle("crop-mode", state.activeTool === "crop");
  canvas.style.cursor = state.activeTool === "crop" ? "crosshair" : "crosshair";
}

function renderPageComments() {
  const layer = $("#comment-layer");
  if (!layer) return;
  layer.replaceChildren();
  const marks = state.edits[state.page]?.marks || [];
  marks.forEach((mark, markIndex) => {
    if (mark.kind !== "comment") return;
    const comment = document.createElement("button");
    comment.type = "button";
    comment.className = "comment-mark";
    const rendered = state.commentImages[state.page]?.[markIndex];
    if (rendered) {
      const img = document.createElement("img");
      img.src = rendered.url;
      img.alt = "";
      img.draggable = false;
      comment.append(img);
      comment.style.width = `${rendered.width * 100}%`;
      comment.style.height = `${rendered.height * 100}%`;
    } else {
      comment.textContent = mark.text;
      comment.style.color = mark.color;
      comment.style.width = "max-content";
    }
    comment.style.left = `${mark.points[0][0] * 100}%`;
    comment.style.top = `${mark.points[0][1] * 100}%`;
    comment.style.fontSize = `${mark.width * layer.clientWidth}px`;
    comment.dataset.markIndex = String(markIndex);
    comment.setAttribute("aria-label", `批注：${mark.text}，可拖动移动`);
    comment.addEventListener("pointerdown", beginCommentDrag);
    comment.addEventListener("pointermove", moveCommentDrag);
    comment.addEventListener("pointerup", finishCommentDrag);
    comment.addEventListener("pointercancel", finishCommentDrag);
    layer.append(comment);
  });
}

function beginCommentDrag(event) {
  if (event.button !== 0 || !state.pages.length || state.editing || state.rendering) return;
  const comment = event.currentTarget;
  const markIndex = Number(comment.dataset.markIndex);
  const mark = state.edits[state.page]?.marks[markIndex];
  const shellRect = $("#paper-shell").getBoundingClientRect();
  const commentRect = comment.getBoundingClientRect();
  if (mark?.kind !== "comment" || !shellRect.width || !shellRect.height) return;
  event.preventDefault();
  event.stopPropagation();
  state.commentDrag = {
    pointerId: event.pointerId,
    markIndex,
    comment,
    offsetX: (event.clientX - commentRect.left) / shellRect.width,
    offsetY: (event.clientY - commentRect.top) / shellRect.height,
    moved: false,
    startX: event.clientX,
    startY: event.clientY,
  };
  comment.setPointerCapture(event.pointerId);
}

function moveCommentDrag(event) {
  const drag = state.commentDrag;
  if (!drag || drag.pointerId !== event.pointerId) return;
  const distance = Math.hypot(event.clientX - drag.startX, event.clientY - drag.startY);
  if (!drag.moved && distance < 3) return;
  if (!drag.moved) {
    pushEditHistory(state.page);
    drag.moved = true;
    drag.comment.classList.add("dragging");
  }
  const shellRect = $("#paper-shell").getBoundingClientRect();
  const commentRect = drag.comment.getBoundingClientRect();
  const maxLeft = Math.max(0, shellRect.width - commentRect.width);
  const maxTop = Math.max(0, shellRect.height - commentRect.height);
  const left = Math.max(0, Math.min(maxLeft, event.clientX - shellRect.left - drag.offsetX * shellRect.width));
  const top = Math.max(0, Math.min(maxTop, event.clientY - shellRect.top - drag.offsetY * shellRect.height));
  const point = [left / shellRect.width, top / shellRect.height];
  state.edits[state.page].marks[drag.markIndex].points[0] = point;
  drag.comment.style.left = `${point[0] * 100}%`;
  drag.comment.style.top = `${point[1] * 100}%`;
  event.preventDefault();
}

async function finishCommentDrag(event) {
  const drag = state.commentDrag;
  if (!drag || drag.pointerId !== event.pointerId) return;
  state.commentDrag = null;
  drag.comment.classList.remove("dragging");
  if (drag.comment.hasPointerCapture(event.pointerId)) drag.comment.releasePointerCapture(event.pointerId);
  if (drag.moved) markLocalCommentEdit();
}

function setActiveEditTool(tool) {
  if (tool !== "comment" && state.pendingCommentPoint) closeCommentEditor();
  state.activeTool = tool;
  $$('[data-edit-tool]:not([data-edit-tool="rotate"])').forEach((button) => {
    const active = button.dataset.editTool === tool;
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", String(active));
  });
  syncEditLayer();
}

function drawEditPreview(mark) {
  const canvas = $("#edit-layer");
  const context = canvas.getContext("2d");
  context.clearRect(0, 0, canvas.width, canvas.height);
  const existing = state.edits[state.page]?.marks || [];
  for (const item of existing) {
    if (item.kind === "comment") continue;
    const points = item.points.map(([x, y]) => [x * canvas.width, y * canvas.height]);
    if (!points.length) continue;
    context.save();
    context.lineCap = "round";
    context.lineJoin = "round";
    context.lineWidth = Math.max(2, item.width * canvas.width);
    context.globalAlpha = item.kind === "highlight" ? 0.38 : 1;
    context.strokeStyle = item.color;
    context.beginPath();
    context.moveTo(points[0][0], points[0][1]);
    points.slice(1).forEach(([x, y]) => context.lineTo(x, y));
    context.stroke();
    context.restore();
  }
  if (!mark) return;
  const points = mark.points.map(([x, y]) => [x * canvas.width, y * canvas.height]);
  context.save();
  context.lineCap = "round";
  context.lineJoin = "round";
  context.lineWidth = Math.max(2, mark.width * canvas.width);
  context.globalAlpha = mark.kind === "highlight" ? 0.38 : 1;
  context.strokeStyle = mark.color;
  if (mark.kind === "crop") {
    const [x1, y1] = points[0];
    const [x2, y2] = points[points.length - 1];
    context.fillStyle = "rgba(17, 39, 81, .16)";
    context.fillRect(0, 0, canvas.width, canvas.height);
    context.clearRect(Math.min(x1, x2), Math.min(y1, y2), Math.abs(x2 - x1), Math.abs(y2 - y1));
    context.setLineDash([canvas.width * 0.012, canvas.width * 0.007]);
    context.lineWidth = Math.max(2, canvas.width * 0.002);
    context.strokeStyle = "#2864eb";
    context.strokeRect(Math.min(x1, x2), Math.min(y1, y2), Math.abs(x2 - x1), Math.abs(y2 - y1));
  } else {
    context.beginPath();
    context.moveTo(points[0][0], points[0][1]);
    if (mark.kind === "underline") context.lineTo(points.at(-1)[0], points.at(-1)[1]);
    else points.slice(1).forEach(([x, y]) => context.lineTo(x, y));
    context.stroke();
  }
  context.restore();
}

function editPointerPoint(event) {
  const rect = $("#edit-layer").getBoundingClientRect();
  return [
    Number(Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width)).toFixed(4)),
    Number(Math.max(0, Math.min(1, (event.clientY - rect.top) / rect.height)).toFixed(4)),
  ];
}

function openCommentEditor(point) {
  const shell = $("#paper-shell");
  const editor = $("#comment-editor");
  const input = $("#comment-text");
  const width = Math.min(240, shell.clientWidth * 0.48);
  const height = Math.min(190, Math.max(150, shell.clientHeight - 16));
  const left = Math.max(8, Math.min(point[0] * shell.clientWidth, shell.clientWidth - width - 8));
  const top = Math.max(8, Math.min(point[1] * shell.clientHeight, shell.clientHeight - height - 8));
  state.pendingCommentPoint = [left / shell.clientWidth, top / shell.clientHeight];
  editor.style.left = `${left}px`;
  editor.style.top = `${top}px`;
  editor.hidden = false;
  input.value = "";
  requestAnimationFrame(() => input.focus({ preventScroll: true }));
}

function closeCommentEditor() {
  $("#comment-editor").hidden = true;
  $("#comment-text").value = "";
  state.pendingCommentPoint = null;
  syncEditLayer();
}

async function saveComment() {
  const text = $("#comment-text").value.trim();
  const point = state.pendingCommentPoint;
  if (!text) {
    showToast("批注内容为空", "输入批注文字后再添加。", true);
    $("#comment-text").focus();
    return;
  }
  if (!point || !state.pages.length || state.editing || state.rendering) return;
  const fittedPoint = fitCommentPoint(point, text, state.commentWidth);
  pushEditHistory(state.page);
  state.edits[state.page].marks.push({
    kind: "comment",
    color: "#183865",
    width: state.commentWidth,
    points: [fittedPoint],
    text,
  });
  closeCommentEditor();
  markLocalCommentEdit();
}

function hasPendingPageEdits() {
  return JSON.stringify(state.edits) !== JSON.stringify(state.savedEdits);
}

function markLocalCommentEdit() {
  // Render text locally; generating all export files on each drag would block editing.
  state.commentImages[state.page] = {};
  renderPageComments();
  updateUndoButton();
  $("#save-state").textContent = "批注已修改，导出时保存";
}

function sameNonCommentEdits(first, second) {
  const withoutComments = (edit) => ({
    rotation: edit.rotation, crop: edit.crop,
    marks: edit.marks.filter((mark) => mark.kind !== "comment"),
  });
  return JSON.stringify(withoutComments(first)) === JSON.stringify(withoutComments(second));
}

function fitCommentPoint(point, text, width) {
  const layer = $("#comment-layer");
  const probe = document.createElement("button");
  probe.type = "button";
  probe.className = "comment-mark";
  probe.textContent = text;
  probe.style.left = "0";
  probe.style.top = "0";
  probe.style.width = "max-content";
  probe.style.fontSize = `${width * layer.clientWidth}px`;
  layer.append(probe);
  const maxLeft = Math.max(0, layer.clientWidth - probe.offsetWidth);
  const maxTop = Math.max(0, layer.clientHeight - probe.offsetHeight);
  const left = Math.max(0, Math.min(maxLeft, point[0] * layer.clientWidth));
  const top = Math.max(0, Math.min(maxTop, point[1] * layer.clientHeight));
  probe.remove();
  return [left / layer.clientWidth, top / layer.clientHeight];
}

function beginPageEdit(event) {
  if (!state.pages.length || state.rendering || state.editing || state.draftMark || !state.activeTool) return;
  const kind = state.activeTool;
  const point = editPointerPoint(event);
  if (kind === "comment") {
    openCommentEditor(point);
    return;
  }
  const color = ({ highlight: "#f0c728", underline: "#8b56bb" })[kind] || "#2864eb";
  const width = ({ highlight: 0.035, underline: 0.004, crop: 0.002 })[kind] || 0.005;
  state.draftMark = { kind, color, width, points: [point, point] };
  $("#edit-layer").setPointerCapture(event.pointerId);
  drawEditPreview(state.draftMark);
}

function continuePageEdit(event) {
  if (!state.draftMark) return;
  const point = editPointerPoint(event);
  if (state.draftMark.kind === "underline" || state.draftMark.kind === "crop") {
    state.draftMark.points[1] = point;
  } else {
    const points = state.draftMark.points;
    const last = points[points.length - 1];
    if (Math.hypot(point[0] - last[0], point[1] - last[1]) < 0.0004) return;
    if (points.length >= 550) state.draftMark.points = points.filter((_, index) => index % 2 === 0);
    state.draftMark.points.push(point);
  }
  drawEditPreview(state.draftMark);
}

async function finishPageEdit(event) {
  if (!state.draftMark || state.rendering || state.editing) return;
  continuePageEdit(event);
  const mark = state.draftMark;
  state.draftMark = null;
  if (mark.kind === "crop") {
    const [start, end] = mark.points;
    const x = Math.min(start[0], end[0]);
    const y = Math.min(start[1], end[1]);
    const width = Math.abs(end[0] - start[0]);
    const height = Math.abs(end[1] - start[1]);
    if (width < 0.025 || height < 0.025) {
      drawEditPreview(null);
      showToast("裁切区域太小", "拖出一个更大的矩形区域再试。");
      return;
    }
    pushEditHistory(state.page);
    const previousCrop = state.edits[state.page].crop;
    state.edits[state.page].crop = previousCrop
      ? [
          previousCrop[0] + x * previousCrop[2],
          previousCrop[1] + y * previousCrop[3],
          width * previousCrop[2],
          height * previousCrop[3],
        ]
      : [x, y, width, height];
  } else {
    if (mark.points.length < 2) mark.points.push([Math.min(1, mark.points[0][0] + 0.001), mark.points[0][1]]);
    pushEditHistory(state.page);
    state.edits[state.page].marks.push(mark);
  }
  await savePageEdits();
}

async function rotateCurrentPage() {
  if (state.rendering || state.editing) return;
  if (state.pendingCommentPoint) closeCommentEditor();
  if (!state.pages.length) {
    showToast("还没有生成手稿", "开始转换后即可旋转页面。");
    return;
  }
  pushEditHistory(state.page);
  const edit = state.edits[state.page];
  edit.rotation = (edit.rotation + 90) % 360;
  edit.crop = null;
  await savePageEdits();
}

function pushEditHistory(page) {
  const history = state.editHistory[page];
  history.push(clone(state.edits[page]));
  if (history.length > 20) history.shift();
  updateUndoButton();
}

async function undoPageEdit() {
  if (state.rendering) return;
  const previous = state.editHistory[state.page]?.pop();
  if (!previous) {
    showToast("没有可撤销的修改", "当前页的修改记录为空。");
    return;
  }
  const current = state.edits[state.page];
  state.edits[state.page] = previous;
  drawEditPreview(null);
  if (sameNonCommentEdits(current, previous)) {
    markLocalCommentEdit();
  } else {
    state.commentImages[state.page] = {};
    renderPageComments();
    updateUndoButton();
    await savePageEdits();
  }
}

async function resetPageEdits() {
  if (!state.pages.length || state.rendering || state.editing) return;
  pushEditHistory(state.page);
  state.edits[state.page] = { rotation: 0, crop: null, marks: [] };
  $("#more-menu").hidden = true;
  $("#more-actions").setAttribute("aria-expanded", "false");
  await savePageEdits();
}

async function savePageEdits() {
  if (!state.jobId || state.rendering) return;
  if (state.editing) { state.editSaveQueued = true; return; }
  state.editing = true;
  const snapshot = clone(state.edits);
  drawEditPreview(null);
  renderPageComments();
  updateUndoButton();
  $("#download-output").classList.add("disabled");
  $("#download-png").disabled = true;
  syncEditLayer();
  try {
    const response = await fetch("/api/edit", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Miaobi-Token": state.csrfToken },
      body: JSON.stringify({ jobId: state.jobId, edits: snapshot }),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "页面编辑失败");
    state.pages = result.pages;
    state.commentImages = result.commentImages || [];
    state.exportPages = result.exportPages || result.pages;
    state.files.pdf = result.pdf;
    state.files.docx = result.docx;
    state.files.image = result.image;
    state.savedEdits = snapshot;
    syncMainExportButton();
    showCurrentPage();
    return true;
  } catch (error) {
    showToast("保存失败", `${error.message || "请稍后重试。"} 页面修改仍在，请重试导出。`, true);
    return false;
  } finally {
    state.editing = false;
    if (state.editSaveQueued) {
      state.editSaveQueued = false;
      await savePageEdits();
      return;
    }
    $("#download-output").classList.remove("disabled");
    $("#download-png").disabled = false;
    syncEditLayer();
    updateUndoButton();
  }
}

function setActiveModule(module) {
  state.module = module;
  const scanning = module === "scan";
  document.body.dataset.module = module;
  $("#text-workspace").hidden = module !== "text";
  $("#scan-workspace").hidden = !scanning;
  $("#history-workspace").hidden = module !== "history";
  $("#nav-history").classList.toggle("active", module === "history");
  $("#nav-history").setAttribute("aria-current", module === "history" ? "page" : "false");
  $("#mobile-history").textContent = module === "history" ? "返回转换" : "导出记录";
  if (module === "history") renderHistory();
  $("#nav-text").classList.toggle("active", module === "text");
  $("#nav-scan").classList.toggle("active", scanning);
  $("#nav-text").setAttribute("aria-current", module === "text" ? "page" : "false");
  $("#nav-scan").setAttribute("aria-current", scanning ? "page" : "false");
  const mobileSwitch = $("#mobile-module-switch");
  mobileSwitch.setAttribute("aria-label", scanning ? "切换到文本转换" : "切换到智能扫描");
  $("#mobile-module-switch span").textContent = scanning ? "文本转换" : "智能扫描";
  const pageTitle = $("#page-title");
  if (pageTitle) pageTitle.textContent = scanning ? "智能扫描" : "手写体转换";
  const pageSubtitle = $("#page-subtitle");
  if (pageSubtitle) {
    pageSubtitle.textContent = scanning
      ? "一键扫描图片，优化文档效果，支持多种输出格式"
      : "将文稿内容转换为自然的手写文档，支持灵活调整纸张与笔迹参数";
  }
  closePanels();
  if (scanning) requestAnimationFrame(sizeScanPreview);
}

function setScanBusy(busy, message = "") {
  state.scanProcessing = busy;
  $("#scan-processing").hidden = !busy;
  if (message) $("#scan-progress").textContent = message;
  updateScanControls();
}

function scanBase64(bytes) {
  let binary = "";
  const chunkSize = 0x8000;
  for (let offset = 0; offset < bytes.length; offset += chunkSize) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + chunkSize));
  }
  return btoa(binary);
}

async function uploadScanFiles(fileList) {
  const files = [...fileList];
  if (!files.length) return;
  const accepted = files.filter((file) => /\.(jpe?g|png|heic|heif|bmp|webp)$/i.test(file.name));
  const rejected = files.length - accepted.length;
  if (!accepted.length) {
    showToast("图片格式不支持", "请选择 JPG、PNG、HEIC、HEIF、BMP 或 WebP 图片。", true);
    return;
  }
  if (state.scanPages.length + accepted.length > 30) {
    showToast("图片数量过多", "每次最多扫描 30 张图片。", true);
    return;
  }
  setScanBusy(true, "正在导入并自动校正图片…");
  let completed = 0;
  let failures = 0;
  try {
    for (let index = 0; index < accepted.length; index += 1) {
      const file = accepted[index];
      if (file.size > MAX_SCAN_FILE_BYTES) {
        showToast("图片过大", `${file.name} 超过 18 MB，已跳过。`, true);
        continue;
      }
      $("#scan-progress").textContent = `正在载入第 ${index + 1} / ${accepted.length} 张图片…`;
      const data = scanBase64(new Uint8Array(await file.arrayBuffer()));
      const response = await fetch("/api/scan/upload", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Miaobi-Token": state.csrfToken },
        body: JSON.stringify({ filename: file.name, data }),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || `${file.name} 上传失败`);
      const page = {
        scanId: result.scanId,
        filename: result.filename,
        url: result.url,
        detected: result.detected,
        autoCorners: result.corners,
        corners: null,
        warning: result.warning,
        processed: false,
        rotation: 0,
        crop: null, marks: [], redo: [],
      };
      state.scanPages.push(page);
      state.scanPage = state.scanPages.length - 1;
      if (typeof persistScanSession === "function") persistScanSession();
      $("#scan-progress").textContent = `正在自动校正第 ${index + 1} / ${accepted.length} 张图片…`;
      try {
        await processOneScan(page);
        completed += 1;
      } catch (error) {
        failures += 1;
        page.warning = `自动处理失败：${error.message}。可调整纸面后重新扫描。`;
      }
      showScanPage();
    }
    if (failures) showToast("部分图片处理失败", `${completed} 张已完成，${failures} 张可调整后重试。`, true);
    else if (rejected) showToast("部分文件已跳过", `${completed} 张已自动处理；请只上传支持的图片格式。`);
    else showToast("自动扫描完成", `已校正并处理 ${completed} 张图片。`);
  } catch (error) {
    showToast("图片载入失败", error.message || "请检查图片格式后重试。", true);
  } finally {
    setScanBusy(false);
    showScanPage();
  }
}

async function scanRequest(path, payload) {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Miaobi-Token": state.csrfToken },
    body: JSON.stringify(payload),
  });
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || "扫描请求失败。");
  return result;
}

function scanSettingsKey(page, includeMode = true) {
  return JSON.stringify([includeMode ? state.scanMode : null, state.scanOrientation, page.rotation, page.crop, page.corners || null]);
}

function scanPageReady(page) {
  return page.processed && !page.error && !page.restoreError && !page.restoring && page.appliedSettings === scanSettingsKey(page);
}

async function refreshScanRestoration(page, manageBusy = true) {
  page.restoredUrl = null;
  page.restoreError = null;
  if (page.appliedMode !== "remove_handwriting" || !page.marks?.some(mark => mark.kind === "restore")) {
    if (manageBusy) showScanPage();
    return;
  }
  page.restoring = true;
  if (manageBusy) setScanBusy(true, "正在恢复原图内容…");
  try {
    const result = await scanRequest("/api/scan/restore-preview", {scanId: page.scanId, marks: page.marks});
    page.restoredUrl = result.url;
  } catch (error) {
    page.restoreError = error.message;
    showToast("恢复预览失败", "可撤销本次恢复后重试。", true);
  } finally {
    page.restoring = false;
    if (manageBusy) { setScanBusy(false); showScanPage(); }
  }
}

function renderScanFilterImages(page) {
  $$('[data-scan-mode]').forEach(button => {
    const image = button.querySelector(".scan-filter-image img");
    const url = page?.filterPreviews?.[button.dataset.scanMode];
    image.hidden = !url;
    if (url && image.getAttribute("src") !== url) image.src = url;
    if (!url) image.removeAttribute("src");
  });
}

async function loadScanFilterPreviews(page) {
  if (!page) return;
  const key = scanSettingsKey(page, false);
  if (page.filterPreviewKey === key) return;
  page.filterPreviewKey = key;
  page.filterPreviews = {};
  renderScanFilterImages(page);
  const options = { orientation: state.scanOrientation, rotation: page.rotation, crop: page.crop, corners: page.corners || null };
  const buttons = $$('[data-scan-mode]').filter(button => button.dataset.unavailable !== "true");
  // One request at a time: avoid running five full-resolution filters in
  // parallel on large camera uploads. The chosen filter is requested first.
  const modes = buttons.map(button => button.dataset.scanMode)
    .sort((a, b) => Number(b === state.scanMode) - Number(a === state.scanMode));
  for (const mode of modes) {
    if (page.filterPreviewKey !== key || state.scanPages[state.scanPage] !== page) {
      // Allow a later visit to resume/reload after navigating away.
      if (page.filterPreviewKey === key) page.filterPreviewKey = null;
      return;
    }
    try {
      const result = await scanRequest("/api/scan/filter-preview", { scanId: page.scanId, ...options, mode });
      if (page.filterPreviewKey !== key) return;
      page.filterPreviews[mode] = result.url;
      if (state.scanPages[state.scanPage] === page) renderScanFilterImages(page);
    } catch (error) {
      // Main processing remains available if a thumbnail request fails.
      if (page.filterPreviewKey !== key) return;
      page.filterPreviewKey = null;
      return;
    }
  }
}

async function processOneScan(page) {
  const appliedSettings = scanSettingsKey(page);
  const options = {
    scanId: page.scanId,
    mode: state.scanMode,
    orientation: state.scanOrientation,
    rotation: page.rotation,
    crop: page.crop,
    corners: page.corners || null,
  };
  try {
    const result = await scanRequest("/api/scan/process", options);
    if (page.filterPipelineVersion !== result.filterPipelineVersion) page.filterPreviewKey = null;
    Object.assign(page, result, { appliedSettings, appliedMode: options.mode });
    delete page.error;
    await refreshScanRestoration(page, false);
    return result;
  } catch (error) {
    page.error = error.message;
    throw error;
  }
}

async function startScan() {
  if (!state.scanPages.length || state.scanProcessing) return;
  setScanBusy(true, "正在检测纸面并增强图片…");
  let completed = 0;
  let errors = 0;
  try {
    for (const page of state.scanPages) {
      completed += 1;
      $("#scan-progress").textContent = `正在处理第 ${completed} / ${state.scanPages.length} 张图片…`;
      try {
        await processOneScan(page);
        if (page.restoreError) errors += 1;
      } catch (error) {
        errors += 1;
        page.error = error.message;
      }
      showScanPage();
    }
    if (errors) showToast("部分图片扫描失败", `${errors} 张图片未能处理，请重试。`, true);
    else showToast("扫描完成", `已增强 ${state.scanPages.length} 张图片。`);
  } finally {
    setScanBusy(false);
    showScanPage();
  }
}

async function reprocessScans() {
  if (!state.scanPages.length || !state.scanPages.some((page) => page.processed)) {
    showScanPage();
    return;
  }
  await startScan();
}

async function processCurrentScan() {
  const page = state.scanPages[state.scanPage];
  if (!page || state.scanProcessing) return;
  setScanBusy(true, "正在更新当前图片…");
  try {
    await processOneScan(page);
    showScanPage();
    if (!page.restoreError) showToast("预览已更新", "当前页面设置已应用。");
  } catch (error) {
    showToast("扫描处理失败", error.message, true);
  } finally {
    setScanBusy(false);
    showScanPage();
  }
}

function updateScanControls() {
  persistScanSession();
  const hasPages = state.scanPages.length > 0;
  $("#scan-controls").classList.toggle("has-pages", hasPages);
  const page = state.scanPages[state.scanPage];
  const processedCount = state.scanPages.filter(scanPageReady).length;
  $("#scan-start").disabled = !hasPages || state.scanProcessing;
  $("#scan-start span").textContent = processedCount === state.scanPages.length && hasPages ? "重新扫描" : "扫描图片";
  $("#scan-export").disabled = !hasPages || processedCount !== state.scanPages.length || state.scanProcessing;
  $("#scan-export-dock").disabled = $("#scan-export").disabled;
  $("#scan-rotate").disabled = !hasPages || state.scanProcessing;
  $("#scan-zoom-in").disabled = !hasPages || state.scanProcessing || state.scanZoom >= 2;
  $("#scan-zoom-out").disabled = !hasPages || state.scanProcessing || state.scanZoom <= 0.5;
  $("#scan-compare").disabled = !page?.processed || state.scanProcessing;
  $("#scan-corners").disabled = !hasPages || state.scanProcessing;
  $("#scan-prev").disabled = !hasPages || state.scanPage <= 0 || state.scanProcessing;
  $("#scan-next").disabled = !hasPages || state.scanPage >= state.scanPages.length - 1 || state.scanProcessing;
  ["[data-scan-mode]", "[data-scan-orientation]", "[data-scan-format]"].forEach((selector) => {
    $$(selector).forEach((button) => { button.disabled = state.scanProcessing || button.dataset.unavailable === "true"; });
  });
  $("#scan-pick").disabled = state.scanProcessing;
  $$("[data-scan-mark]").forEach(button => { button.disabled = !page?.processed || state.scanProcessing; });
  $("#scan-undo").disabled = !page?.marks?.length || state.scanProcessing;
  $("#scan-zoom-label").textContent = `${Math.round(state.scanZoom * 100)}%`;
  $("#scan-export span").textContent = ({pdf:"导出 PDF",jpg:"导出图片",docx:"导出 Word"})[state.scanFormat];
  $("#scan-export-dock span").textContent = $("#scan-export span").textContent;
  $("#scan-clear").disabled = state.scanProcessing || !hasPages;
  $("#scan-page-count").textContent = state.scanPages.length;
  $("#scan-current-number").textContent = hasPages ? state.scanPage + 1 : 0;
  if (!state.scanProcessing) {
    $("#scan-status").textContent = hasPages
      ? `${processedCount} / ${state.scanPages.length} 张已扫描`
      : "导入图片后自动校正并扫描";
  }
  $("#scan-count").textContent = `${state.scanPages.length} 页`;
  renderScanFilterImages(page);
}

function showScanPage() {
  if (state.scanCommentPoint) closeScanCommentEditor();
  const page = state.scanPages[state.scanPage];
  const image = $("#scan-image");
  state.scanComparing = false; $("#scan-compare span").textContent = "对比原图";
  if (!page || page.appliedMode !== "remove_handwriting") state.scanRestoreEditing = false;
  $("#scan-empty").hidden = Boolean(page);
  $("#scan-image-wrap").hidden = !page;
  $("#scan-crop-layer").classList.toggle("is-cropping", Boolean((state.scanCropEditing || state.scanRestoreEditing || state.scanMarkTool) && page?.processed));
  if (page) {
    image.alt = `${page.filename}扫描预览`;
    image.onload = sizeScanPreview;
    image.onerror = () => showToast("预览无法显示", "请重新载入这张图片。", true);
    image.src = page.restoredUrl || page.url;
    if (page.warning) $("#scan-export-hint").textContent = page.warning.replaceAll("裁切工具", "校正纸面");
    else $("#scan-export-hint").textContent = "图片在本机处理，不会上传到外部服务";
    if (page.error) $("#scan-export-hint").textContent = page.error;
    if (page.restoreError) $("#scan-export-hint").textContent = page.restoreError;
  } else {
    $("#scan-export-hint").textContent = "图片在本机处理，不会上传到外部服务";
    state.scanCropEditing = false;
    state.draftScanCrop = null;
  }
  updateScanControls();
  renderScanThumbnails();
  if (page) requestAnimationFrame(sizeScanPreview);
  if (!state.scanProcessing) loadScanFilterPreviews(page);
}

function sizeScanPreview() {
  const page = state.scanPages[state.scanPage];
  const image = $("#scan-image");
  if (!page || !image.naturalWidth || !image.naturalHeight) return;
  const stage = $("#scan-stage").getBoundingClientRect();
  const availableWidth = Math.max(160, stage.width - 36);
  const availableHeight = Math.max(180, stage.height - 36);
  const ratio = image.naturalWidth / image.naturalHeight;
  const width = Math.min(availableWidth, availableHeight * ratio) * state.scanZoom;
  const height = width / ratio;
  const wrap = $("#scan-image-wrap");
  wrap.style.width = `${Math.round(width)}px`;
  wrap.style.height = `${Math.round(height)}px`;
  const canvas = $("#scan-crop-layer");
  if (canvas.width !== image.naturalWidth) canvas.width = image.naturalWidth;
  if (canvas.height !== image.naturalHeight) canvas.height = image.naturalHeight;
  drawScanCropPreview();
}

function renderScanThumbnails() {
  const rail = $("#scan-thumbnails");
  rail.replaceChildren();
  state.scanPages.forEach((page, index) => {
    const button = document.createElement("button");
    button.className = `scan-thumbnail${index === state.scanPage ? " active" : ""}`;
    button.type = "button";
    button.setAttribute("aria-label", `查看第 ${index + 1} 张：${page.filename}`);
    const image = document.createElement("img");
    image.src = page.url;
    image.alt = "";
    const number = document.createElement("span");
    number.textContent = index + 1;
    button.append(image, number);
    button.addEventListener("click", () => {
      if (state.scanProcessing) return;
      state.scanPage = index;
      state.scanCropEditing = false;
      state.scanRestoreEditing = false;
      state.draftScanCrop = null;
      showScanPage();
    });
    rail.append(button);
  });
}

function moveScanPage(direction) {
  if (state.scanProcessing || !state.scanPages.length) return;
  state.scanPage = Math.max(0, Math.min(state.scanPages.length - 1, state.scanPage + direction));
  state.scanCropEditing = false;
  state.scanRestoreEditing = false;
  state.draftScanCrop = null;
  showScanPage();
}

function setScanMode(mode) {
  closeScanCommentEditor();
  const button = $$('[data-scan-mode]').find(button => button.dataset.scanMode === mode);
  if (!button || button.dataset.unavailable === "true" || state.scanProcessing) return;
  state.scanMode = mode;
  $$('[data-scan-mode]').forEach((button) => {
    const active = button.dataset.scanMode === mode;
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", String(active));
  });
  reprocessScans();
}

function setScanOrientation(orientation) {
  if (state.scanOrientation !== orientation) {
    if (state.scanPages.some(page => page.marks?.length) && !confirm("切换页面方向会清除标注和恢复区域，是否继续？")) return;
    state.scanPages.forEach((page) => { page.crop = null; page.marks = []; page.redo = []; });
  }
  state.scanOrientation = orientation;
  $$('[data-scan-orientation]').forEach((button) => {
    const active = button.dataset.scanOrientation === orientation;
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", String(active));
  });
  reprocessScans();
}

async function rotateScanPage() {
  const page = state.scanPages[state.scanPage];
  if (!page || state.scanProcessing) return;
  if (page.marks?.length && !confirm("旋转会清除当前页的标注，是否继续？")) return;
  page.marks = []; page.redo = [];
  page.rotation = (page.rotation + 90) % 360;
  page.crop = null;
  if (page.processed) await processCurrentScan();
  else showScanPage();
}

function validScanCorners(points) {
  if (!Array.isArray(points) || points.length !== 4) return false;
  if (points.some(p => !Array.isArray(p) || p.length !== 2 || p.some(v => !Number.isFinite(v) || v < 0 || v > 1))) return false;
  const crosses = points.map((a, i) => {
    const b = points[(i + 1) % 4], c = points[(i + 2) % 4];
    return (b[0]-a[0])*(c[1]-b[1]) - (b[1]-a[1])*(c[0]-b[0]);
  });
  const area = Math.abs(points.reduce((sum, a, i) => { const b = points[(i+1)%4]; return sum+a[0]*b[1]-a[1]*b[0]; }, 0)) / 2;
  return area >= .015 && (crosses.every(v => v > 0) || crosses.every(v => v < 0)) &&
    points.every((a,i) => Math.hypot(a[0]-points[(i+1)%4][0], a[1]-points[(i+1)%4][1]) >= .02);
}

function drawScanCorners() {
  const points = state.scanCornerDraft;
  if (!points) return;
  $("#scan-corner-polygon").setAttribute("points", points.map(p => p.map(v => v*1000).join(",")).join(" "));
  $$("[data-corner-handle]").forEach((button, i) => {
    button.style.left = `${points[i][0]*100}%`;
    button.style.top = `${points[i][1]*100}%`;
  });
  const valid = validScanCorners(points);
  $("#scan-corner-apply").disabled = !valid || !state.scanCornerLoaded || state.scanProcessing;
  $("#scan-corner-error").textContent = !state.scanCornerLoaded ? "正在载入原图…" : valid ? "" : "四角不能交叉或过于靠近，请重新调整。";
}

function openScanCorners() {
  const page = state.scanPages[state.scanPage];
  if (!page || state.scanProcessing) return;
  state.scanCornerPage = page;
  state.scanCornerLoaded = false;
  $("#scan-corner-stage").style.visibility = "hidden";
  state.scanCornerDraft = clone(page.corners || page.autoCorners || [[0,0],[1,0],[1,1],[0,1]]);
  $("#scan-corner-image").src = `/output/scans/${page.scanId}/original.png`;
  $("#scan-corner-dialog").showModal();
  drawScanCorners();
}

async function applyScanCorners() {
  const page = state.scanCornerPage;
  if (!page || !state.scanCornerLoaded || state.scanProcessing || !validScanCorners(state.scanCornerDraft)) return;
  if (page.marks?.length && !confirm("校正纸面会清除当前页的标注，是否继续？")) return;
  const previous = { corners: page.corners, crop: page.crop };
  page.corners = clone(state.scanCornerDraft);
  page.crop = null;
  setScanBusy(true, "正在校正纸面…");
  $$("#scan-corner-dialog button").forEach(button => { button.disabled = true; });
  try {
    await processOneScan(page);
    page.marks = []; page.redo = [];
    state.scanCropEditing = false; state.scanRestoreEditing = false; state.draftScanCrop = null; state.scanMarkTool = null;
    $$("[data-scan-mark]").forEach(button => button.classList.remove("active"));
    $("#scan-corner-dialog").close();
  } catch (error) {
    Object.assign(page, previous);
    $("#scan-corner-error").textContent = error.message;
  } finally {
    setScanBusy(false);
    $$("#scan-corner-dialog button").forEach(button => { button.disabled = false; });
    showScanPage();
  }
}

function bindScanCorners() {
  const button = document.createElement("button");
  button.id = "scan-corners"; button.type = "button"; button.className = "scan-tool"; button.disabled = true;
  button.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m5 6 14-2-2 16-14-2Z"/><path d="M3 3v4m-2-2h4m14 14v4m-2-2h4"/></svg><span>校正纸面</span>';
  $("#scan-zoom-in").before(button);
  button.addEventListener("click", openScanCorners);
  $("#scan-corner-image").addEventListener("load", () => {
    state.scanCornerLoaded = true;
    $("#scan-corner-stage").style.visibility = "visible";
    drawScanCorners();
  });
  $("#scan-corner-image").addEventListener("error", () => {
    state.scanCornerLoaded = false;
    $("#scan-corner-error").textContent = "原图载入失败，请关闭后重试。";
    $("#scan-corner-apply").disabled = true;
  });
  $("#scan-corner-apply").addEventListener("click", applyScanCorners);
  $("#scan-corner-cancel").addEventListener("click", () => $("#scan-corner-dialog").close());
  $("#scan-corner-dialog").addEventListener("cancel", event => { if (state.scanProcessing) event.preventDefault(); });
  $$("[data-corner-handle]").forEach((handle, i) => {
    let pointer = null;
    handle.addEventListener("pointerdown", event => {
      if (state.scanProcessing) return;
      event.preventDefault(); handle.focus(); pointer = event.pointerId; handle.setPointerCapture(pointer);
    });
    handle.addEventListener("pointermove", event => {
      if (pointer !== event.pointerId || state.scanProcessing) return;
      const rect = $("#scan-corner-stage").getBoundingClientRect();
      state.scanCornerDraft[i] = [Math.max(0,Math.min(1,(event.clientX-rect.left)/rect.width)), Math.max(0,Math.min(1,(event.clientY-rect.top)/rect.height))];
      drawScanCorners();
    });
    const end = () => { pointer = null; };
    handle.addEventListener("pointerup", end); handle.addEventListener("pointercancel", end); handle.addEventListener("lostpointercapture", end);
    handle.addEventListener("keydown", event => {
      if (state.scanProcessing) return;
      const delta = {ArrowLeft:[-1,0],ArrowRight:[1,0],ArrowUp:[0,-1],ArrowDown:[0,1]}[event.key];
      if (!delta) return;
      event.preventDefault();
      state.scanCornerDraft[i] = state.scanCornerDraft[i].map((v,j) => Math.max(0,Math.min(1,v+delta[j]*(event.shiftKey ? .01 : .002))));
      drawScanCorners();
    });
  });
}

function scanPointerPoint(event) {
  const rect = $("#scan-crop-layer").getBoundingClientRect();
  return [
    Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width)),
    Math.max(0, Math.min(1, (event.clientY - rect.top) / rect.height)),
  ];
}

function drawScanCropPreview() {
  const canvas = $("#scan-crop-layer");
  const context = canvas.getContext("2d");
  if (!context) return;
  context.clearRect(0, 0, canvas.width, canvas.height);
  const page = state.scanPages[state.scanPage];
  renderScanComments(page);
  for (const mark of [...(page?.marks || []), ...(state.scanDraftMark ? [state.scanDraftMark] : [])]) {
    if (mark.kind === "restore" || mark.kind === "comment") continue;
    const points = mark.points; if (!points.length) continue;
    context.save(); context.strokeStyle = mark.color; context.fillStyle = mark.color; context.globalAlpha = mark.kind === "highlight" ? .38 : 1; context.lineWidth = mark.width * canvas.width; context.lineCap = "round"; context.lineJoin = "round";
    if (mark.kind === "comment") { context.font = `${Math.max(16, canvas.width * .025)}px sans-serif`; context.fillText(`批注：${mark.text}`, points[0][0]*canvas.width, points[0][1]*canvas.height); }
    else { context.beginPath(); context.moveTo(points[0][0]*canvas.width, points[0][1]*canvas.height); points.slice(1).forEach(([x,y])=>context.lineTo(x*canvas.width,y*canvas.height)); context.stroke(); } context.restore();
  }
  if (!(state.scanCropEditing || state.scanRestoreEditing) || !state.draftScanCrop) return;
  const [x1, y1] = state.draftScanCrop[0];
  const [x2, y2] = state.draftScanCrop[1];
  const left = Math.min(x1, x2) * canvas.width;
  const top = Math.min(y1, y2) * canvas.height;
  const width = Math.abs(x2 - x1) * canvas.width;
  const height = Math.abs(y2 - y1) * canvas.height;
  context.fillStyle = "rgba(17, 39, 81, .24)";
  context.fillRect(0, 0, canvas.width, canvas.height);
  context.clearRect(left, top, width, height);
  context.strokeStyle = "#2864eb";
  context.lineWidth = Math.max(2, canvas.width * 0.003);
  context.setLineDash([canvas.width * 0.014, canvas.width * 0.008]);
  context.strokeRect(left, top, width, height);
}

function renderScanComments(page) {
  const layer = $("#scan-comment-layer");
  layer.classList.toggle("comment-mode", state.scanMarkTool === "comment" && !state.scanProcessing);
  layer.replaceChildren();
  (page?.marks || []).forEach(mark => {
    if (mark.kind !== "comment") return;
    const button = document.createElement("button");
    button.type = "button"; button.className = "comment-mark";
    button.textContent = mark.text; button.style.color = mark.color;
    button.style.left = `${mark.points[0][0]*100}%`; button.style.top = `${mark.points[0][1]*100}%`;
    button.style.fontSize = `${mark.width*layer.clientWidth}px`;
    button.setAttribute("aria-label", `批注：${mark.text}，可拖动移动`);
    let drag = null;
    button.addEventListener("pointerdown", event => {
      if (state.scanMarkTool !== "comment" || state.scanProcessing) return;
      event.stopPropagation(); event.preventDefault();
      const box=layer.getBoundingClientRect(), current=button.getBoundingClientRect();
      drag={id:event.pointerId, dx:event.clientX-current.left, dy:event.clientY-current.top, box};
      button.setPointerCapture(event.pointerId); button.classList.add("dragging");
    });
    button.addEventListener("pointermove", event => {
      if (!drag || drag.id !== event.pointerId) return;
      const x=Math.max(0,Math.min(drag.box.width-button.offsetWidth,event.clientX-drag.box.left-drag.dx));
      const y=Math.max(0,Math.min(drag.box.height-button.offsetHeight,event.clientY-drag.box.top-drag.dy));
      mark.points[0]=[x/drag.box.width,y/drag.box.height];
      button.style.left=`${mark.points[0][0]*100}%`; button.style.top=`${mark.points[0][1]*100}%`;
    });
    const end=() => { drag=null; button.classList.remove("dragging"); };
    button.addEventListener("pointerup",end); button.addEventListener("pointercancel",end);
    layer.append(button);
  });
}

function openScanCommentEditor(point) {
  const wrap=$("#scan-image-wrap"), editor=$("#scan-comment-editor");
  const width=Math.min(240,wrap.clientWidth*.70), height=Math.min(190,Math.max(150,wrap.clientHeight-16));
  const left=Math.max(8,Math.min(point[0]*wrap.clientWidth,wrap.clientWidth-width-8));
  const top=Math.max(8,Math.min(point[1]*wrap.clientHeight,wrap.clientHeight-height-8));
  state.scanCommentPoint=[left/wrap.clientWidth,top/wrap.clientHeight];
  editor.style.left=`${left}px`; editor.style.top=`${top}px`; editor.hidden=false;
  $("#scan-comment-text").value="";
  requestAnimationFrame(() => $("#scan-comment-text").focus({preventScroll:true}));
}

function closeScanCommentEditor() {
  $("#scan-comment-editor").hidden=true; $("#scan-comment-text").value=""; state.scanCommentPoint=null;
}

function beginScanCrop(event) {
  if (!(state.scanCropEditing || state.scanRestoreEditing) || state.scanProcessing || !state.scanPages[state.scanPage]?.processed) return;
  event.preventDefault();
  const point = scanPointerPoint(event);
  state.draftScanCrop = [point, point];
  $("#scan-crop-layer").setPointerCapture(event.pointerId);
  drawScanCropPreview();
}

function moveScanCrop(event) {
  if (!state.draftScanCrop) return;
  state.draftScanCrop[1] = scanPointerPoint(event);
  drawScanCropPreview();
}

async function finishScanCrop(event) {
  if (!state.draftScanCrop) return;
  moveScanCrop(event);
  const [[startX, startY], [endX, endY]] = state.draftScanCrop;
  state.draftScanCrop = null;
  if (state.scanRestoreEditing) {
    const width = Math.abs(endX-startX), height = Math.abs(endY-startY);
    if (width < .001 || height < .001) { drawScanCropPreview(); return; }
    const page = state.scanPages[state.scanPage];
    if (page.marks.length >= 150) { showToast("编辑数量已达上限", "请撤销部分标注或恢复区域后再试。", true); return; }
    page.marks.push({kind: "restore", rect: [Math.min(startX,endX), Math.min(startY,endY), width, height]});
    page.redo = [];
    await refreshScanRestoration(page);
    return;
  }
  drawScanCropPreview();
}

async function exportScans() {
  if (!state.scanPages.length || state.scanProcessing) return;
  if (!state.scanPages.every(scanPageReady)) {
    showToast("请先开始扫描", "处理完所有图片后即可导出。", true);
    return;
  }
  try {
    const result = await scanRequest("/api/scan/export", {
      scanIds: state.scanPages.map((page) => page.scanId),
      format: state.scanFormat,
      edits: state.scanPages.map(page => ({marks: page.marks || [], rotation: 0, crop: null})),
    });
    const link = document.createElement("a");
    link.href = result.url;
    link.download = result.filename;
    document.body.append(link);
    link.click();
    link.remove();
    addExportRecord({name: result.filename, url: result.url, source: "scan", pages: state.scanPages.length});
    showToast("文件已导出", result.filename);
  } catch (error) {
    showToast("导出失败", error.message || "请重试。", true);
  }
}

function clearScanList() {
  if (state.scanProcessing) return;
  state.scanPages = [];
  state.scanPage = 0;
  state.scanZoom = 1;
  state.scanCropEditing = false;
  state.draftScanCrop = null;
  $("#scan-files").value = "";
  showScanPage();
}

function updateSamplePagination() {
  const page = state.page + 1;
  ["#current-page", "#footer-current-page"].forEach((selector) => { $(selector).textContent = page; });
  ["#page-count", "#footer-page-count"].forEach((selector) => { $(selector).textContent = SAMPLE_PAGE_COUNT; });
  ["#prev-page", "#prev-page-bottom"].forEach((selector) => { $(selector).disabled = state.page === 0; });
  ["#next-page", "#next-page-bottom"].forEach((selector) => { $(selector).disabled = state.page === SAMPLE_PAGE_COUNT - 1; });
  $(".paper-footer").textContent = `— ${page} —`;
}

function syncMainExportButton() {
  const link = $("#download-output");
  const options = {
    docx: { label: "导出 Word", filename: "markdown-to-handwrite.docx" },
    pdf: { label: "导出 PDF", filename: "markdown-to-handwrite.pdf" },
    image: { label: "导出图片", filename: "handwritten-pages.zip" },
  };
  const option = options[state.outputFormat] || options.pdf;
  link.href = state.files[state.outputFormat] || "#";
  link.download = option.filename;
  $("span", link).textContent = option.label;
  link.setAttribute("aria-label", option.label);
  $("#export-dock").textContent = option.label;
}

async function saveTextExport() {
  if (state.editing || state.rendering) {
    showToast("正在保存页面", "请稍候再导出。");
    return;
  }
  if (!state.pages.length) {
    showToast("还没有生成手稿", "开始转换后即可导出完整文稿。");
    return;
  }
  const format = state.outputFormat;
  if (!state.files[format]) {
    showToast("导出文件未就绪", "请重新生成手稿后再试。", true);
    return;
  }
  if (typeof window.showSaveFilePicker !== "function") {
    showToast("当前浏览器不支持选择保存位置", "请使用最新版 Chrome 或 Edge 打开此页面后导出。", true);
    return;
  }
  const formats = {
    pdf: { filename: "手写文稿.pdf", description: "PDF 文档", mime: "application/pdf", extension: ".pdf" },
    docx: { filename: "手写文稿.docx", description: "Word 文档", mime: "application/vnd.openxmlformats-officedocument.wordprocessingml.document", extension: ".docx" },
    image: { filename: "手写文稿图片.zip", description: "图片压缩包", mime: "application/zip", extension: ".zip" },
  };
  const option = formats[format];
  try {
    const handle = await window.showSaveFilePicker({
      suggestedName: option.filename,
      types: [{ description: option.description, accept: { [option.mime]: [option.extension] } }],
      excludeAcceptAllOption: true,
    });
    if (hasPendingPageEdits() && !(await savePageEdits())) return;
    const url = state.files[format];
    const response = await fetch(url);
    if (!response.ok) throw new Error("无法读取导出文件，请重新生成后再试。");
    const blob = await response.blob();
    const writable = await handle.createWritable();
    try {
      await writable.write(blob);
      await writable.close();
    } catch (error) {
      await writable.abort().catch(() => {});
      throw error;
    }
    addExportRecord({ name: handle.name, url, source: "text", pages: state.pages.length });
    showToast("导出成功", `已保存 ${handle.name}`);
  } catch (error) {
    if (error.name !== "AbortError") showToast("导出失败", error.message || "请检查保存权限后重试。", true);
  }
}

function movePage(direction) {
  if (state.editing) return;
  if (state.pendingCommentPoint) closeCommentEditor();
  const pageCount = state.pages.length || SAMPLE_PAGE_COUNT;
  state.page = Math.min(pageCount - 1, Math.max(0, state.page + direction));
  if (state.pages.length) showCurrentPage();
  else updateSamplePagination();
  updateUndoButton();
}

async function downloadCurrentPng() {
  if (!state.pages.length) {
    showToast("还没有生成手稿", "开始转换后即可下载当前页 PNG。");
    return;
  }
  try {
    if (hasPendingPageEdits() && !(await savePageEdits())) return;
    const image = new Image();
    image.src = state.exportPages[state.page] || state.pages[state.page];
    await image.decode();
    const canvas = document.createElement("canvas");
    canvas.width = image.naturalWidth;
    canvas.height = image.naturalHeight;
    const context = canvas.getContext("2d");
    if (!context) throw new Error("无法创建图片画布");
    context.drawImage(image, 0, 0);
    const blob = await new Promise((resolve) => canvas.toBlob(resolve, "image/png"));
    if (!blob) throw new Error("PNG 图片生成失败");
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `handwritten-page-${state.page + 1}.png`;
    anchor.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  } catch (error) {
    showToast("PNG 导出失败", error.message || "请重新生成预览后再试。", true);
  }
}

function setZoom(value) {
  state.zoom = Math.max(0.25, Math.min(1.6, value));
  $("#paper-shell").style.width = `${Math.round(520 * state.zoom)}px`;
  $("#zoom-label").textContent = `${Math.round(state.zoom * 100)}%`;
  renderPageComments();
}

function fitPreview() {
  const viewport = $("#canvas-viewport");
  const horizontalPadding = window.innerWidth <= 620 ? 20 : 48;
  const verticalPadding = window.innerWidth <= 620 ? 22 : 48;
  const widthFit = (viewport.clientWidth - horizontalPadding) / 520;
  const heightFit = ((viewport.clientHeight - verticalPadding) * (520 / 655)) / 520;
  setZoom(Math.min(1.6, Math.max(0.25, widthFit), Math.max(0.25, heightFit)));
}

function downloadJson(filename, data) {
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

function showToast(title, message, error = false) {
  const toast = $("#toast");
  if (state.toastTimer) clearTimeout(state.toastTimer);
  $("#toast-title").textContent = title;
  $("#toast-message").textContent = message;
  $(".toast-mark", toast).textContent = error ? "!" : "✓";
  toast.classList.toggle("error", error);
  toast.hidden = false;
  requestAnimationFrame(() => toast.classList.add("show"));
  state.toastTimer = setTimeout(() => {
    toast.classList.remove("show");
    setTimeout(() => { toast.hidden = true; }, 260);
  }, error ? 5200 : 3200);
}

function openPasteDialog() {
  const dialog = $("#paste-dialog");
  const input = $("#paste-text");
  input.value = $("#markdown-editor").value;
  dialog.showModal();
  requestAnimationFrame(() => {
    input.focus({ preventScroll: true });
    input.setSelectionRange(input.value.length, input.value.length);
  });
}

function applyPastedText() {
  const markdown = $("#markdown-editor");
  markdown.value = $("#paste-text").value;
  markdown.dispatchEvent(new Event("input", { bubbles: true }));
  $("#editor-disclosure").open = false;
  $("#paste-dialog").close();
  showToast("文稿已载入", "文字已准备好，可以开始转换。");
}

function openPanel(name) {
  closePanels();
  const panel = name === "scan-controls" ? $("#scan-controls") : $(`#${name}-panel`);
  panel.classList.add("open");
  $("#panel-scrim").hidden = false;
}

function closePanels() {
  $$(".side-panel.open").forEach((panel) => panel.classList.remove("open"));
  $("#panel-scrim").hidden = true;
}

function bindEvents() {
  bindScanCorners();
  $("#nav-text").addEventListener("click", () => setActiveModule("text"));
  $("#nav-scan").addEventListener("click", () => setActiveModule("scan"));
  $("#nav-history").addEventListener("click", () => setActiveModule("history"));
  $("#mobile-history").addEventListener("click", () => setActiveModule(state.module === "history" ? "text" : "history"));
  initHistory();
  $("#mobile-module-switch").addEventListener("click", () => setActiveModule(state.module === "scan" ? "text" : "scan"));
  $("#scan-pick").addEventListener("click", () => $("#scan-files").click());
  $("#scan-files").addEventListener("change", async (event) => {
    await uploadScanFiles(event.target.files);
    event.target.value = "";
  });
  const scanDropzone = $("#scan-dropzone");
  ["dragenter", "dragover"].forEach((eventName) => scanDropzone.addEventListener(eventName, (event) => {
    event.preventDefault();
    scanDropzone.classList.add("dragging");
  }));
  ["dragleave", "drop"].forEach((eventName) => scanDropzone.addEventListener(eventName, (event) => {
    event.preventDefault();
    scanDropzone.classList.remove("dragging");
  }));
  scanDropzone.addEventListener("drop", (event) => uploadScanFiles(event.dataTransfer?.files || []));
  $("#scan-start").addEventListener("click", startScan);
  $("#scan-clear").addEventListener("click", clearScanList);
  $("#scan-export").addEventListener("click", exportScans);
  $("#scan-export-dock").addEventListener("click", exportScans);
  $("#scan-prev").addEventListener("click", () => moveScanPage(-1));
  $("#scan-next").addEventListener("click", () => moveScanPage(1));
  $("#scan-compare").addEventListener("click", () => { const page=state.scanPages[state.scanPage]; if (!page?.processed) return; state.scanComparing=!state.scanComparing; $("#scan-image").src=state.scanComparing ? (page.alignedOriginalUrl || `/output/scans/${page.scanId}/original.png`) : (page.restoredUrl || page.url); $("#scan-compare span").textContent=state.scanComparing ? "返回扫描效果" : "对比原图"; });
  $("#scan-zoom-in").addEventListener("click", () => { state.scanZoom = Math.min(2, Math.round((state.scanZoom + 0.2) * 10) / 10); sizeScanPreview(); updateScanControls(); });
  $("#scan-zoom-out").addEventListener("click", () => { state.scanZoom = Math.max(0.5, Math.round((state.scanZoom - 0.2) * 10) / 10); sizeScanPreview(); updateScanControls(); });
  $("#scan-rotate").addEventListener("click", rotateScanPage);
  $$("[data-scan-mark]").forEach(button => button.addEventListener("click", () => {
    closeScanCommentEditor();
    state.scanRestoreEditing = false;
    state.scanMarkTool = state.scanMarkTool === button.dataset.scanMark ? null : button.dataset.scanMark; state.scanCropEditing = false;
    $$("[data-scan-mark]").forEach(b => b.classList.toggle("active", b.dataset.scanMark === state.scanMarkTool));
    $("#scan-crop-layer").classList.toggle("is-cropping", !!state.scanMarkTool);
    drawScanCropPreview();
  }));
  $("#scan-comment-cancel").addEventListener("click", closeScanCommentEditor);
  $("#scan-comment-save").addEventListener("click", () => {
    const text=$("#scan-comment-text").value.trim(), page=state.scanPages[state.scanPage];
    if (!text || !page || !state.scanCommentPoint) { showToast("批注内容为空", "输入批注文字后再添加。", true); return; }
    page.marks.push({kind:"comment",color:"#183865",width:.028,points:[state.scanCommentPoint],text:text.slice(0,240)});
    page.redo=[]; closeScanCommentEditor(); drawScanCropPreview(); updateScanControls();
  });
  $("#scan-undo").addEventListener("click", async () => { const p=state.scanPages[state.scanPage]; if(state.scanProcessing || !p?.marks.length) return; const mark=p.marks.pop(); p.redo.push(mark); if(mark.kind === "restore") await refreshScanRestoration(p); drawScanCropPreview(); updateScanControls(); });
  const markLayer = $("#scan-crop-layer");
  markLayer.addEventListener("pointerdown", e => { if(!state.scanMarkTool || state.scanCropEditing) return; const p=state.scanPages[state.scanPage]; const point=scanPointerPoint(e); const kind=state.scanMarkTool; if(kind === "comment") { openScanCommentEditor(point); return; } state.scanDraftMark={kind,color:kind === "highlight" ? "#f0c728" : "#8b56bb",width:kind === "highlight" ? .035 : .004,points:[point,point]}; markLayer.setPointerCapture(e.pointerId); });
  markLayer.addEventListener("pointermove", e => { const m=state.scanDraftMark; if(!m) return; const point=scanPointerPoint(e); if(m.kind === "underline") m.points[1]=point; else if(m.points.length < 600) m.points.push(point); drawScanCropPreview(); });
  markLayer.addEventListener("pointerup", () => { if(!state.scanDraftMark) return; const p=state.scanPages[state.scanPage]; p.marks.push(state.scanDraftMark); p.redo=[]; state.scanDraftMark=null; drawScanCropPreview(); updateScanControls(); });
  $("#scan-crop-layer").addEventListener("pointerdown", beginScanCrop);
  $("#scan-crop-layer").addEventListener("pointermove", moveScanCrop);
  $("#scan-crop-layer").addEventListener("pointerup", finishScanCrop);
  $("#scan-crop-layer").addEventListener("pointercancel", () => {
    state.draftScanCrop = null;
    drawScanCropPreview();
  });
  $$('[data-scan-mode]').forEach((button) => button.addEventListener("click", () => setScanMode(button.dataset.scanMode)));
  $$('[data-scan-orientation]').forEach((button) => button.addEventListener("click", () => setScanOrientation(button.dataset.scanOrientation)));
  $$('[data-scan-format]').forEach((button) => button.addEventListener("click", () => {
    state.scanFormat = button.dataset.scanFormat;
    updateScanControls();
    $$('[data-scan-format]').forEach((option) => {
      const active = option === button;
      option.classList.toggle("active", active);
      option.setAttribute("aria-pressed", String(active));
    });
  }));
  $("#markdown-editor").addEventListener("input", () => {
    state.importWarnings = [];
    state.renderWarnings = [];
    updateWarnings();
    updateDocumentStats();
    scheduleDraftSave();
  });
  $("#example-select").addEventListener("change", (event) => loadExample(event.target.value));
  $("#pick-file").addEventListener("click", () => $("#markdown-import").click());
  $("#edit-text").addEventListener("click", openPasteDialog);
  $("#close-paste-dialog").addEventListener("click", () => $("#paste-dialog").close());
  $("#cancel-paste").addEventListener("click", () => $("#paste-dialog").close());
  $("#apply-paste").addEventListener("click", applyPastedText);
  $("#cancel-comment").addEventListener("click", closeCommentEditor);
  $("#save-comment").addEventListener("click", saveComment);
  $("#paste-dialog").addEventListener("click", (event) => {
    if (event.target === $("#paste-dialog")) $("#paste-dialog").close();
  });
  const dropzone = $("#file-dropzone");
  ["dragenter", "dragover"].forEach((eventName) => dropzone.addEventListener(eventName, (event) => {
    event.preventDefault();
    dropzone.classList.add("dragging");
  }));
  ["dragleave", "drop"].forEach((eventName) => dropzone.addEventListener(eventName, (event) => {
    event.preventDefault();
    dropzone.classList.remove("dragging");
  }));
  dropzone.addEventListener("drop", (event) => {
    if (!event.dataTransfer?.files?.length) return;
    const input = $("#markdown-import");
    input.files = event.dataTransfer.files;
    input.dispatchEvent(new Event("change", { bubbles: true }));
  });
  $("#markdown-import").addEventListener("change", async (event) => {
    const file = event.target.files[0];
    if (!file) return;
    try {
      let markdown;
      let warnings = [];
      if (file.name.toLowerCase().endsWith(".docx")) {
        if (file.size > 5 * 1024 * 1024) throw new Error("WebUI 暂时支持 5 MB 以内的 DOCX 文件。");
        const bytes = new Uint8Array(await file.arrayBuffer());
        let binary = "";
        const chunkSize = 0x8000;
        for (let offset = 0; offset < bytes.length; offset += chunkSize) {
          binary += String.fromCharCode(...bytes.subarray(offset, offset + chunkSize));
        }
        const response = await fetch("/api/import-docx", {
          method: "POST",
          headers: { "Content-Type": "application/json", "X-Miaobi-Token": state.csrfToken },
          body: JSON.stringify({ filename: file.name, data: btoa(binary) }),
        });
        const result = await response.json();
        if (!response.ok) throw new Error(result.error || "Word 文档导入失败。");
        markdown = result.markdown;
        warnings = result.warnings || [];
      } else {
        markdown = await file.text();
      }
      $("#markdown-editor").value = markdown;
      state.importWarnings = warnings;
      state.renderWarnings = [];
      updateWarnings();
      updateDocumentStats();
      scheduleDraftSave();
      const warningText = warnings.length ? `；${warnings.length} 条提示：${warnings.slice(0, 2).join("；")}` : "";
      showToast("文稿已导入", `${file.name}${warningText}`);
    } catch (error) {
      showToast("文稿无法导入", error.message || "请确认文件格式正确。", true);
    } finally {
      event.target.value = "";
    }
  });
  $$("[data-preset]").forEach((button) => button.addEventListener("click", () => applyPreset(button.dataset.preset)));
  $("#font-preset").addEventListener("change", (event) => applyPreset(event.target.value));
  const fontToggle = $("#font-preset-toggle");
  const fontMenu = $("#font-preset-menu");
  const closeFontMenu = (focus = false) => {
    fontMenu.hidden = true;
    fontToggle.setAttribute("aria-expanded", "false");
    if (focus) fontToggle.focus();
  };
  fontToggle.addEventListener("click", () => {
    const opening = fontMenu.hidden;
    fontMenu.hidden = !opening;
    fontToggle.setAttribute("aria-expanded", String(opening));
    if (opening) (fontMenu.querySelector('[aria-selected="true"]:not(:disabled)') || fontMenu.querySelector('button:not(:disabled)'))?.focus();
  });
  fontMenu.addEventListener("click", (event) => {
    const option = event.target.closest('[data-font-option]');
    if (!option || option.disabled) return;
    applyPreset(option.dataset.fontOption);
    closeFontMenu(true);
  });
  fontMenu.addEventListener("keydown", (event) => {
    if (event.key === "Escape") { event.preventDefault(); event.stopPropagation(); closeFontMenu(true); return; }
    if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    const options = [...fontMenu.querySelectorAll('button:not(:disabled)')];
    const index = options.indexOf(document.activeElement);
    const next = event.key === "Home" ? 0 : event.key === "End" ? options.length - 1 : (index + (event.key === "ArrowDown" ? 1 : -1) + options.length) % options.length;
    options[next]?.focus();
  });
  document.addEventListener("pointerdown", (event) => {
    if (!event.target.closest("#font-picker")) closeFontMenu();
  });
  $("#font-picker").addEventListener("focusout", (event) => {
    if (!event.currentTarget.contains(event.relatedTarget)) closeFontMenu();
  });
  $$("[data-paper-style]").forEach((button) => button.addEventListener("click", () => {
    const style = button.dataset.paperStyle;
    if (style === "image") {
      $("#custom-paper-file").click();
      return;
    }
    configurePaperStyle(style);
    $("#empty-paper").style.backgroundImage = "";
    syncPaperOptions();
    markChanged();
  }));
  $("#custom-paper-file").addEventListener("change", async (event) => {
    const file = event.target.files[0];
    if (!file) return;
    try {
      if (file.size > 5 * 1024 * 1024) throw new Error("背景图片不能超过 5 MB。");
      const bytes = new Uint8Array(await file.arrayBuffer());
      let binary = "";
      for (let offset = 0; offset < bytes.length; offset += 0x8000) {
        binary += String.fromCharCode(...bytes.subarray(offset, offset + 0x8000));
      }
      const response = await fetch("/api/background/upload", {
        method: "POST", headers: { "Content-Type": "application/json", "X-Miaobi-Token": state.csrfToken },
        body: JSON.stringify({ data: btoa(binary) }),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || "背景图片上传失败。");
      state.config.background.style = "image";
      state.config.background.image = result.path;
      $("#empty-paper").style.backgroundImage = `url(${JSON.stringify(result.url)})`;
      syncPaperOptions();
      markChanged();
      showToast("背景已选择", "开始转换后应用到所有页面。");
    } catch (error) {
      showToast("无法使用背景", error.message || "请选择 PNG、JPG 或 WebP 图片。", true);
    } finally {
      event.target.value = "";
    }
  });
  const outputOptions = ["#format-word", "#format-pdf", "#format-image"];
  const selectOutput = (selected) => outputOptions.forEach((selector) => {
    const button = $(selector);
    const active = selector === selected;
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", String(active));
  });
  const setOutputFormat = (format, selected) => {
    state.outputFormat = format;
    selectOutput(selected);
    syncMainExportButton();
  };
  $("#format-word").addEventListener("click", () => {
    setOutputFormat("docx", "#format-word");
  });
  $("#format-pdf").addEventListener("click", () => {
    setOutputFormat("pdf", "#format-pdf");
  });
  $("#format-image").addEventListener("click", () => {
    setOutputFormat("image", "#format-image");
  });
  $("#download-output").addEventListener("click", (event) => {
    event.preventDefault();
    saveTextExport();
  });
  $("#config-search").addEventListener("input", applyConfigSearch);
  $("#reset-config").addEventListener("click", resetConfiguration);
  $("#export-dock").addEventListener("click", () => $("#download-output").click());
  ["#render-top", "#render-main", "#render-empty"].forEach((selector) => $(selector).addEventListener("click", renderDocument));
  $("#prev-page").addEventListener("click", () => movePage(-1));
  $("#next-page").addEventListener("click", () => movePage(1));
  $("#prev-page-bottom").addEventListener("click", () => movePage(-1));
  $("#next-page-bottom").addEventListener("click", () => movePage(1));
  $("#zoom-in").addEventListener("click", () => setZoom(state.zoom + 0.1));
  $("#zoom-out").addEventListener("click", () => setZoom(state.zoom - 0.1));
  $("#zoom-in-tool").addEventListener("click", () => setZoom(state.zoom + 0.1));
  $("#zoom-out-tool").addEventListener("click", () => setZoom(state.zoom - 0.1));
  $("#zoom-fit").addEventListener("click", fitPreview);
  $("#download-png").addEventListener("click", downloadCurrentPng);
  $("#more-actions").addEventListener("click", () => {
    const menu = $("#more-menu");
    menu.hidden = !menu.hidden;
    $("#more-actions").setAttribute("aria-expanded", String(!menu.hidden));
  });
  $("#undo-page-edit").addEventListener("click", () => {
    undoPageEdit();
  });
  $("#reset-page-edit").addEventListener("click", resetPageEdits);
  $$('[data-edit-tool]').forEach((button) => button.addEventListener("click", () => {
    if (button.dataset.editTool === "rotate") {
      rotateCurrentPage();
      return;
    }
    if (!state.pages.length) {
      showToast("还没有生成手稿", "开始转换后即可在页面上使用编辑工具。");
      return;
    }
    setActiveEditTool(button.dataset.editTool);
  }));
  $("#edit-layer").addEventListener("pointerdown", (event) => {
    event.preventDefault();
    beginPageEdit(event);
  });
  $("#edit-layer").addEventListener("pointermove", continuePageEdit);
  $("#edit-layer").addEventListener("pointerup", finishPageEdit);
  $("#edit-layer").addEventListener("pointercancel", () => {
    state.draftMark = null;
    drawEditPreview(null);
  });
  $$('[data-placeholder]').forEach((button) => button.addEventListener("click", () => {
    showToast("功能即将接入", `${button.dataset.placeholder}工具会在后续完善。`);
  }));
  $("#theme-toggle").addEventListener("click", () => {
    const theme = document.body.dataset.theme === "dark" ? "light" : "dark";
    document.body.dataset.theme = theme;
    localStorage.setItem("markdown-to-handwrite-theme", theme);
  });
  $("#toggle-editor").addEventListener("click", () => openPanel(state.module === "scan" ? "scan-controls" : "editor"));
  $("#toggle-settings").addEventListener("click", () => openPanel(state.module === "scan" ? "scan-controls" : "editor"));
  $("#fullscreen-preview").addEventListener("click", async () => {
    const preview = $(".preview-card");
    try {
      if (document.fullscreenElement) await document.exitFullscreen();
      else await preview.requestFullscreen();
    } catch {
      showToast("无法进入全屏", "请检查浏览器的全屏权限后重试。", true);
    }
  });
  $$("[data-close-panel]").forEach((button) => button.addEventListener("click", closePanels));
  $("#panel-scrim").addEventListener("click", closePanels);
  window.addEventListener("resize", () => {
    if (state.module === "scan") sizeScanPreview();
    else if (window.innerWidth <= 620) fitPreview();
    if (state.module === "text") renderPageComments();
  });
  document.addEventListener("keydown", (event) => {
    if (state.module === "text" && (event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "z" && !["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement?.tagName)) {
      event.preventDefault();
      undoPageEdit();
    }
    if (event.key === "Escape") {
      if (state.pendingCommentPoint) {
        closeCommentEditor();
        return;
      }
      closePanels();
      $("#more-menu").hidden = true;
      $("#more-actions").setAttribute("aria-expanded", "false");
    }
  });
  document.addEventListener("pointerdown", (event) => {
    if (!event.target.closest(".more-wrapper")) {
      $("#more-menu").hidden = true;
      $("#more-actions").setAttribute("aria-expanded", "false");
    }
  });
}

async function initialize() {
  document.body.dataset.theme = localStorage.getItem("markdown-to-handwrite-theme") || "light";
  try {
    const response = await fetch("/api/bootstrap");
    if (!response.ok) throw new Error("无法读取配置模型");
    const bootstrap = await response.json();
    state.csrfToken = bootstrap.csrfToken;
    const draft = readDraft();
    state.defaults = bootstrap.config;
    state.config = draft?.config ? mergeDeep(clone(bootstrap.config), draft.config) : clone(bootstrap.config);
    // Upgrade the old untouched formula defaults without overwriting custom sizes.
    if (draft?.preset === "anjingchen" && (draft.anjingchenFormulaVersion || 0) < 3 && bootstrap.presets.anjingchen) {
      const target = bootstrap.presets.anjingchen;
      const handwriting = state.config.handwriting;
      const previous = { math_font_pt: [16, 18], math_inline_scale: [1, 1.15],
        math_stroke_weight_scale: [1, 1.35, 1.25, 0.8], math_jitter_scale: [0.08, 0.22],
        math_font_path: [null], math_match_body_ink: [false], math_wrap_long: [false], math_character_rotation_deg: [0] };
      for (const [key, values] of Object.entries(previous)) {
        if (values.includes(handwriting[key])) handwriting[key] = target[`handwriting.${key}`];
      }
      handwriting.math_display_left_aligned = target["handwriting.math_display_left_aligned"];
    }
    if (draft?.preset === "anjingchen" && !draft.anjingchenTableInkVersion && bootstrap.presets.anjingchen) {
      state.config.handwriting.uniform_table_ink = bootstrap.presets.anjingchen["handwriting.uniform_table_ink"];
    }
    if (draft?.preset === "caveat" && !draft.caveatTableInkVersion && bootstrap.presets.caveat) {
      state.config.handwriting.uniform_table_ink = bootstrap.presets.caveat["handwriting.uniform_table_ink"];
    }
    if (draft?.preset === "caveat" && (draft.caveatMathInkVersion || 0) < 2 && bootstrap.presets.caveat) {
      state.config.handwriting.math_match_body_ink = bootstrap.presets.caveat["handwriting.math_match_body_ink"];
      if (state.config.handwriting.math_stroke_weight_scale === 1) {
        state.config.handwriting.math_stroke_weight_scale = bootstrap.presets.caveat["handwriting.math_stroke_weight_scale"];
      }
    }
    if (draft?.preset === "caveat" && !draft.caveatCorrectionVersion && bootstrap.presets.caveat) {
      state.config.handwriting.latin_word_corrections = bootstrap.presets.caveat["handwriting.latin_word_corrections"];
    }
    if (draft?.preset === "shaohua" && (draft.shaohuaInkVersion || 0) < 2 && bootstrap.presets.shaohua) {
      const target = bootstrap.presets.shaohua;
      const handwriting = state.config.handwriting;
      const previous = { handwritten_digit_one: [false], uniform_table_ink: [false], legible_decimal_point: [false],
        ink_density_jitter: [0.025], dry_brush_probability: [0.01],
        stroke_weight_variation_sigma_ratio: [0.0035] };
      for (const [key, values] of Object.entries(previous)) {
        if (values.includes(handwriting[key])) handwriting[key] = target[`handwriting.${key}`];
      }
    }
    // Migrate only the previous preset's untouched spacing defaults.
    const migrateFontSpacing = draft?.preset === "personal_v6" && !draft.presetVersion &&
        state.config.handwriting.body_font_pt === 16 && state.config.handwriting.word_spacing_px === 2;
    if (migrateFontSpacing) {
      state.config.handwriting.body_font_pt = bootstrap.presets.personal_v6?.["handwriting.body_font_pt"] ?? 15;
      state.config.handwriting.word_spacing_px = bootstrap.presets.personal_v6?.["handwriting.word_spacing_px"] ?? 0;
    }
    // Older drafts could retain oversized top margins on the built-in ruled paper.
    const builtinRuledPaper = [RED_LINED_PAPER, GREEN_LINED_PAPER].includes(state.config.background.image);
    state.paperLayoutVersion = draft?.config ? (draft.paperLayoutVersion || 0) : 1;
    const migratePaperMargin = Boolean(draft?.config && !state.paperLayoutVersion && builtinRuledPaper && state.config.page.margin_top_mm > 30);
    if (migratePaperMargin) state.config.page.margin_top_mm = 22;
    if (builtinRuledPaper) state.paperLayoutVersion = 1;
    if (!draft?.config) {
      state.config.background.style = "plain";
      state.config.background.image = null;
      state.config.background.paper_color = "#ffffff";
      state.config.background.draw_margin_line = false;
    }
    if (state.config.background.style === "image" && state.config.background.image) {
      const name = state.config.background.image.split(/[\\/]/).pop();
      if (/^[a-f0-9]{24}\.png$/.test(name)) $("#empty-paper").style.backgroundImage = `url(/output/backgrounds/${name})`;
    }
    state.sections = bootstrap.sections;
    state.presets = bootstrap.presets;
    state.assets = bootstrap.assets;
    $("#font-preset option[value=personal_v6]").disabled = !Object.hasOwn(state.presets, "personal_v6");
    $("[data-font-option=personal_v6]").disabled = !Object.hasOwn(state.presets, "personal_v6");
    $("#font-preset option[value=anjingchen]").disabled = !Object.hasOwn(state.presets, "anjingchen");
    $("[data-font-option=anjingchen]").disabled = !Object.hasOwn(state.presets, "anjingchen");
    $("#font-preset option[value=shaohua]").disabled = !Object.hasOwn(state.presets, "shaohua");
    $("[data-font-option=shaohua]").disabled = !Object.hasOwn(state.presets, "shaohua");
    $("#font-preset option[value=caveat]").disabled = !Object.hasOwn(state.presets, "caveat");
    $("[data-font-option=caveat]").disabled = !Object.hasOwn(state.presets, "caveat");
    $("#font-preset option[value=kalam]").disabled = !Object.hasOwn(state.presets, "kalam");
    $("[data-font-option=kalam]").disabled = !Object.hasOwn(state.presets, "kalam");
    if (!draft?.config) applyPreset("formal", false, false);
    else {
      state.selectedPreset = Object.hasOwn(state.presets, draft.preset) ? draft.preset : null;
      updateStyleSelection();
      updateSummary();
    }
    renderConfigSections();
    renderQuickControls();
    const isA4 = state.config.page.width_mm === 210 && state.config.page.height_mm === 297;
    const pageSize = isA4 ? "A4" : `${state.config.page.width_mm} × ${state.config.page.height_mm} mm`;
    $("#preview-meta").textContent = `${SAMPLE_PAGE_COUNT} 页 · ${pageSize} · ${state.config.page.dpi} DPI`;
    bootstrap.examples.forEach((example) => {
      const option = document.createElement("option");
      option.value = example.value;
      option.textContent = example.label;
      $("#example-select").append(option);
    });
    bindEvents();
    syncMainExportButton();
    restoreScanSession();
    showScanPage();
    updateSamplePagination();
    if (draft) {
      const draftOption = document.createElement("option");
      draftOption.value = "__local-draft";
      draftOption.textContent = "本地草稿";
      $("#example-select").prepend(draftOption);
      $("#example-select").value = draftOption.value;
      $("#markdown-editor").value = draft.markdown;
      updateDocumentStats();
      if (migrateFontSpacing || migratePaperMargin) saveDraftNow();
    } else {
      const preferred = bootstrap.examples.find((example) => example.value === "report0.md") || bootstrap.examples[0];
      if (preferred) {
        $("#example-select").value = preferred.value;
        await loadExample(preferred.value, false);
      }
    }
    requestAnimationFrame(() => setZoom(state.zoom));
    $("#service-status").textContent = "本地渲染器已连接";
  } catch (error) {
    $(".status-dot").classList.add("error");
    $("#service-status").textContent = "无法连接渲染器";
    showToast("WebUI 初始化失败", error.message, true);
  }
}

initialize();

const HISTORY_KEY = "handwriting-export-history-v1";
let historySource = "all", historyPage = 1;
function readExportRecords() { try { const data = JSON.parse(localStorage.getItem(HISTORY_KEY) || "[]"); return Array.isArray(data) ? data : []; } catch { return []; } }
function saveExportRecords(records) { try { localStorage.setItem(HISTORY_KEY, JSON.stringify(records)); } catch { showToast("记录保存失败", "浏览器存储空间不足。", true); } }
function addExportRecord(record) { const records = readExportRecords(); records.unshift({...record, id: `${Date.now()}-${Math.random().toString(36).slice(2)}`, time: Date.now()}); saveExportRecords(records); }
function escapeHistory(value) { const el = document.createElement("span"); el.textContent = String(value ?? ""); return el.innerHTML.replaceAll('"', '&quot;').replaceAll("'", '&#39;'); }
function historyFormat(name) { const ext = name.split(".").pop().toUpperCase(); return ext === "DOCX" ? "WORD" : ext === "JPEG" ? "JPG" : ext; }
function renderHistory() {
  const records = readExportRecords();
  $("#history-text-count").innerHTML = `<span class="history-count-number">${records.filter(r => r.source === "text").length}</span> <small>条导出记录</small>`;
  $("#history-scan-count").innerHTML = `<span class="history-count-number">${records.filter(r => r.source === "scan").length}</span> <small>条导出记录</small>`;
  const format = $("#history-format").value, time = $("#history-time").value, query = $("#history-search").value.trim().toLowerCase();
  const filtered = records.filter(r => (historySource === "all" || r.source === historySource) && (format === "all" || historyFormat(r.name) === format) && r.name.toLowerCase().includes(query) && (time === "all" || (time === "today" ? new Date(r.time).toDateString() === new Date().toDateString() : Date.now() - r.time < (time === "week" ? 7 : 30) * 86400000)));
  const size = Number($("#history-page-size").value), pages = Math.max(1, Math.ceil(filtered.length / size)); historyPage = Math.min(historyPage, pages);
  const rows = filtered.slice((historyPage - 1) * size, historyPage * size);
  $("#history-rows").innerHTML = rows.map(r => `<tr><td><div class="history-file"><span class="history-file-icon ${r.source === "scan" ? "scan" : ""}">${escapeHistory(historyFormat(r.name))}</span><span><strong>${escapeHistory(r.name)}</strong><small>${r.pages || 1} ${r.source === "scan" ? "张图片" : "页"}</small></span></div></td><td>${r.source === "scan" ? "智能扫描" : "文本转换"}</td><td><span class="history-format">${escapeHistory(historyFormat(r.name))}</span></td><td>${new Date(r.time).toLocaleString("zh-CN", {year:"numeric", month:"2-digit", day:"2-digit", hour:"2-digit", minute:"2-digit"})}</td><td><span class="history-success">✓ 导出成功</span></td><td><div class="history-actions"><a href="${escapeHistory(r.url)}" download="${escapeHistory(r.name)}">下载</a><button data-delete-history="${escapeHistory(r.id)}" aria-label="删除 ${escapeHistory(r.name)} 的记录">删除</button></div></td></tr>`).join("");
  $("#history-empty").hidden = filtered.length > 0;
  $("#history-empty-title").textContent = records.length ? "暂无符合条件的导出记录" : "暂无导出记录";
  $("#history-empty-description").textContent = records.length ? "试试调整筛选条件或搜索内容" : "导出文件后可在这里查看";
  $("#history-summary").textContent = `显示 ${rows.length} 条记录，共 ${filtered.length} 条`; $("#history-page").textContent = historyPage; $("#history-prev").disabled = historyPage <= 1; $("#history-next").disabled = historyPage >= pages;
}
function initHistory() {
  $$('[data-history-source]').forEach(button => button.addEventListener("click", () => { historySource = button.dataset.historySource; historyPage = 1; $$('[data-history-source]').forEach(b => b.classList.toggle("active", b === button)); renderHistory(); }));
  ["#history-format", "#history-time", "#history-search", "#history-page-size"].forEach(selector => $(selector).addEventListener("input", () => { historyPage = 1; renderHistory(); }));
  $("#history-prev").addEventListener("click", () => { historyPage--; renderHistory(); }); $("#history-next").addEventListener("click", () => { historyPage++; renderHistory(); });
  $("#history-rows").addEventListener("click", event => { const button = event.target.closest("[data-delete-history]"); if (!button) return; if (confirm("确定删除这条导出记录？文件本身不会被删除。")) { saveExportRecords(readExportRecords().filter(r => r.id !== button.dataset.deleteHistory)); renderHistory(); } });
}

window.addEventListener("beforeunload", (event) => {
  if (state.jobId && hasPendingPageEdits()) {
    event.preventDefault();
    event.returnValue = "";
  }
});
