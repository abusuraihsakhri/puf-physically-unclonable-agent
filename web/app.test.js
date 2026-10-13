"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const { analyze, hamming } = require("./app.js");

const base = {
    type: "sram",
    bits: 64,
    devices: 4,
    trials: 8,
    challenges: 6,
    noise: 0.01,
    seed: "browser-regression",
};

test("Hamming comparison rejects unequal or empty vectors", () => {
    assert.equal(hamming([0, 1], [1, 1]), 1);
    assert.throws(() => hamming([0], []), RangeError);
    assert.throws(() => hamming([], []), RangeError);
});

test("all architectures return bounded, reproducible statistics", () => {
    for (const type of ["sram", "arbiter", "ring_oscillator"]) {
        const config = { ...base, type };
        const a = analyze(config);
        const b = analyze(config);
        assert.deepEqual(a, b);
        assert.ok(a.observedBits > 0);
        assert.ok(a.reliabilityBer >= 0 && a.reliabilityBer <= 1);
        assert.ok(a.uniqueness >= 0 && a.uniqueness <= 1);
        assert.ok(a.referenceBits.length > 0);
    }
});

test("zero noise yields perfectly repeatable outputs", () => {
    for (const type of ["sram", "arbiter", "ring_oscillator"]) {
        assert.equal(analyze({ ...base, type, noise: 0 }).reliabilityBer, 0);
    }
});

test("invalid settings fail before simulation", () => {
    for (const patch of [
        { bits: 0 }, { devices: 1 }, { trials: 1 },
        { challenges: 101 }, { noise: -0.1 }, { noise: Infinity },
        { type: "unknown" }, { seed: "x".repeat(101) },
        { bits: 1024, devices: 20, trials: 100, challenges: 100 }
    ]) {
        assert.throws(() => analyze({ ...base, ...patch }), RangeError);
    }
});

test("different seeds vary simulated reference response", () => {
    const a = analyze({ ...base, seed: "alpha" });
    const b = analyze({ ...base, seed: "beta" });
    assert.notEqual(a.referenceBits, b.referenceBits);
});
