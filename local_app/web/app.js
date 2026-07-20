const NOTE_NAMES = ["C", "D♭", "D", "E♭", "E", "F", "G♭", "G", "A♭", "A", "B♭", "B"];
const WHITE_PCS = new Set([0, 2, 4, 5, 7, 9, 11]);
const WHITE_NOTES = Array.from({ length: 36 }, (_, index) => 48 + index).filter((note) => WHITE_PCS.has(note % 12));
const BLACK_NOTES = Array.from({ length: 36 }, (_, index) => 48 + index).filter((note) => !WHITE_PCS.has(note % 12));
const GENSHIN_KEYS = "ZXCVBNMASDFGHJQWERTYU".split("");
const STRATEGY_HELP = {
  harmony: "先尝试和弦整体平移，再做无冲突声部分配。",
  melody: "锁定调式中心，变化音就近让位，适合单旋律。",
  strict: "只输出能无损落到白键的音，调外音会静音。",
};

const elements = Object.fromEntries([
  "connectionDot", "connectionTitle", "connectionDetail", "deviceSelect", "refreshButton", "retryButton",
  "panicButton", "outputToggle", "outputHint", "errorBanner", "errorText", "technicalError", "errorRetryButton",
  "tonicSelect", "minorPreserveRow", "preserveMinor", "strategyHelp", "registerRange", "registerValue",
  "windowRange", "windowValue", "liveDot", "stageStatus", "stageSub", "targetChip", "sustainChip",
  "whiteKeys", "blackKeys", "lyreKeys", "transposeValue", "octaveValue", "conflictValue", "pipelineOutput",
  "eventMeta", "assignmentList", "footerStatus", "toast",
].map((id) => [id, document.getElementById(id)]));

let socket = null;
let currentState = null;
let applyingState = false;
let reconnectTimer = null;
let configTimer = null;

function midiName(note) {
  return `${NOTE_NAMES[((note % 12) + 12) % 12]}${Math.floor(note / 12) - 1}`;
}

function signed(value) {
  return value > 0 ? `+${value}` : String(value);
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (character) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;",
  })[character]);
}

function send(message) {
  if (socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify(message));
}

function showToast(message) {
  elements.toast.textContent = message;
  elements.toast.hidden = false;
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => { elements.toast.hidden = true; }, 2600);
}

function buildKeyboards() {
  elements.whiteKeys.innerHTML = WHITE_NOTES.map((note) => `
    <div class="white-key" data-note="${note}"><small>${note % 12 === 0 ? midiName(note) : ""}</small></div>
  `).join("");
  elements.blackKeys.innerHTML = BLACK_NOTES.map((note) => {
    const before = WHITE_NOTES.filter((white) => white < note).length;
    const left = (before / WHITE_NOTES.length) * 100;
    return `<div class="black-key" data-note="${note}" style="left:${left}%"></div>`;
  }).join("");
  elements.lyreKeys.innerHTML = WHITE_NOTES.map((note, index) => `
    <div class="lyre-key octave-${Math.floor(index / 7)}" data-note="${note}">
      <span>${midiName(note)}</span><strong>${GENSHIN_KEYS[index]}</strong><i></i>
    </div>
  `).join("");
}

function getRadio(name) {
  return document.querySelector(`input[name="${name}"]:checked`)?.value;
}

function collectConfig() {
  return {
    source_tonic: Number(elements.tonicSelect.value),
    mode: getRadio("mode"),
    strategy: getRadio("strategy"),
    preserve_minor: elements.preserveMinor.checked,
    register_shift: Number(elements.registerRange.value),
    chord_window_ms: Number(elements.windowRange.value),
  };
}

function queueConfig() {
  if (applyingState) return;
  renderLocalControlLabels();
  clearTimeout(configTimer);
  configTimer = setTimeout(() => send({ type: "config", config: collectConfig() }), 70);
}

function renderLocalControlLabels() {
  const config = collectConfig();
  elements.minorPreserveRow.hidden = config.mode !== "minor";
  elements.strategyHelp.textContent = STRATEGY_HELP[config.strategy];
  elements.registerValue.textContent = config.register_shift === 0 ? "原位" : `${signed(config.register_shift)} 八度`;
  elements.windowValue.textContent = `${config.chord_window_ms} ms`;
}

function applyConfig(config) {
  applyingState = true;
  elements.tonicSelect.value = String(config.source_tonic);
  document.querySelector(`input[name="mode"][value="${config.mode}"]`).checked = true;
  document.querySelector(`input[name="strategy"][value="${config.strategy}"]`).checked = true;
  elements.preserveMinor.checked = config.preserve_minor;
  elements.registerRange.value = String(config.register_shift);
  elements.windowRange.value = String(config.chord_window_ms);
  renderLocalControlLabels();
  applyingState = false;
}

function renderDevices(midi) {
  const known = new Set(Array.from(elements.deviceSelect.options).map((option) => option.value));
  const wanted = new Set(midi.devices);
  const changed = known.size !== wanted.size || [...wanted].some((name) => !known.has(name));
  if (changed) {
    elements.deviceSelect.innerHTML = midi.devices.length
      ? midi.devices.map((name) => `<option value="${escapeHtml(name)}">${escapeHtml(name)}</option>`).join("")
      : `<option value="">未发现 MIDI 设备</option>`;
  }
  if (midi.selected && midi.devices.includes(midi.selected)) elements.deviceSelect.value = midi.selected;
  elements.deviceSelect.disabled = !midi.devices.length;
}

function renderConnection(state) {
  const midi = state.midi;
  renderDevices(midi);
  elements.connectionDot.className = `dot ${midi.connected ? "online" : midi.error ? "error" : "waiting"}`;
  elements.connectionTitle.textContent = midi.connected ? "MIDI 已连接" : midi.error ? "MIDI 暂不可用" : "正在扫描 MIDI";
  elements.connectionDetail.textContent = midi.connected ? midi.selected : (midi.error || "请连接电钢琴");
  elements.errorBanner.hidden = !midi.error;
  elements.errorText.textContent = midi.error || "";
  elements.technicalError.textContent = midi.technical_error || "";
  elements.technicalError.hidden = !midi.technical_error;
  elements.outputToggle.disabled = !midi.connected;
  elements.footerStatus.textContent = midi.connected ? `已连接 ${midi.selected}` : "等待 MIDI 设备";
}

function renderOutput(state) {
  elements.outputToggle.checked = state.output_enabled;
  elements.outputHint.textContent = state.output_enabled ? "已向当前前台程序发送按键" : "当前只可视化，不发送按键";
  elements.pipelineOutput.textContent = state.output_enabled ? "已启用" : "已关闭";
  elements.pipelineOutput.className = state.output_enabled ? "enabled" : "";
  if (state.output_error) showToast(state.output_error);
}

function renderPianos(state) {
  const inputs = new Set(state.active_notes);
  const outputs = new Set(state.active_outputs);
  document.querySelectorAll("[data-note]").forEach((key) => {
    const note = Number(key.dataset.note);
    const active = key.classList.contains("lyre-key") ? outputs.has(note) : inputs.has(note);
    key.classList.toggle("pressed", active);
  });
  elements.liveDot.className = `dot ${inputs.size ? "live" : ""}`;
  elements.stageStatus.textContent = inputs.size ? `实时输入 · ${inputs.size} 个音` : "等待 MIDI 输入";
  elements.stageSub.textContent = inputs.size ? "映射已由本地 Python 计算并同步" : "弹下电钢琴后会在这里显示完整执行流";
  elements.sustainChip.textContent = `延音踏板：${state.sustain_down ? "踩下" : "抬起"}`;
  elements.sustainChip.classList.toggle("active", state.sustain_down);
}

function renderMapping(state) {
  const config = state.config;
  const tonic = NOTE_NAMES[config.source_tonic];
  const mode = config.mode === "major" ? "大调" : "小调";
  elements.targetChip.textContent = `${tonic} ${mode} → ${state.target_label}`;
  const targetTonic = config.mode === "minor" && config.preserve_minor ? 9 : 0;
  let transpose = ((targetTonic - config.source_tonic) % 12 + 12) % 12;
  if (transpose > 6) transpose -= 12;
  elements.transposeValue.textContent = `${signed(transpose)} 半音`;
  const event = state.last_event || {};
  elements.octaveValue.textContent = `${signed((event.octave_shift || 0) / 12)} 八度`;
  elements.conflictValue.textContent = `避开 ${event.conflicts_avoided || 0} 个冲突`;
  const rows = state.active_assignments?.length ? state.active_assignments : (event.assignments || []);
  elements.eventMeta.textContent = event.adaptive_offset
    ? `和弦整体偏移 ${signed(event.adaptive_offset)} 半音`
    : rows.length ? `${rows.length} 个音已完成分配` : "尚未收到音符";
  if (!rows.length) {
    elements.assignmentList.innerHTML = `<div class="empty-state"><span>⌁</span><p>${event.notice || "连接 Roland 后弹一个和弦，系统会逐音解释为什么映射到对应原琴键。"}</p></div>`;
    return;
  }
  elements.assignmentList.innerHTML = rows.map((row) => `
    <div class="assignment ${row.output == null ? "omitted" : ""}">
      <span class="note-chip">${row.input_name}</span><b>→</b>
      <span class="note-chip output">${row.output_name}</span><kbd>${row.key}</kbd>
      <p>${row.reason}</p>
    </div>
  `).join("");
}

function renderState(state) {
  currentState = state;
  applyConfig(state.config);
  renderConnection(state);
  renderOutput(state);
  renderPianos(state);
  renderMapping(state);
}

function connect() {
  clearTimeout(reconnectTimer);
  const protocol = location.protocol === "https:" ? "wss:" : "ws:";
  socket = new WebSocket(`${protocol}//${location.host}/ws`);
  socket.addEventListener("open", () => {
    elements.footerStatus.textContent = "本地服务已连接";
  });
  socket.addEventListener("message", (event) => {
    const message = JSON.parse(event.data);
    if (message.type === "state") renderState(message.state);
    if (message.type === "error") showToast(message.message);
  });
  socket.addEventListener("close", () => {
    elements.connectionDot.className = "dot error";
    elements.connectionTitle.textContent = "本地服务已断开";
    elements.connectionDetail.textContent = "正在自动重连…";
    elements.footerStatus.textContent = "本地服务重连中";
    reconnectTimer = setTimeout(connect, 1000);
  });
  socket.addEventListener("error", () => socket.close());
}

document.querySelectorAll("input[name='mode'], input[name='strategy']").forEach((input) => input.addEventListener("change", queueConfig));
[elements.tonicSelect, elements.preserveMinor, elements.registerRange, elements.windowRange].forEach((input) => input.addEventListener("input", queueConfig));
elements.deviceSelect.addEventListener("change", () => send({ type: "device", name: elements.deviceSelect.value }));
elements.refreshButton.addEventListener("click", () => send({ type: "refresh_devices" }));
elements.retryButton.addEventListener("click", () => send({ type: "retry" }));
elements.errorRetryButton.addEventListener("click", () => send({ type: "retry" }));
elements.panicButton.addEventListener("click", () => send({ type: "panic" }));
elements.outputToggle.addEventListener("change", () => send({ type: "output", enabled: elements.outputToggle.checked }));

buildKeyboards();
renderLocalControlLabels();
connect();
