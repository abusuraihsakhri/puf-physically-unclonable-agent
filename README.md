# PUF (Physically Unclonable Function) Simulator

A Python simulator for hardware Physically Unclonable Functions (PUFs). Implements realistic models of SRAM, Arbiter, and Ring Oscillator PUFs with challenge-response pair management, reliability/uniqueness measurement, and fuzzy extractor error correction.

## What This Actually Does

This is a **simulation** of PUF behavior using cryptographic hash functions to model manufacturing variations. It does **not** interface with real hardware. Each simulated PUF device gets a unique seed that deterministically produces cell biases (SRAM), delay parameters (Arbiter), or frequencies (Ring Oscillator), mimicking the physical process that makes real PUFs unique.

## PUF Types Implemented

### SRAM PUF
Each cell has a bias (probability of powering up to 1) derived from the device seed. Thermal noise is modeled by flipping bits with probability `noise_rate`. Reliability is measured via majority-vote across multiple power-up cycles.

### Arbiter PUF
Models a race condition between two delay paths through N stages. Each challenge bit selects straight-through or cross routing. The arbiter outputs 0 if the upper path is faster, 1 otherwise. Deterministic for a given device+challenge pair.

### Ring Oscillator PUF
Each oscillator has a characteristic frequency from manufacturing variations. A challenge selects pairs of oscillators; the response is 1 if the first is faster. Noise perturbs frequencies slightly each measurement.

## Features

- **CRP Management**: Enroll and verify Challenge-Response Pairs
- **Reliability**: Measure bit error rate across repeated measurements
- **Uniqueness**: Compute inter-device Hamming distance (target ~50%)
- **Fuzzy Extractor**: XOR-based helper data with error correction for key derivation
- **CLI**: Full command-line interface for all operations

## Quick Start

```bash
# SRAM PUF power-up with reliability measurement
python cli.py sram --bits 256 --noise 0.02 --reliability --trials 50

# Arbiter PUF evaluation
python cli.py arbiter --stages 64

# Ring Oscillator comparison
python cli.py ro --oscillators 128 --pair 0 1

# Generate CRPs
python cli.py crp --puf-type sram --bits 128 --count 10

# Measure uniqueness across devices
python cli.py uniqueness --puf-type sram --devices 5 --bits 256

# Fuzzy extractor demo
python cli.py fuzzy --bits 128 --noise 0.02 --tolerance 5

# Full simulation
python cli.py simulate --puf-type sram --devices 3 --bits 128
```

## Python API

```python
from simulator import SRAMPUF, ArbiterPUF, RingOscillatorPUF, FuzzyExtractor

# SRAM PUF
puf = SRAMPUF(num_cells=256, noise_rate=0.02)
bits = puf.power_up()
reference, ber = puf.measure_reliability(num_trials=100)

# Arbiter PUF
arbiter = ArbiterPUF(num_stages=64)
challenge = [1, 0, 1, 1, 0, ...]  # 64 bits
response = arbiter.evaluate(challenge)

# Fuzzy extractor for error correction
fe = FuzzyExtractor(response_length=128)
key, helper_data = fe.enroll(raw_response)
recovered_key = fe.reproduce(noisy_response, helper_data)
```

## Requirements

Python 3.10+ stdlib only (no external dependencies).

## License

MIT
