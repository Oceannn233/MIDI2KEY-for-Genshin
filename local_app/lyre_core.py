# -*- coding: utf-8 -*-
"""Harmony-aware, stateful MIDI-to-lyre mapping core."""

from __future__ import annotations

import math
import time
from collections import Counter
from dataclasses import asdict, dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple


NOTE_NAMES = ("C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B")
MAJOR_INTERVALS = (0, 2, 4, 5, 7, 9, 11)
MINOR_INTERVALS = (0, 2, 3, 5, 7, 8, 10)
WHITE_PITCH_CLASSES = frozenset(MAJOR_INTERVALS)
WHITE_MIDI_NOTES = tuple(note for note in range(48, 84) if note % 12 in WHITE_PITCH_CLASSES)
GENSHIN_KEYS = tuple("ZXCVBNMASDFGHJQWERTYU")
KEY_BY_MIDI = dict(zip(WHITE_MIDI_NOTES, GENSHIN_KEYS))


def mod(value: int, divisor: int = 12) -> int:
    return value % divisor


def signed_pitch_distance(source: int, target: int) -> int:
    upward = mod(target - source)
    return upward - 12 if upward > 6 else upward


def midi_name(note: int) -> str:
    return f"{NOTE_NAMES[note % 12]}{note // 12 - 1}"


@dataclass(frozen=True)
class MapperConfig:
    source_tonic: int = 1
    mode: str = "major"
    strategy: str = "harmony"
    preserve_minor: bool = True
    register_shift: int = 0
    chord_window_ms: int = 18

    @classmethod
    def from_dict(cls, value: object) -> "MapperConfig":
        raw = value if isinstance(value, dict) else {}
        config = cls(
            source_tonic=int(raw.get("source_tonic", 1)),
            mode=str(raw.get("mode", "major")),
            strategy=str(raw.get("strategy", "harmony")),
            preserve_minor=bool(raw.get("preserve_minor", True)),
            register_shift=int(raw.get("register_shift", 0)),
            chord_window_ms=int(raw.get("chord_window_ms", 18)),
        )
        return config.validate()

    def validate(self) -> "MapperConfig":
        if not 0 <= self.source_tonic <= 11:
            raise ValueError("主音必须在 0 到 11 之间")
        if self.mode not in {"major", "minor"}:
            raise ValueError("调式必须是 major 或 minor")
        if self.strategy not in {"harmony", "melody", "strict"}:
            raise ValueError("策略必须是 harmony、melody 或 strict")
        if not -2 <= self.register_shift <= 2:
            raise ValueError("手动八度必须在 -2 到 +2 之间")
        if not 4 <= self.chord_window_ms <= 80:
            raise ValueError("和弦识别窗口必须在 4 到 80 ms 之间")
        return self

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)


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
    analyses: Dict[int, NoteAnalysis]
    ideals: Dict[int, int]


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
        return GroupMapping({}, locked_octave_shift or 0, 0, 0, {}, {})

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
                cost = distance * multiplier + max(0, distance - 2) ** 2 * 1.5
                if exact_playable and candidate % 12 != ideal % 12:
                    cost += 20
                if not accidental and adaptive_offset == 0 and candidate % 12 != ideal % 12:
                    cost += 26
                update(i + 1, j + 1, current + cost, i, j, "assign")

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

    return GroupMapping(
        assignments=assignments,
        octave_shift=octave_shift,
        adaptive_offset=adaptive_offset,
        conflicts_avoided=conflicts_avoided,
        analyses={item.note: item for item in analyses},
        ideals=dict(zip(ordered, ideals)),
    )


class LyreEngine:
    """Owns active-note, sustain, output-key and live-config state."""

    def __init__(self, config: MapperConfig, keyboard: object) -> None:
        self.config = config
        self.keyboard = keyboard
        self.output_enabled = False
        self.held_notes: Set[int] = set()
        self.sustained_notes: Set[int] = set()
        self.pending_notes: Dict[int, float] = {}
        self.active_mapping: Dict[int, int] = {}
        self.mapping_reasons: Dict[int, str] = {}
        self.output_refs: Counter[int] = Counter()
        self.sustain_down = False
        self.locked_octave_shift: Optional[int] = None
        self.last_event: Dict[str, object] = {"assignments": []}
        self.revision = 0
        self.output_error: Optional[str] = None

    def _changed(self) -> None:
        self.revision += 1

    def update_config(self, config: MapperConfig) -> None:
        if config == self.config:
            return
        self.panic("参数已更新，请重新落键")
        self.config = config
        self._changed()

    def set_output_enabled(self, enabled: bool) -> None:
        if enabled == self.output_enabled:
            return
        self.panic("游戏输出状态已切换")
        self.output_enabled = enabled
        self.output_error = None
        self._changed()

    def queue_note_on(self, note: int) -> None:
        if note in self.held_notes:
            return
        self.held_notes.add(note)
        self.sustained_notes.discard(note)
        if note not in self.active_mapping:
            self.pending_notes[note] = time.monotonic()
        self._changed()

    def note_off(self, note: int) -> None:
        self.held_notes.discard(note)
        if note in self.pending_notes:
            self.flush_pending(force=True)
        if self.sustain_down:
            self.sustained_notes.add(note)
        else:
            self.release_note(note)
        self._changed()

    def set_sustain(self, enabled: bool) -> None:
        if enabled == self.sustain_down:
            return
        self.sustain_down = enabled
        if not enabled:
            releasing = [note for note in self.sustained_notes if note not in self.held_notes]
            self.sustained_notes.clear()
            for note in releasing:
                self.release_note(note)
        self._changed()

    def _reason_for(self, note: int, output: Optional[int], mapping: GroupMapping) -> str:
        analysis = mapping.analyses[note]
        ideal = mapping.ideals[note]
        if output is None:
            return "严格调内：变化音已省略" if analysis.degree < 0 else "容量不足：已保护其他声部"
        if mapping.adaptive_offset and output == ideal:
            return f"和弦整体偏移 {mapping.adaptive_offset:+d} 半音，保留和弦形状"
        if output == ideal:
            return "调内音按音级无损映射"
        if analysis.degree < 0:
            return "变化音分配到最近空闲音级，避免抢键"
        return "为保持声部顺序，移动到最近空闲原琴音"

    def _press_output(self, output: int) -> None:
        if not self.output_enabled or self.output_refs[output] > 0:
            return
        try:
            self.keyboard.press(KEY_BY_MIDI[output].lower())
        except Exception as error:
            self.output_error = f"Windows 按键发送失败：{error}"
            self.output_enabled = False

    def flush_pending(self, force: bool = False) -> bool:
        if not self.pending_notes:
            return False
        elapsed_ms = (time.monotonic() - min(self.pending_notes.values())) * 1000
        if not force and elapsed_ms < self.config.chord_window_ms:
            return False
        notes = sorted(self.pending_notes)
        self.pending_notes.clear()
        mapping = map_note_group(
            notes,
            self.config,
            reserved_outputs=set(self.active_mapping.values()),
            locked_octave_shift=self.locked_octave_shift,
        )
        if self.locked_octave_shift is None:
            self.locked_octave_shift = mapping.octave_shift
        event_assignments = []
        for note in notes:
            output = mapping.assignments.get(note)
            reason = self._reason_for(note, output, mapping)
            event_assignments.append({
                "input": note,
                "input_name": midi_name(note),
                "output": output,
                "output_name": midi_name(output) if output is not None else "静音",
                "key": KEY_BY_MIDI.get(output, "—"),
                "reason": reason,
            })
            if output is None:
                continue
            self.active_mapping[note] = output
            self.mapping_reasons[note] = reason
            self._press_output(output)
            self.output_refs[output] += 1
        self.last_event = {
            "assignments": event_assignments,
            "octave_shift": mapping.octave_shift,
            "adaptive_offset": mapping.adaptive_offset,
            "conflicts_avoided": mapping.conflicts_avoided,
        }
        self._changed()
        return True

    def release_note(self, note: int) -> None:
        self.pending_notes.pop(note, None)
        output = self.active_mapping.pop(note, None)
        self.mapping_reasons.pop(note, None)
        if output is not None:
            self.output_refs[output] = max(0, self.output_refs[output] - 1)
            if self.output_refs[output] == 0:
                if self.output_enabled:
                    try:
                        self.keyboard.release(KEY_BY_MIDI[output].lower())
                    except Exception:
                        pass
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

    def panic(self, reason: str = "全部按键已释放") -> None:
        for output in list(self.output_refs):
            try:
                self.keyboard.release(KEY_BY_MIDI[output].lower())
            except Exception:
                pass
        self.pending_notes.clear()
        self.active_mapping.clear()
        self.mapping_reasons.clear()
        self.output_refs.clear()
        self.held_notes.clear()
        self.sustained_notes.clear()
        self.sustain_down = False
        self.locked_octave_shift = None
        self.last_event = {"assignments": [], "notice": reason}
        self._changed()

    def snapshot(self) -> Dict[str, object]:
        active_assignments = [
            {
                "input": note,
                "input_name": midi_name(note),
                "output": output,
                "output_name": midi_name(output),
                "key": KEY_BY_MIDI[output],
                "reason": self.mapping_reasons.get(note, "当前活动映射"),
            }
            for note, output in sorted(self.active_mapping.items())
        ]
        target = "A 小调（C 大调白键）" if self.config.mode == "minor" and self.config.preserve_minor else "C 大调"
        return {
            "revision": self.revision,
            "config": self.config.to_dict(),
            "output_enabled": self.output_enabled,
            "output_error": self.output_error,
            "sustain_down": self.sustain_down,
            "active_notes": sorted(self.held_notes | self.sustained_notes),
            "active_outputs": sorted(self.output_refs),
            "active_assignments": active_assignments,
            "last_event": self.last_event,
            "target_label": target,
        }

