# PUF Physically Unclonable Agent

> **Domain:** Post-Quantum Cryptography & Hardware Security
> **Standards:** NIST FIPS 203/204/205, NIST SP 800-193, NIST SP 800-90B, ISO/IEC 17825

<div align="center">

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
![Python](https://img.shields.io/badge/Python-3.10%20%7C%203.11%20%7C%203.12-3776AB.svg?logo=python&logoColor=white)
![Audit Trail](https://img.shields.io/badge/Audit-HMAC--SHA256_Tamper--Evident-brightgreen.svg)
![Zero-PHI Guard](https://img.shields.io/badge/Guard-Zero--PHI_Outbound-blue.svg)
![Docker](https://img.shields.io/badge/Docker-Ready-2496ED.svg?logo=docker&logoColor=white)

</div>

---

## Overview

PUF (Physically Unclonable Function) Simulator and Validator implementing realistic simulations of hardware PUF types for cryptographic research and education. Includes SRAM PUF, Arbiter PUF, and Ring Oscillator PUF implementations with challenge-response pair management, reliability measurement, and fuzzy extractor-based key generation.

---

## Key Features

- **SRAM PUF Simulation**: Models power-up state based on manufacturing variations with configurable noise
- **Arbiter PUF Simulation**: Race condition between delay paths with challenge-response evaluation
- **Ring Oscillator PUF**: Frequency comparison-based response generation
- **Challenge-Response Pair (CRP) Management**: Enrollment, verification, and export
- **Reliability Measurement**: Bit error rate (BER) computation across repeated measurements
- **Uniqueness Measurement**: Inter-device Hamming distance analysis
- **Fuzzy Extractor**: Error correction for stable key derivation from noisy PUF responses
- **Multi-Agent Validation System**: Distributed component coordination with specialized workers
- **Zero-PHI Outbound Guard**: Prevents sensitive data leakage in outbound communications
- **HMAC-SHA256 Audit Trail**: Tamper-evident cryptographic logging
- **FastAPI REST API**: OpenAPI 3.1 endpoints for remote operation
- **Prometheus Metrics**: Operational telemetry export

---

## Installation

```bash
# Clone the repository
git clone https://github.com/abusuraihsakhri/puf-physically-unclonable-agent.git
cd puf-physically-unclonable-agent

# Install dependencies (Python 3.9+ required)
pip install -e .

# For development with testing
pip install -e ".[dev]"
```

---

## Usage

### PUF Simulator CLI

```bash
# SRAM PUF power-up simulation
python cli.py sram --bits 256 --noise 0.02

# Arbiter PUF evaluation
python cli.py arbiter --stages 64

# Ring Oscillator PUF comparison
python cli.py ro --oscillators 128 --pair 0 1

# Generate Challenge-Response Pairs
python cli.py crp --puf-type sram --bits 128 --count 10

# Measure inter-device uniqueness
python cli.py uniqueness --puf-type sram --devices 5 --bits 256

# Fuzzy extractor demo
python cli.py fuzzy --bits 128 --noise 0.02 --tolerance 5

# Full simulation with multiple devices
python cli.py simulate --puf-type sram --devices 3 --bits 128
```

### Validator CLI

```bash
# Run single task evaluation
python puf_validator_app.py audit --task-id TASK-001

# System configuration query
python puf_validator_app.py chat "What is the system status?"

# Batch process CSV records
python puf_validator_app.py batch -i sample.csv -o results.csv

# Launch FastAPI REST server
python puf_validator_app.py serve --host 127.0.0.1 --port 8000
```

### REST API

```bash
# Start the server
python puf_validator_app.py serve

# Health check
curl http://localhost:8000/health

# Audit endpoint
curl -X POST http://localhost:8000/api/audit \
  -H "Content-Type: application/json" \
  -d '{"task_id": "TASK-001", "primary_metric": 28.5, "status_descriptor": "DISCORDANT_ANOMALY"}'

# Chat endpoint
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"query": "What is the system status?"}'
```

---

## Testing

```bash
# Run all tests
pytest -v

# Run specific test modules
pytest tests/test_puf_physically_unclonable_agent.py -v
pytest tests/test_puf_validator.py -v
pytest tests/test_enrichment.py -v
```

---

## Project Structure

```
puf-physically-unclonable-agent/
├── simulator.py              # Core PUF simulation engine
├── cli.py                    # PUF simulator CLI
├── puf_validator_app.py      # Validator CLI entry point
├── enrichment.py             # Domain enrichment engines
├── agents/                   # Enterprise agent system
│   ├── api.py               # FastAPI REST server
│   ├── base.py              # Security, PHI guard, audit trail
│   ├── models.py            # Pydantic data models
│   ├── workers.py           # Specialized domain workers
│   ├── supervisor.py        # System supervisor orchestrator
│   ├── llm_factory.py       # LLM provider factory
│   ├── metrics.py           # Prometheus metrics
│   ├── learning.py          # Bayesian calibration engine
│   └── streamer.py          # WebSocket telemetry streamer
├── puf_validator/            # PUF validator module
│   ├── cli.py               # Validator CLI
│   ├── models.py            # Data models
│   ├── engine.py            # Core evaluation engine
│   ├── agents.py            # Sub-agent coordination
│   └── server.py            # FastAPI server
├── web/                      # Operations console
│   └── index.html           # Web dashboard
├── tests/                    # Test suite
├── Dockerfile               # Container definition
├── docker-compose.yml       # Container orchestration
└── pyproject.toml           # Project configuration
```

---

## Security

- **Zero-PHI Outbound Interceptor**: Active regex inspection blocking SSNs, MRNs, phone numbers, and patient identifiers
- **Tamper-Evident HMAC-SHA256 Audit Trail**: Chained, cryptographically signed logs for every evaluation
- **Secure Random Key Generation**: Audit trail uses `secrets.token_bytes()` when no key is configured
- **Input Validation**: Rigorous bounds checking on all PUF parameters

---

## Docker Deployment

```bash
# Build and run with Docker Compose
docker-compose up --build

# Or manually
docker build -t puf-physically-unclonable-agent .
docker run -p 8000:8000 -e AUDIT_SECRET_KEY=your-secret-key puf-physically-unclonable-agent
```

---

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
