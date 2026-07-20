"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  GENSHIN_KEYS,
  MapperConfig,
  MappingStrategy,
  NOTE_NAMES,
  ScaleMode,
  TONIC_OPTIONS,
  WHITE_MIDI_NOTES,
  isWhite,
  mapChord,
  midiName,
  signedPitchDistance,
  sourceScaleNames,
  targetScaleNames,
} from "./lib/mapping";

const COMPUTER_PIANO: Record<string, number> = {
  a: 60,
  w: 61,
  s: 62,
  e: 63,
  d: 64,
  f: 65,
  t: 66,
  g: 67,
  y: 68,
  h: 69,
  u: 70,
  j: 71,
  k: 72,
};

const SCALE_DEGREES = ["1 · 主音", "2 · 上主音", "3 · 中音", "4 · 下属音", "5 · 属音", "6 · 下中音", "7 · 导音"];

function pianoPosition(note: number) {
  const whiteBefore = WHITE_MIDI_NOTES.filter((white) => white < note).length;
  return `${(whiteBefore / WHITE_MIDI_NOTES.length) * 100}%`;
}

function signedNumber(value: number) {
  if (value > 0) return `+${value}`;
  return `${value}`;
}

function strategyCopy(strategy: MappingStrategy) {
  if (strategy === "harmony") return "先尝试和弦整体平移，再做无冲突声部分配；最适合弹唱与和弦。";
  if (strategy === "melody") return "锁定调式中心，变化音就近让位；最适合单旋律与快速跑动。";
  return "只输出能无损落到白键的音，调外音会静音；最适合检查编配。";
}

export default function Home() {
  const [sourceTonic, setSourceTonic] = useState(1);
  const [mode, setMode] = useState<ScaleMode>("major");
  const [strategy, setStrategy] = useState<MappingStrategy>("harmony");
  const [preserveMinor, setPreserveMinor] = useState(true);
  const [registerShift, setRegisterShift] = useState(0);
  const [chordWindow, setChordWindow] = useState(18);
  const [activeNotes, setActiveNotes] = useState<Set<number>>(new Set());
  const [hasPlayed, setHasPlayed] = useState(false);
  const [midiStatus, setMidiStatus] = useState<"idle" | "connecting" | "connected" | "error">("idle");
  const [midiMessage, setMidiMessage] = useState("本地控制台未打开");
  const sustainedNotes = useRef<Set<number>>(new Set());
  const sustainDown = useRef(false);

  const config = useMemo<MapperConfig>(() => ({
    sourceTonic,
    mode,
    preserveMinor,
    strategy,
    registerShift,
  }), [sourceTonic, mode, preserveMinor, strategy, registerShift]);

  const startNote = useCallback((note: number) => {
    if (note < 0 || note > 127) return;
    setHasPlayed(true);
    sustainedNotes.current.delete(note);
    setActiveNotes((current) => {
      const next = new Set(current);
      next.add(note);
      return next;
    });
  }, []);

  const stopNote = useCallback((note: number) => {
    if (sustainDown.current) {
      sustainedNotes.current.add(note);
      return;
    }
    setActiveNotes((current) => {
      const next = new Set(current);
      next.delete(note);
      return next;
    });
  }, []);

  useEffect(() => {
    const pressed = new Set<string>();
    const onKeyDown = (event: KeyboardEvent) => {
      const element = event.target as HTMLElement | null;
      if (element?.matches("input, select, textarea, button, a")) return;
      const key = event.key.toLowerCase();
      const note = COMPUTER_PIANO[key];
      if (note === undefined || pressed.has(key) || event.repeat) return;
      pressed.add(key);
      startNote(note);
    };
    const onKeyUp = (event: KeyboardEvent) => {
      const key = event.key.toLowerCase();
      const note = COMPUTER_PIANO[key];
      if (note === undefined) return;
      pressed.delete(key);
      stopNote(note);
    };
    window.addEventListener("keydown", onKeyDown);
    window.addEventListener("keyup", onKeyUp);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
      window.removeEventListener("keyup", onKeyUp);
    };
  }, [startNote, stopNote]);

  const connectMidi = useCallback(() => {
    setMidiStatus("connecting");
    setMidiMessage("正在打开 127.0.0.1:17321…");
    window.open("http://127.0.0.1:17321", "_blank", "noopener,noreferrer");
    window.setTimeout(() => {
      setMidiStatus("idle");
      setMidiMessage("由本地 Python 独占 MIDI 端口");
    }, 900);
  }, []);

  const tonicAnchor = 60 + signedPitchDistance(0, sourceTonic);
  const demoNotes = mode === "major"
    ? [tonicAnchor, tonicAnchor + 4, tonicAnchor + 7]
    : [tonicAnchor, tonicAnchor + 3, tonicAnchor + 7];
  const liveNotes = [...activeNotes].sort((a, b) => a - b);
  const displayNotes = liveNotes.length ? liveNotes : demoNotes;
  const mapping = useMemo(() => mapChord(displayNotes, config), [displayNotes.join(","), config]);
  const sourceNames = sourceScaleNames(config);
  const targetNames = targetScaleNames(config);
  const inputHighlights = new Set(displayNotes);
  const outputHighlights = new Set(
    mapping.assignments.flatMap((assignment) => assignment.output === null ? [] : [assignment.output]),
  );
  const blackNotes = Array.from({ length: 36 }, (_, index) => 48 + index).filter((note) => !isWhite(note));
  const qualityLabel = mapping.quality === "lossless" ? "无损映射" : mapping.quality === "adapted" ? "已智能改编" : "存在省略音";

  const clearNotes = () => {
    sustainedNotes.current.clear();
    sustainDown.current = false;
    setActiveNotes(new Set());
    setHasPlayed(false);
  };

  const exportConfig = () => {
    const payload = {
      source_tonic: sourceTonic,
      mode,
      strategy,
      preserve_minor: preserveMinor,
      register_shift: registerShift,
      chord_window_ms: chordWindow,
    };
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = "lyre-bridge-config.json";
    anchor.click();
    URL.revokeObjectURL(url);
  };

  return (
    <main>
      <header className="site-header">
        <a className="brand" href="#top" aria-label="原琴律桥首页">
          <span className="brand-mark" aria-hidden="true">♬</span>
          <span>
            <strong>原琴律桥</strong>
            <small>LYRE BRIDGE</small>
          </span>
        </a>
        <div className="header-actions">
          <span className={`status-pill ${midiStatus}`}>
            <i aria-hidden="true" />
            {midiMessage}
          </span>
          <button className="button primary" type="button" onClick={connectMidi} disabled={midiStatus === "connecting"}>
            <span aria-hidden="true">⌁</span>
            打开本地控制台
          </button>
        </div>
      </header>

      <section className="hero" id="top">
        <div>
          <p className="eyebrow"><span /> 不是“就近吸附”，是和弦级重编配</p>
          <h1>弹你熟悉的调，<br /><em>落在原琴的白键上。</em></h1>
          <p className="hero-copy">
            本地 Python 独占电钢琴端口，网页只负责改参数和显示映射；这样不会再出现浏览器与脚本争抢 Roland 端口的问题。
          </p>
        </div>
        <div className="hero-route" aria-label="当前映射方向">
          <div>
            <span>你的原调</span>
            <strong>{NOTE_NAMES[sourceTonic]} {mode === "major" ? "大调" : "小调"}</strong>
            <small>{sourceNames.join(" · ")}</small>
          </div>
          <b aria-hidden="true">→</b>
          <div>
            <span>原琴键盘</span>
            <strong>{mapping.targetLabel}</strong>
            <small>{targetNames.join(" · ")}</small>
          </div>
        </div>
      </section>

      <section className="workbench" aria-label="映射工作台">
        <aside className="control-panel">
          <div className="panel-heading">
            <span>01</span>
            <div>
              <p>映射设置</p>
              <h2>先告诉我你在弹什么调</h2>
            </div>
          </div>

          <label className="field-label" htmlFor="source-tonic">原曲主音</label>
          <select id="source-tonic" value={sourceTonic} onChange={(event) => setSourceTonic(Number(event.target.value))}>
            {TONIC_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
          </select>

          <div className="field-group">
            <span className="field-label">调式</span>
            <div className="segmented two">
              <button className={mode === "major" ? "active" : ""} type="button" onClick={() => setMode("major")}>大调</button>
              <button className={mode === "minor" ? "active" : ""} type="button" onClick={() => setMode("minor")}>小调</button>
            </div>
          </div>

          {mode === "minor" && (
            <label className="toggle-row">
              <span>
                <strong>保留小调听感</strong>
                <small>映射到 A 小调，仍使用原琴的 C 大调白键</small>
              </span>
              <input type="checkbox" checked={preserveMinor} onChange={(event) => setPreserveMinor(event.target.checked)} />
              <i aria-hidden="true" />
            </label>
          )}

          <div className="field-group">
            <span className="field-label">冲突处理</span>
            <div className="strategy-stack">
              {([
                ["harmony", "和声优先", "整体保形"],
                ["melody", "旋律优先", "音级稳定"],
                ["strict", "严格调内", "变化音静音"],
              ] as const).map(([value, label, caption]) => (
                <button key={value} className={strategy === value ? "active" : ""} type="button" onClick={() => setStrategy(value)}>
                  <span><i />{label}</span><small>{caption}</small>
                </button>
              ))}
            </div>
            <p className="helper-copy">{strategyCopy(strategy)}</p>
          </div>

          <div className="range-row">
            <label htmlFor="register">手动八度 <strong>{signedNumber(registerShift)}</strong></label>
            <input id="register" type="range" min="-2" max="2" step="1" value={registerShift} onChange={(event) => setRegisterShift(Number(event.target.value))} />
            <div><span>-2</span><span>原位</span><span>+2</span></div>
          </div>

          <div className="range-row compact">
            <label htmlFor="window">和弦识别窗口 <strong>{chordWindow} ms</strong></label>
            <input id="window" type="range" min="8" max="40" step="1" value={chordWindow} onChange={(event) => setChordWindow(Number(event.target.value))} />
            <p>更低更跟手，更高更容易把琶音识别为同一组。</p>
          </div>

          <div className="download-stack">
            <a className="button dark" href="/lyre-bridge-local.zip" download>
              <span aria-hidden="true">↓</span> 下载本地一键版
            </a>
            <button className="text-button" type="button" onClick={exportConfig}>导出当前设置 <span>↗</span></button>
          </div>
        </aside>

        <div className="stage-panel">
          <div className="stage-toolbar">
            <div>
              <span className="live-dot" />
              <strong>{liveNotes.length ? "实时输入" : "示例预览"}</strong>
              <small>{liveNotes.length ? `${liveNotes.length} 个输入音` : "按 A W S E D… 或点击琴键试弹"}</small>
            </div>
            <div className="quality-group">
              <span className={`quality ${mapping.quality}`}>{qualityLabel}</span>
              <button type="button" onClick={clearNotes}>清空</button>
            </div>
          </div>

          <div className="piano-block">
            <div className="keyboard-title">
              <span>电钢琴输入 · MIDI C3–B5</span>
              <small>黑键也会被识别</small>
            </div>
            <div className="piano input-piano" aria-label="电钢琴输入键盘">
              <div className="white-keys">
                {WHITE_MIDI_NOTES.map((note) => (
                  <button
                    key={note}
                    className={inputHighlights.has(note) ? (liveNotes.length ? "pressed" : "preview") : ""}
                    type="button"
                    aria-label={`输入 ${midiName(note)}`}
                    onPointerDown={(event) => { event.currentTarget.setPointerCapture(event.pointerId); startNote(note); }}
                    onPointerUp={() => stopNote(note)}
                    onPointerCancel={() => stopNote(note)}
                  >
                    {note % 12 === 0 && <small>{midiName(note)}</small>}
                  </button>
                ))}
              </div>
              {blackNotes.map((note) => (
                <button
                  key={note}
                  className={`black-key ${inputHighlights.has(note) ? (liveNotes.length ? "pressed" : "preview") : ""}`}
                  style={{ left: pianoPosition(note) }}
                  type="button"
                  aria-label={`输入 ${midiName(note)}`}
                  onPointerDown={(event) => { event.currentTarget.setPointerCapture(event.pointerId); startNote(note); }}
                  onPointerUp={() => stopNote(note)}
                  onPointerCancel={() => stopNote(note)}
                />
              ))}
            </div>
          </div>

          <div className="mapping-rail" aria-label="映射处理流程">
            <div><i>1</i><span>调式归一</span><strong>{signedNumber(mapping.baseTranspose)} 半音</strong></div>
            <b>›</b>
            <div><i>2</i><span>整体八度</span><strong>{signedNumber(mapping.octaveShift / 12)} 八度</strong></div>
            <b>›</b>
            <div><i>3</i><span>和弦分配</span><strong>避开 {mapping.conflictsAvoided} 个冲突</strong></div>
          </div>

          <div className="piano-block output-block">
            <div className="keyboard-title">
              <span>原琴输出 · 21 键</span>
              <small>低音 / 中音 / 高音</small>
            </div>
            <div className="lyre-keys" aria-label="原神原琴输出键盘">
              {WHITE_MIDI_NOTES.map((note, index) => (
                <div key={note} className={`lyre-key octave-${Math.floor(index / 7)} ${outputHighlights.has(note) ? "pressed" : ""}`}>
                  <span>{midiName(note)}</span>
                  <strong>{GENSHIN_KEYS[index]}</strong>
                  {outputHighlights.has(note) && <i aria-hidden="true" />}
                </div>
              ))}
            </div>
          </div>

          <div className="live-readout">
            <div className="readout-heading">
              <span>当前映射解释</span>
              {mapping.adaptiveOffset !== 0 && <strong>和弦整体偏移 {signedNumber(mapping.adaptiveOffset)} 半音</strong>}
            </div>
            <div className="assignment-list">
              {mapping.assignments.map((assignment) => (
                <div key={assignment.input} className={assignment.output === null ? "omitted" : ""}>
                  <span className="note-chip">{midiName(assignment.input)}</span>
                  <b>→</b>
                  <span className="note-chip output">{assignment.output === null ? "静音" : midiName(assignment.output)}</span>
                  <kbd>{assignment.key || "—"}</kbd>
                  <p>{assignment.reason}</p>
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>

      <section className="rule-section">
        <div className="section-intro">
          <p className="eyebrow"><span /> 规则透明，听感才可控</p>
          <h2>这套映射为什么更科学？</h2>
          <p>原琴只有 21 个自然音，半音信息不可能全部无损保留。好的算法不会假装没有损失，而是先保护最重要的音乐结构，再明确标出妥协发生在哪里。</p>
        </div>
        <div className="rule-grid">
          <article>
            <span>01</span>
            <i className="rule-icon">≋</i>
            <h3>音级优先，而非黑键吸附</h3>
            <p>调内的 1–7 级直接映射到目标音级，因此主音、属音与和弦功能保持稳定。</p>
          </article>
          <article>
            <span>02</span>
            <i className="rule-icon">⌁</i>
            <h3>和弦作为整体做决定</h3>
            <p>同时到达的音共享八度和局部偏移，避免每个音各自折返后把和弦拆散。</p>
          </article>
          <article>
            <span>03</span>
            <i className="rule-icon">⇅</i>
            <h3>输出键一对一占用</h3>
            <p>动态规划保持声部从低到高的顺序，并禁止两个输入音抢占同一个原琴键。</p>
          </article>
          <article>
            <span>04</span>
            <i className="rule-icon">◇</i>
            <h3>变化音诚实降级</h3>
            <p>先尝试整体保形；做不到时才就近让位或省略，并在实时解释里明确提示。</p>
          </article>
        </div>
      </section>

      <section className="scale-map-section">
        <div className="map-heading">
          <div>
            <p className="eyebrow"><span /> 当前调式映射表</p>
            <h2>{NOTE_NAMES[sourceTonic]} {mode === "major" ? "大调" : "小调"} → {mapping.targetLabel}</h2>
          </div>
          <p>每个音级在三个八度分别对应一枚原琴键。先记“音级去向”，再记键盘字母，会比死背 21 个映射快得多。</p>
        </div>
        <div className="degree-map">
          {SCALE_DEGREES.map((degree, index) => (
            <div key={degree}>
              <span>{degree}</span>
              <strong>{sourceNames[index]}</strong>
              <b>→</b>
              <strong>{targetNames[index]}</strong>
              <div className="key-triplet">
                <kbd>{GENSHIN_KEYS[index]}</kbd>
                <kbd>{GENSHIN_KEYS[index + 7]}</kbd>
                <kbd>{GENSHIN_KEYS[index + 14]}</kbd>
              </div>
            </div>
          ))}
        </div>
      </section>

      <section className="companion-callout">
        <div>
          <span className="callout-mark">⌘</span>
          <div>
            <p>一个本地地址，同时完成参数控制、可视化与游戏送键</p>
            <h2>双击启动后，所有操作都在本地网页里完成。</h2>
          </div>
        </div>
        <div className="callout-actions">
            <a className="button light" href="/lyre-bridge-local.zip" download>下载本地一键版 <span>↓</span></a>
          <button className="button ghost" type="button" onClick={exportConfig}>导出配置</button>
        </div>
      </section>

      <footer>
        <div className="brand compact-brand"><span className="brand-mark">♬</span><span><strong>原琴律桥</strong><small>LYRE BRIDGE</small></span></div>
        <p>为 21 键原琴设计的调式映射与实时练习工具</p>
        <span>{hasPlayed ? "本次练习已捕获演示输入" : "下载本地版后连接你的电钢琴"}</span>
      </footer>
    </main>
  );
}
