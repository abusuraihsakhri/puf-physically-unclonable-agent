"use strict";

/*
 * Browser-only educational PUF models. Deterministic PRNG is used solely to
 * reproduce simulated manufacturing variation; it is not cryptographic.
 */
function hashSeed(value) {
    let h = 2166136261;
    for (const char of String(value)) {
        h ^= char.charCodeAt(0);
        h = Math.imul(h, 16777619);
    }
    return h >>> 0;
}

function seededRandom(seed) {
    let state = seed >>> 0;
    return () => {
        state = (state + 0x6D2B79F5) >>> 0;
        let t = Math.imul(state ^ (state >>> 15), 1 | state);
        t ^= t + Math.imul(t ^ (t >>> 7), 61 | t);
        return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
}

function hamming(a, b) {
    if (a.length !== b.length || !a.length) {
        throw new RangeError("Bit vectors must have equal, nonzero length");
    }
    let errors = 0;
    for (let i = 0; i < a.length; i++) errors += Number(a[i] !== b[i]);
    return errors;
}

function gaussian(rng) {
    return Math.sqrt(-2 * Math.log(Math.max(Number.MIN_VALUE, rng())))
        * Math.cos(2 * Math.PI * rng());
}

function makeDevice(type, count, seed) {
    const rng = seededRandom(seed);
    if (type === "sram") {
        return { bits: Array.from({ length: count }, () => Number(rng() >= 0.5)) };
    }
    if (type === "arbiter") {
        return { delays: Array.from({ length: count }, () => rng() * 2 - 1) };
    }
    return { frequencies: Array.from({ length: count }, () => 100 + 100 * rng()) };
}

function readDevice(type, device, count, noise, challenge, pairs, rng) {
    if (type === "sram") {
        return device.bits.map(bit => noise && rng() < noise ? bit ^ 1 : bit);
    }
    if (type === "arbiter") {
        let delta = 0;
        for (let i = 0; i < count; i++) {
            delta += (challenge[i] ? -1 : 1) * device.delays[i];
        }
        if (noise) delta += gaussian(rng) * noise * Math.sqrt(count);
        return [Number(delta > 0)];
    }
    return pairs.map(([a, b]) => {
        const fa = device.frequencies[a] * (1 + gaussian(rng) * noise);
        const fb = device.frequencies[b] * (1 + gaussian(rng) * noise);
        return Number(fa > fb);
    });
}

function validate(config) {
    if (!["sram", "arbiter", "ring_oscillator"].includes(config.type)) {
        throw new RangeError("Unsupported PUF type");
    }
    for (const [key, min, max] of [
        ["bits", 32, 1024], ["devices", 2, 20],
        ["trials", 2, 100], ["challenges", 1, 100]
    ]) {
        if (!Number.isInteger(config[key]) || config[key] < min || config[key] > max) {
            throw new RangeError(key + " must be an integer from " + min + " to " + max);
        }
    }
    if (!Number.isFinite(config.noise) || config.noise < 0 || config.noise > 0.25) {
        throw new RangeError("Noise must be between 0 and 0.25");
    }
    if (typeof config.seed !== "string" || config.seed.length > 100) {
        throw new RangeError("Seed must be a string of at most 100 characters");
    }
    const bitsPerReading = config.type === "arbiter" ? config.bits :
        config.type === "sram" ? config.bits : Math.floor(config.bits / 2);
    const workload = bitsPerReading * config.devices * config.trials * config.challenges;
    if (workload > 10000000) {
        throw new RangeError("Workload exceeds 10 million simulated bit operations; reduce settings");
    }
}

function analyze(config) {
    validate(config);
    const { type, bits, devices, trials, challenges, noise, seed } = config;
    const rng = seededRandom(hashSeed(seed + "|measurements"));
    const models = Array.from({ length: devices }, (_, i) =>
        makeDevice(type, bits, hashSeed(seed + "|device|" + i)));
    let errors = 0;
    let comparisons = 0;
    let distances = 0;
    let pairsCount = 0;
    let preview = [];

    for (let c = 0; c < challenges; c++) {
        const challenge = Array.from({ length: bits }, () => Number(rng() >= 0.5));
        const pairs = Array.from({ length: Math.floor(bits / 2) }, () => {
            const a = Math.floor(rng() * bits);
            let b = Math.floor(rng() * (bits - 1));
            if (b >= a) b++;
            return [a, b];
        });
        // Reference is measured with zero noise for consistent comparison.
        const reference = models.map(device =>
            readDevice(type, device, bits, 0, challenge, pairs, rng));
        if (c === 0) preview = reference[0].slice(0, 64);

        for (let i = 0; i < devices; i++) {
            for (let t = 0; t < trials; t++) {
                const measurement = readDevice(type, models[i], bits, noise, challenge, pairs, rng);
                errors += hamming(reference[i], measurement);
                comparisons += measurement.length;
            }
            for (let j = i + 1; j < devices; j++) {
                distances += hamming(reference[i], reference[j]) / reference[i].length;
                pairsCount++;
            }
        }
    }

    return {
        model: type,
        seed,
        config: { bits, devices, trials, challenges, noise },
        reliabilityBer: errors / comparisons,
        uniqueness: distances / pairsCount,
        observedBits: comparisons,
        referenceBits: preview.join(""),
        description: "Educational mathematical simulation, not physical PUF validation or secure key generation."
    };
}

if (typeof module !== "undefined" && module.exports) {
    module.exports = { analyze, hamming, seededRandom, hashSeed };
}

if (typeof document !== "undefined") {
    const form = document.getElementById("sim-form");
    const results = document.getElementById("results");
    const runButton = document.getElementById("run");
    const download = document.getElementById("download");
    let lastResult = null;

    function setText(id, value) {
        document.getElementById(id).textContent = value;
    }

    form.addEventListener("submit", event => {
        event.preventDefault();
        runButton.disabled = true;
        download.disabled = true;
        setText("message", "Calculating...");
        try {
            const value = id => document.getElementById(id).value;
            const config = {
                type: value("type"),
                bits: Number(value("bits")),
                devices: Number(value("devices")),
                noise: Number(value("noise")),
                trials: Number(value("trials")),
                challenges: Number(value("challenges")),
                seed: value("seed")
            };
            const result = analyze(config);
            lastResult = result;
            setText("ber", (result.reliabilityBer * 100).toFixed(3) + "%");
            setText("uniqueness", (result.uniqueness * 100).toFixed(2) + "%");
            setText("samples", result.observedBits.toLocaleString());
            setText("preview", result.referenceBits);
            setText("message", "Simulation complete. Same seed and settings reproduce the same results.");
            results.hidden = false;
            download.disabled = false;
        } catch (error) {
            setText("message", "Invalid input: " + error.message);
            results.hidden = true;
        } finally {
            runButton.disabled = false;
        }
    });

    download.addEventListener("click", () => {
        if (!lastResult) return;
        const blob = new Blob([JSON.stringify(lastResult, null, 2) + "\n"],
            { type: "application/json" });
        const url = URL.createObjectURL(blob);
        const anchor = document.createElement("a");
        anchor.href = url;
        anchor.download = "puf-simulation.json";
        document.body.appendChild(anchor);
        anchor.click();
        anchor.remove();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
    });
}
