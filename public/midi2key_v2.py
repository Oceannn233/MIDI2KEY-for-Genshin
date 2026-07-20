# -*- coding: utf-8 -*-
"""Lyre Bridge v2 - MIDI electric piano to Genshin lyre keyboard mapper.

Install:
    py -m pip install mido python-rtmidi pynput

Examples:
    py midi2key_v2.py --source Db --mode major
    py midi2key_v2.py --source D --mode minor --strategy harmony
    py midi2key_v2.py --config lyre-bridge-config.json

The browser visualizer explains the same mapping model. This companion is the
part that can send Windows keyboard events while the game is focused.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple


NOTE_NAMES = ("C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B")
MAJOR_INTERVALS = (0, 2, 4, 5, 7, 9, 11)
MINOR_INTERVALS = (0, 2, 3, 5, 7, 8, 10)
WHITE_PITCH_CLASSES = frozenset(MAJOR_INTERVALS)
WHITE_MIDI_NOTES = tuple(note for note in range(48, 84) if note % 12 in WHITE_PITCH_CLASSES)
GENSHIN_KEYS = tuple("ZXCVBNMASDFGHJQWERTYU")
KEY_BY_MIDI = dict(zip(WHITE_MIDI_NOTES, GENSHIN_KEYS))

TONIC_ALIASES = {
    "c": 0,
    "c#": 1,
    "db": 1,
    "d♭": 1,
    "d": 2,
    "d#": 3,
    "eb": 3,
    "e♭": 3,
    "e": 4,
    "f": 5,
    "f#": 6,
    "gb": 6,
    "g♭": 6,
    "g": 7,
    "g#": 8,
    "ab": 8,
    "a♭": 8,
    "a": 9,
    "a#": 10,
    "bb": 10,
    "b♭": 10,
    "b": 11,
}


def mod(value: int, divisor: int = 12) -> int:
    return value % divisor


def signed_pitch_distance(source: int, target: int) -> int:
    upward = mod(target - source)
    return upward - 12 if upward > 6 else upward


def midi_name(note: int) -> str:
    return f"{NOTE_NAMES[note % 12]}{note // 12 - 1}"


def parse_tonic(value: object) -> int:
    if isinstance(value, int) and 0 <= value <= 11:
        return value
    text = str(value).strip().lower()
    if text.isdigit() and 0 <= int(text) <= 11:
        return int(text)
    if text not in TONIC_ALIASES:
        raise ValueError(f"未知主音 {value!r}；请使用 C、Db、F# 等名称")
    return TONIC_ALIASES[text]


@dataclass(frozen=True)
class MapperConfig:
    source_tonic: int = 1
    mode: str = "major"
    strategy: str = "harmony"
    preserve_minor: bool = True
    register_shift: int = 0
    chord_window_ms: int = 18

    def validate(self) -> "MapperConfig":
        if self.mode not in {"major", "minor"}:
            raise ValueError("mode 必须是 major 或 minor")
        if self.strategy not in {"harmony", "melody", "strict"}:
            raise ValueError("strategy 必须是 harmony、melody 或 strict")
        if not -2 <= self.register_shift <= 2:
            raise ValueError("register_shift 必须在 -2 到 +2 之间")
        if not 4 <= self.chord_window_ms <= 80:
            raise ValueError("chord_window_ms 建议在 4 到 80 ms 之间")
        return self


@dataclass(frozen=True)
class NoteAnalysis:
    note: int
    ideal: int
    degree: int
    base_transpose: int


@dataclass(frozen=True)
class GroupMapping:
    assignments: Dict[int, Optional[int]]
    octave_shift: int
    adaptive_offset: int
    conflicts_avoided: int


def analyse_note(note: int, config: MapperConfig) -> NoteAnalysis:
    source_intervals = MAJOR_INTERVALS if config.mode == "major" else MINOR_INTERVALS
    preserve_mode = config.mode == "major" or config.preserve_minor
    target_intervals = source_intervals if preserve_mode else MAJOR_INTERVALS
    target_tonic = 9 if config.mode == "minor" and config.preserve_minor else 0
    base_transpose = signed_pitch_distance(config.source_tonic, target_tonic)
    relative_pc = mod(note - config.source_tonic)
    degree = source_intervals.index(relative_pc) if relative_pc in source_intervals else -1
    chromatic_ideal = note + base_transpose
    if degree < 0:
        return NoteAnalysis(note, chromatic_ideal, degree, base_transpose)
    expected_pc = mod(target_tonic + target_intervals[degree])
    correction = signed_pitch_distance(mod(chromatic_ideal), expected_pc)
    return NoteAnalysis(note, chromatic_ideal + correction, degree, base_transpose)


def choose_octave_shift(ideals: Sequence[int], requested_register: int) -> int:
    requested = requested_register * 12
    best_shift = requested
    best_score = math.inf
    for automatic in range(-72, 73, 12):
        shift = requested + automatic
        score = abs(automatic) * 0.05
        for ideal in ideals:
            shifted = ideal + shift
            if shifted < 48:
                score += (48 - shifted) ** 2 * 8
            if shifted > 83:
                score += (shifted - 83) ** 2 * 8
        if score < best_score:
            best_score = score
            best_shift = shift
    return best_shift


def choose_adaptive_offset(ideals: Sequence[int], strategy: str) -> int:
    if strategy != "harmony" or len(ideals) < 2:
        return 0
    base_playable = sum(note % 12 in WHITE_PITCH_CLASSES for note in ideals)
    best_offset = 0
    best_score = base_playable * 12
    for offset in range(-2, 3):
        playable = sum((note + offset) % 12 in WHITE_PITCH_CLASSES for note in ideals)
        score = playable * 12 - abs(offset) * 2.5
        if score > best_score:
            best_offset, best_score = offset, score
    improved = sum((note + best_offset) % 12 in WHITE_PITCH_CLASSES for note in ideals)
    if improved >= base_playable + 2 and improved >= math.ceil(len(ideals) * 0.75):
        return best_offset
    return 0


def nearest_white(note: int) -> int:
    return min(WHITE_MIDI_NOTES, key=lambda candidate: abs(candidate - note))


def map_note_group(
    notes: Iterable[int],
    config: MapperConfig,
    reserved_outputs: Optional[Set[int]] = None,
    locked_octave_shift: Optional[int] = None,
) -> GroupMapping:
    ordered = sorted(set(notes))
    reserved = reserved_outputs or set()
    if not ordered:
        return GroupMapping({}, locked_octave_shift or 0, 0, 0)

    analyses = [analyse_note(note, config) for note in ordered]
    octave_shift = locked_octave_shift
    if octave_shift is None:
        octave_shift = choose_octave_shift([item.ideal for item in analyses], config.register_shift)
    shifted = [item.ideal + octave_shift for item in analyses]
    adaptive_offset = choose_adaptive_offset(shifted, config.strategy)
    ideals = [note + adaptive_offset for note in shifted]
    candidates = [note for note in WHITE_MIDI_NOTES if note not in reserved]
    naive = [nearest_white(note) for note in ideals]
    conflicts_avoided = len(naive) - len(set(naive))

    rows, columns = len(ordered) + 1, len(candidates) + 1
    costs = [[math.inf] * columns for _ in range(rows)]
    previous: List[List[Optional[Tuple[int, int, str]]]] = [
        [None] * columns for _ in range(rows)
    ]
    costs[0][0] = 0.0

    def update(next_i: int, next_j: int, cost: float, prev_i: int, prev_j: int, action: str) -> None:
        if cost < costs[next_i][next_j]:
            costs[next_i][next_j] = cost
            previous[next_i][next_j] = (prev_i, prev_j, action)

    for i in range(rows):
        for j in range(columns):
            current = costs[i][j]
            if not math.isfinite(current):
                continue
            if j < len(candidates):
                update(i, j + 1, current, i, j, "skip")
            if i >= len(ordered):
                continue

            analysis = analyses[i]
            ideal = ideals[i]
            accidental = analysis.degree < 0
            exact_playable = ideal % 12 in WHITE_PITCH_CLASSES
            omit_cost = 24 if accidental else 58
            update(i + 1, j, current + omit_cost, i, j, "omit")

            if j < len(candidates) and not (config.strategy == "strict" and not exact_playable):
                candidate = candidates[j]
                distance = abs(candidate - ideal)
                multiplier = 4.2 if config.strategy == "melody" else 3.2
                assignment_cost = distance * multiplier + max(0, distance - 2) ** 2 * 1.5
                if exact_playable and candidate % 12 != ideal % 12:
                    assignment_cost += 20
                if not accidental and adaptive_offset == 0 and candidate % 12 != ideal % 12:
                    assignment_cost += 26
                update(i + 1, j + 1, current + assignment_cost, i, j, "assign")

    best_j = min(range(columns), key=lambda j: costs[len(ordered)][j])
    assignments: Dict[int, Optional[int]] = {}
    cursor_i, cursor_j = len(ordered), best_j
    while cursor_i > 0 or cursor_j > 0:
        step = previous[cursor_i][cursor_j]
        if step is None:
            break
        prev_i, prev_j, action = step
        if action == "assign":
            assignments[ordered[cursor_i - 1]] = candidates[cursor_j - 1]
        elif action == "omit":
            assignments[ordered[cursor_i - 1]] = None
        cursor_i, cursor_j = prev_i, prev_j

    return GroupMapping(assignments, octave_shift, adaptive_offset, conflicts_avoided)


class LyreEngine:
    def __init__(self, config: MapperConfig, keyboard: object, dry_run: bool = False) -> None:
        self.config = config
        self.keyboard = keyboard
        self.dry_run = dry_run
        self.held_notes: Set[int] = set()
        self.sustained_notes: Set[int] = set()
        self.pending_notes: Dict[int, float] = {}
        self.active_mapping: Dict[int, int] = {}
        self.output_refs: Counter[int] = Counter()
        self.sustain_down = False
        self.locked_octave_shift: Optional[int] = None

    def queue_note_on(self, note: int) -> None:
        if note in self.held_notes:
            return
        self.held_notes.add(note)
        self.sustained_notes.discard(note)
        if note not in self.active_mapping:
            self.pending_notes[note] = time.monotonic()

    def note_off(self, note: int) -> None:
        self.held_notes.discard(note)
        if note in self.pending_notes:
            self.flush_pending(force=True)
        if self.sustain_down:
            self.sustained_notes.add(note)
        else:
            self.release_note(note)

    def set_sustain(self, enabled: bool) -> None:
        if enabled == self.sustain_down:
            return
        self.sustain_down = enabled
        if not enabled:
            releasing = [note for note in self.sustained_notes if note not in self.held_notes]
            self.sustained_notes.clear()
            for note in releasing:
                self.release_note(note)

    def flush_pending(self, force: bool = False) -> None:
        if not self.pending_notes:
            return
        oldest = min(self.pending_notes.values())
        elapsed_ms = (time.monotonic() - oldest) * 1000
        if not force and elapsed_ms < self.config.chord_window_ms:
            return

        notes = sorted(self.pending_notes)
        self.pending_notes.clear()
        reserved = set(self.active_mapping.values())
        mapping = map_note_group(
            notes,
            self.config,
            reserved_outputs=reserved,
            locked_octave_shift=self.locked_octave_shift,
        )
        if self.locked_octave_shift is None:
            self.locked_octave_shift = mapping.octave_shift

        rendered = []
        for note in notes:
            output = mapping.assignments.get(note)
            if output is None:
                rendered.append(f"{midi_name(note)}→省略")
                continue
            self.active_mapping[note] = output
            key = KEY_BY_MIDI[output]
            if self.output_refs[output] == 0 and not self.dry_run:
                self.keyboard.press(key.lower())
            self.output_refs[output] += 1
            rendered.append(f"{midi_name(note)}→{midi_name(output)}[{key}]")

        extra = ""
        if mapping.adaptive_offset:
            extra += f" | 和弦整体偏移 {mapping.adaptive_offset:+d}"
        if mapping.conflicts_avoided:
            extra += f" | 避开 {mapping.conflicts_avoided} 个按键冲突"
        print("  " + "  ".join(rendered) + extra)

    def release_note(self, note: int) -> None:
        self.pending_notes.pop(note, None)
        output = self.active_mapping.pop(note, None)
        if output is None:
            if not self.active_mapping and not self.pending_notes:
                self.locked_octave_shift = None
            return
        self.output_refs[output] = max(0, self.output_refs[output] - 1)
        if self.output_refs[output] == 0:
            if not self.dry_run:
                self.keyboard.release(KEY_BY_MIDI[output].lower())
            del self.output_refs[output]
        if not self.active_mapping and not self.pending_notes:
            self.locked_octave_shift = None

    def process_message(self, message: object) -> None:
        message_type = getattr(message, "type", "")
        if message_type == "note_on" and getattr(message, "velocity", 0) > 0:
            self.queue_note_on(int(message.note))
        elif message_type == "note_off" or (message_type == "note_on" and getattr(message, "velocity", 0) == 0):
            self.note_off(int(message.note))
        elif message_type == "control_change" and getattr(message, "control", -1) == 64:
            self.set_sustain(getattr(message, "value", 0) >= 64)

    def panic(self) -> None:
        if not self.dry_run:
            for output in list(self.output_refs):
                try:
                    self.keyboard.release(KEY_BY_MIDI[output].lower())
                except Exception:
                    pass
        self.pending_notes.clear()
        self.active_mapping.clear()
        self.output_refs.clear()
        self.held_notes.clear()
        self.sustained_notes.clear()
        self.locked_octave_shift = None


def load_json_config(path: Optional[str]) -> Dict[str, object]:
    if not path:
        return {}
    with Path(path).open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError("配置文件顶层必须是 JSON 对象")
    return value


def build_config(args: argparse.Namespace) -> MapperConfig:
    raw = load_json_config(args.config)
    source = args.source if args.source is not None else raw.get("source_tonic", 1)
    mode = args.mode if args.mode is not None else str(raw.get("mode", "major"))
    strategy = args.strategy if args.strategy is not None else str(raw.get("strategy", "harmony"))
    register = args.register if args.register is not None else int(raw.get("register_shift", 0))
    window = args.window if args.window is not None else int(raw.get("chord_window_ms", 18))
    preserve = bool(raw.get("preserve_minor", True))
    if args.flatten_minor:
        preserve = False
    return MapperConfig(
        source_tonic=parse_tonic(source),
        mode=mode,
        strategy=strategy,
        preserve_minor=preserve,
        register_shift=register,
        chord_window_ms=window,
    ).validate()


def choose_device(names: Sequence[str], requested: Optional[str]) -> str:
    if requested:
        if requested.isdigit() and 1 <= int(requested) <= len(names):
            return names[int(requested) - 1]
        matches = [name for name in names if requested.lower() in name.lower()]
        if len(matches) == 1:
            return matches[0]
        if requested in names:
            return requested
        raise ValueError(f"没有找到 MIDI 设备：{requested}")
    print("\n可用 MIDI 输入：")
    for index, name in enumerate(names, 1):
        print(f"  {index}. {name}")
    selection = input("请选择设备编号：").strip()
    if not selection.isdigit() or not 1 <= int(selection) <= len(names):
        raise ValueError("设备编号无效")
    return names[int(selection) - 1]


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="电钢琴到原神原琴的无冲突调式映射器")
    parser.add_argument("--config", help="网页导出的 JSON 配置")
    parser.add_argument("--source", help="原曲主音，如 Db、F#、A；也可使用 0-11")
    parser.add_argument("--mode", choices=("major", "minor"), help="原曲调式")
    parser.add_argument("--strategy", choices=("harmony", "melody", "strict"), help="变化音策略")
    parser.add_argument("--register", type=int, choices=range(-2, 3), help="手动八度 -2 到 +2")
    parser.add_argument("--window", type=int, help="和弦识别窗口，单位毫秒")
    parser.add_argument("--flatten-minor", action="store_true", help="把小调音级改写成 C 大调，而非保留 A 小调听感")
    parser.add_argument("--device", help="MIDI 设备编号或名称片段")
    parser.add_argument("--dry-run", action="store_true", help="只打印映射，不发送 Windows 按键")
    return parser


def main() -> int:
    args = make_parser().parse_args()
    try:
        config = build_config(args)
        import mido
        if args.dry_run:
            keyboard = object()
        else:
            from pynput.keyboard import Controller
            keyboard = Controller()
    except ImportError as error:
        print(f"缺少依赖：{error.name}")
        print("请先运行：py -m pip install mido python-rtmidi pynput")
        return 2
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"配置错误：{error}")
        return 2

    target = "A 小调（C 大调白键）" if config.mode == "minor" and config.preserve_minor else "C 大调"
    print("Lyre Bridge v2")
    print(f"  原调：{NOTE_NAMES[config.source_tonic]} {'大调' if config.mode == 'major' else '小调'}")
    print(f"  目标：{target} | 策略：{config.strategy} | 和弦窗口：{config.chord_window_ms} ms")
    if not args.dry_run:
        print("  提示：运行后切回游戏窗口；Ctrl+C 会安全释放全部按键。")

    names = mido.get_input_names()
    if not names:
        print("没有发现 MIDI 输入，请检查 USB 连接与 python-rtmidi。")
        return 1

    try:
        device = choose_device(names, args.device)
        engine = LyreEngine(config, keyboard, dry_run=args.dry_run)
        print(f"\n已连接：{device}\n")
        with mido.open_input(device) as port:
            while True:
                message = port.poll()
                if message is not None:
                    engine.process_message(message)
                engine.flush_pending()
                time.sleep(0.001)
    except KeyboardInterrupt:
        print("\n已停止。")
    except Exception as error:
        print(f"运行中断：{error}")
        return 1
    finally:
        if "engine" in locals():
            engine.panic()
    return 0


if __name__ == "__main__":
    sys.exit(main())

