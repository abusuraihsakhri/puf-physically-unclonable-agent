# PUF Physically Unclonable Agent

Educational simulations and analysis tools for physically unclonable functions (PUFs). The repository provides Python models of SRAM, arbiter, and ring-oscillator PUFs, a separate rules-based validator, FastAPI endpoints, and an entirely client-side browser simulator.

**Scope:** Mathematical and software demonstrations only. No physical hardware is measured, no real-world entropy is characterized, and no cryptographic certification or NIST/ISO conformance is asserted.

## Browser simulator

Open `web/index.html` in a modern browser. The application runs locally with JavaScript and does not require a Python server or network connection.

- Select SRAM, arbiter, or ring-oscillator architecture.
- Choose model size, noise, devices, repeated readings, and challenge samples.
- Compute repeatability (bit error rate) and uniqueness (mean pairwise normalized Hamming distance).
- Reproduce runs with a seed and export results as JSON.

The browser simulator is an intentionally lightweight model; it does **not** execute the Python source. A GitHub Actions workflow is included for GitHub Pages publication once Pages is enabled for the repository. Deployment availability must be checked separately.

## Python setup

Requires Python 3.10 or newer.

```bash
git clone https://github.com/abusuraihsakhri/puf-physically-unclonable-agent.git
cd puf-physically-unclonable-agent
python -m pip install -e ".[dev]"
```

The Python simulator uses the standard library; the package also installs Pydantic, FastAPI, and Uvicorn for the agent and HTTP interfaces.

## Usage

```bash
# PUF simulation
puf-simulator sram --bits 256 --noise 0.02 --reliability --trials 50
puf-simulator arbiter --stages 64
puf-simulator ro --oscillators 128 --pair 0 1
puf-simulator crp --puf-type sram --bits 128 --count 10
puf-simulator uniqueness --puf-type arbiter --devices 5 --bits 64
puf-simulator fuzzy --bits 128 --noise 0.02 --tolerance 5
puf-simulator simulate --puf-type sram --devices 3 --bits 128

# Rules-based validator
puf-validator audit --task-id TASK-001 --primary 29.4 --secondary 15.1
puf-validator batch -i sample.csv -o results.csv
puf-validator chat "What is the system status?"
puf-validator serve --host 127.0.0.1 --port 8000
```

The fuzzy reconstruction example uses a *repetition-code offset* and a fresh noisy PUF reading. This replaces an earlier insecure XOR-mask demonstration. It is **not** a production-ready fuzzy extractor: no source min-entropy estimate, secure-sketch proof, or privacy amplification guarantee is provided. Do not use derived values as real device keys.

The `puf_validator` and `agents` packages contain heuristic alert workflows with configurable example thresholds. Their outputs are not independent measurements of physical PUF reliability or attack resilience.

## HTTP API and Docker

The rule-based `agents` service runs with:

```bash
python -m uvicorn agents.api:app --host 127.0.0.1 --port 8000
```

Available routes include `GET /health`, `GET /metrics`, `POST /api/audit`, `POST /api/chat` and `GET /api/audit/logs`. The `puf-validator serve` command exposes a separate validator API, also with `/health`, `/api/audit`, and `/api/chat` endpoints. Use different ports if running both.

```bash
docker compose up --build
```

The container runs `agents.api:app` on port 8000. Configure `AUDIT_SECRET_KEY` in the environment for consistent HMAC signatures across process restarts. The in-memory audit trail is **not durable storage**.

## Testing

```bash
python -m compileall -q agents puf_validator cli.py simulator.py enrichment.py
pytest -v
node --check web/app.js
node --test web/app.test.js
```

GitHub Actions runs the Python test suite on Python 3.10, 3.11, and 3.12, plus browser JavaScript tests.

## Privacy, security, and limitations

- The browser simulator operates in the browser without uploads, third-party scripts, or remote API requests.
- Python API inputs and in-memory audit metadata remain within the running service. Do not submit patient information or real device secrets.
- The agent-side identifier guard uses limited pattern matching, **not** comprehensive PHI de-identification.
- Audit entries are chained and signed with HMAC-SHA256; the integrity checker verifies the signatures. The trail is memory-resident, not an external immutable ledger.
- Simulated responses, CRP exports, illustrative key material, and seeded pseudorandom outputs are unsuitable for authentication or cryptographic key provisioning.
- Standards mentioned in source are contextual references, not evidence of compliance.

## Technology and compatibility

Python 3.10+, Pydantic 2, FastAPI, Uvicorn, pytest; vanilla JavaScript and HTML/CSS for the browser app. The browser UI is designed for current Chromium, Firefox, and Safari releases. It uses standard DOM APIs and the Blob download API; no browser-specific compatibility matrix has been validated.

## License

MIT — see [LICENSE](LICENSE).
