import assert from "node:assert/strict";
import test from "node:test";
import { mapChord } from "../app/lib/mapping.ts";

const base = {
  sourceTonic: 1,
  mode: "major",
  preserveMinor: true,
  strategy: "harmony",
  registerShift: 0,
};

test("D-flat major triad maps losslessly to C major", () => {
  const result = mapChord([61, 65, 68], base);
  assert.deepEqual(result.assignments.map((item) => item.output), [60, 64, 67]);
  assert.deepEqual(result.assignments.map((item) => item.key), ["A", "D", "G"]);
  assert.equal(result.quality, "lossless");
});

test("chromatic neighbors never share one lyre key", () => {
  const result = mapChord([60, 61, 64], { ...base, sourceTonic: 0 });
  const outputs = result.assignments.flatMap((item) => item.output === null ? [] : [item.output]);
  assert.equal(outputs.length, new Set(outputs).size);
  assert.ok(outputs.length >= 2);
});

test("strict mode omits an out-of-key accidental", () => {
  const result = mapChord([60, 66, 67], {
    ...base,
    sourceTonic: 0,
    strategy: "strict",
  });
  assert.equal(result.assignments.find((item) => item.input === 66)?.output, null);
  assert.equal(result.assignments.find((item) => item.input === 60)?.output, 60);
  assert.equal(result.assignments.find((item) => item.input === 67)?.output, 67);
});

test("a high chord is moved by one shared octave multiple", () => {
  const result = mapChord([96, 100, 103], { ...base, sourceTonic: 0 });
  assert.deepEqual(result.assignments.map((item) => item.output), [72, 76, 79]);
  assert.equal(result.octaveShift, -24);
});

test("minor mode preserves minor quality on the C-major white-key collection", () => {
  const result = mapChord([62, 65, 69], {
    ...base,
    sourceTonic: 2,
    mode: "minor",
    preserveMinor: true,
  });
  assert.deepEqual(result.assignments.map((item) => item.output), [57, 60, 64]);
  assert.equal(result.targetLabel, "A 小调（C 大调原琴键）");
});

