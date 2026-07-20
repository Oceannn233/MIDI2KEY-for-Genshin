export const NOTE_NAMES = [
  "C",
  "D♭",
  "D",
  "E♭",
  "E",
  "F",
  "G♭",
  "G",
  "A♭",
  "A",
  "B♭",
  "B",
] as const;

export const TONIC_OPTIONS = [
  { value: 0, label: "C" },
  { value: 1, label: "D♭ / C♯" },
  { value: 2, label: "D" },
  { value: 3, label: "E♭ / D♯" },
  { value: 4, label: "E" },
  { value: 5, label: "F" },
  { value: 6, label: "G♭ / F♯" },
  { value: 7, label: "G" },
  { value: 8, label: "A♭ / G♯" },
  { value: 9, label: "A" },
  { value: 10, label: "B♭ / A♯" },
  { value: 11, label: "B" },
] as const;

export const GENSHIN_KEYS = [
  "Z", "X", "C", "V", "B", "N", "M",
  "A", "S", "D", "F", "G", "H", "J",
  "Q", "W", "E", "R", "T", "Y", "U",
] as const;

export const WHITE_MIDI_NOTES = Array.from({ length: 36 }, (_, index) => 48 + index)
  .filter((note) => [0, 2, 4, 5, 7, 9, 11].includes(note % 12));

export type ScaleMode = "major" | "minor";
export type MappingStrategy = "harmony" | "melody" | "strict";

export type MapperConfig = {
  sourceTonic: number;
  mode: ScaleMode;
  preserveMinor: boolean;
  strategy: MappingStrategy;
  registerShift: number;
};

export type NoteAssignment = {
  input: number;
  ideal: number;
  output: number | null;
  key: string | null;
  accidental: boolean;
  exact: boolean;
  reason: string;
};

export type MappingResult = {
  assignments: NoteAssignment[];
  baseTranspose: number;
  octaveShift: number;
  adaptiveOffset: number;
  conflictsAvoided: number;
  omitted: number;
  quality: "lossless" | "adapted" | "lossy";
  targetLabel: string;
};

const MAJOR_INTERVALS = [0, 2, 4, 5, 7, 9, 11];
const MINOR_INTERVALS = [0, 2, 3, 5, 7, 8, 10];
const WHITE_PITCH_CLASSES = new Set(MAJOR_INTERVALS);

export function mod(value: number, divisor = 12) {
  return ((value % divisor) + divisor) % divisor;
}

export function signedPitchDistance(from: number, to: number) {
  const upward = mod(to - from);
  return upward > 6 ? upward - 12 : upward;
}

export function midiName(note: number) {
  return `${NOTE_NAMES[mod(note)]}${Math.floor(note / 12) - 1}`;
}

export function isWhite(note: number) {
  return WHITE_PITCH_CLASSES.has(mod(note));
}

export function genshinKeyForMidi(note: number) {
  const index = WHITE_MIDI_NOTES.indexOf(note);
  return index >= 0 ? GENSHIN_KEYS[index] : null;
}

export function sourceScalePitchClasses(config: MapperConfig) {
  const intervals = config.mode === "major" ? MAJOR_INTERVALS : MINOR_INTERVALS;
  return intervals.map((interval) => mod(config.sourceTonic + interval));
}

export function sourceScaleNames(config: MapperConfig) {
  return sourceScalePitchClasses(config).map((pitchClass) => NOTE_NAMES[pitchClass]);
}

export function targetScaleNames(config: MapperConfig) {
  if (config.mode === "minor" && config.preserveMinor) {
    return ["A", "B", "C", "D", "E", "F", "G"];
  }
  return ["C", "D", "E", "F", "G", "A", "B"];
}

export function targetLabel(config: MapperConfig) {
  return config.mode === "minor" && config.preserveMinor
    ? "A 小调（C 大调原琴键）"
    : "C 大调";
}

function degreeAndIdeal(note: number, config: MapperConfig) {
  const sourceIntervals = config.mode === "major" ? MAJOR_INTERVALS : MINOR_INTERVALS;
  const preserveMode = config.mode === "major" || config.preserveMinor;
  const targetIntervals = preserveMode ? sourceIntervals : MAJOR_INTERVALS;
  const targetTonic = config.mode === "minor" && config.preserveMinor ? 9 : 0;
  const baseTranspose = signedPitchDistance(config.sourceTonic, targetTonic);
  const relativePitchClass = mod(note - config.sourceTonic);
  const degree = sourceIntervals.indexOf(relativePitchClass);
  const chromaticIdeal = note + baseTranspose;

  if (degree < 0) {
    return { degree, ideal: chromaticIdeal, baseTranspose };
  }

  const expectedPitchClass = mod(targetTonic + targetIntervals[degree]);
  const correction = signedPitchDistance(mod(chromaticIdeal), expectedPitchClass);
  return { degree, ideal: chromaticIdeal + correction, baseTranspose };
}

function chooseOctaveShift(ideals: number[], requestedRegister: number) {
  const requested = requestedRegister * 12;
  let bestShift = requested;
  let bestScore = Number.POSITIVE_INFINITY;

  for (let automatic = -72; automatic <= 72; automatic += 12) {
    const shift = requested + automatic;
    let score = Math.abs(automatic) * 0.05;
    for (const ideal of ideals) {
      const shifted = ideal + shift;
      if (shifted < 48) score += (48 - shifted) ** 2 * 8;
      if (shifted > 83) score += (shifted - 83) ** 2 * 8;
    }
    if (score < bestScore) {
      bestScore = score;
      bestShift = shift;
    }
  }
  return bestShift;
}

function chooseAdaptiveOffset(shiftedIdeals: number[], strategy: MappingStrategy) {
  if (strategy !== "harmony" || shiftedIdeals.length < 2) return 0;

  const basePlayable = shiftedIdeals.filter(isWhite).length;
  let best = { offset: 0, score: basePlayable * 12 };

  for (let offset = -2; offset <= 2; offset += 1) {
    const playable = shiftedIdeals.filter((note) => isWhite(note + offset)).length;
    const score = playable * 12 - Math.abs(offset) * 2.5;
    if (score > best.score) best = { offset, score };
  }

  const improved = shiftedIdeals.filter((note) => isWhite(note + best.offset)).length;
  return improved >= basePlayable + 2 && improved >= Math.ceil(shiftedIdeals.length * 0.75)
    ? best.offset
    : 0;
}

function nearestWhite(note: number) {
  let best = WHITE_MIDI_NOTES[0];
  let distance = Number.POSITIVE_INFINITY;
  for (const candidate of WHITE_MIDI_NOTES) {
    const nextDistance = Math.abs(candidate - note);
    if (nextDistance < distance) {
      best = candidate;
      distance = nextDistance;
    }
  }
  return best;
}

type Cell = {
  cost: number;
  previousI: number;
  previousJ: number;
  action: "assign" | "omit" | "skip" | null;
};

export function mapChord(
  rawNotes: number[],
  config: MapperConfig,
  previouslyMapped: Map<number, number> = new Map(),
  reservedOutputs: Set<number> = new Set(),
): MappingResult {
  const notes = [...new Set(rawNotes)].sort((a, b) => a - b);
  if (!notes.length) {
    return {
      assignments: [],
      baseTranspose: signedPitchDistance(
        config.sourceTonic,
        config.mode === "minor" && config.preserveMinor ? 9 : 0,
      ),
      octaveShift: config.registerShift * 12,
      adaptiveOffset: 0,
      conflictsAvoided: 0,
      omitted: 0,
      quality: "lossless",
      targetLabel: targetLabel(config),
    };
  }

  const analyses = notes.map((note) => ({ note, ...degreeAndIdeal(note, config) }));
  const octaveShift = chooseOctaveShift(
    analyses.map((analysis) => analysis.ideal),
    config.registerShift,
  );
  const shiftedIdeals = analyses.map((analysis) => analysis.ideal + octaveShift);
  const adaptiveOffset = chooseAdaptiveOffset(shiftedIdeals, config.strategy);
  const adjustedIdeals = shiftedIdeals.map((ideal) => ideal + adaptiveOffset);
  const candidates = WHITE_MIDI_NOTES.filter((note) => !reservedOutputs.has(note));

  const naive = adjustedIdeals.map(nearestWhite);
  const conflictsAvoided = naive.length - new Set(naive).size;
  const rows = notes.length + 1;
  const columns = candidates.length + 1;
  const table: Cell[][] = Array.from({ length: rows }, () =>
    Array.from({ length: columns }, () => ({
      cost: Number.POSITIVE_INFINITY,
      previousI: -1,
      previousJ: -1,
      action: null,
    })),
  );
  table[0][0].cost = 0;

  const update = (
    nextI: number,
    nextJ: number,
    cost: number,
    previousI: number,
    previousJ: number,
    action: Cell["action"],
  ) => {
    if (cost < table[nextI][nextJ].cost) {
      table[nextI][nextJ] = { cost, previousI, previousJ, action };
    }
  };

  for (let i = 0; i <= notes.length; i += 1) {
    for (let j = 0; j <= candidates.length; j += 1) {
      const current = table[i][j];
      if (!Number.isFinite(current.cost)) continue;

      if (j < candidates.length) {
        update(i, j + 1, current.cost, i, j, "skip");
      }
      if (i >= notes.length) continue;

      const analysis = analyses[i];
      const ideal = adjustedIdeals[i];
      const accidental = analysis.degree < 0;
      const exactPlayable = isWhite(ideal);
      const omitCost = accidental ? 24 : 58;
      update(i + 1, j, current.cost + omitCost, i, j, "omit");

      if (j < candidates.length && !(config.strategy === "strict" && !exactPlayable)) {
        const candidate = candidates[j];
        const distance = Math.abs(candidate - ideal);
        let assignmentCost = distance * (config.strategy === "melody" ? 4.2 : 3.2);
        assignmentCost += Math.max(0, distance - 2) ** 2 * 1.5;
        if (exactPlayable && mod(candidate) !== mod(ideal)) assignmentCost += 20;
        if (!accidental && adaptiveOffset === 0 && mod(candidate) !== mod(ideal)) assignmentCost += 26;
        const previous = previouslyMapped.get(analysis.note);
        if (previous !== undefined) assignmentCost += Math.abs(previous - candidate) * 2.5;
        update(i + 1, j + 1, current.cost + assignmentCost, i, j, "assign");
      }
    }
  }

  let bestJ = 0;
  for (let j = 1; j <= candidates.length; j += 1) {
    if (table[notes.length][j].cost < table[notes.length][bestJ].cost) bestJ = j;
  }

  const outputs = new Map<number, number | null>();
  let cursorI = notes.length;
  let cursorJ = bestJ;
  while (cursorI > 0 || cursorJ > 0) {
    const cell = table[cursorI][cursorJ];
    if (cell.action === "assign") {
      outputs.set(notes[cursorI - 1], candidates[cursorJ - 1]);
    } else if (cell.action === "omit") {
      outputs.set(notes[cursorI - 1], null);
    }
    if (cell.previousI < 0 || cell.previousJ < 0) break;
    cursorI = cell.previousI;
    cursorJ = cell.previousJ;
  }

  const assignments = analyses.map((analysis, index): NoteAssignment => {
    const output = outputs.get(analysis.note) ?? null;
    const ideal = adjustedIdeals[index];
    const accidental = analysis.degree < 0;
    const exact = output !== null && output === ideal;
    let reason = "调内音按音级无损映射";
    if (output === null) reason = accidental ? "严格模式：省略调外变化音" : "超出原琴容量，已保护其他声部";
    else if (adaptiveOffset !== 0 && exact) reason = `和弦整体平移 ${adaptiveOffset > 0 ? "+" : ""}${adaptiveOffset}，保留和弦形状`;
    else if (!exact && accidental) reason = "变化音分配到最近的空闲音级，避免按键冲突";
    else if (!exact) reason = "为保持声部顺序，移动到最近的空闲原琴音";

    return {
      input: analysis.note,
      ideal,
      output,
      key: output === null ? null : genshinKeyForMidi(output),
      accidental,
      exact,
      reason,
    };
  });

  const omitted = assignments.filter((assignment) => assignment.output === null).length;
  const changed = assignments.some((assignment) => !assignment.exact);
  return {
    assignments,
    baseTranspose: analyses[0].baseTranspose,
    octaveShift,
    adaptiveOffset,
    conflictsAvoided,
    omitted,
    quality: omitted ? "lossy" : changed || adaptiveOffset !== 0 ? "adapted" : "lossless",
    targetLabel: targetLabel(config),
  };
}

