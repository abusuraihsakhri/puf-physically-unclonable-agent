"""Regression coverage for length handling, PUF reconstruction, and audit integrity."""
import pytest

from simulator import (
    ArbiterPUF, CRPDatabase, FuzzyExtractor, PUFSimulator, RingOscillatorPUF,
    SRAMPUF, _hamming_distance, compute_bit_error_rate, compute_uniqueness,
)
from puf_validator.cli import parse_boolean
from agents.base import AuditTrail


def test_hamming_rejects_short_vectors():
    with pytest.raises(ValueError):
        _hamming_distance([1, 0, 1], [1, 0])
    with pytest.raises(ValueError):
        compute_bit_error_rate([[1]], [1, 0])
    with pytest.raises(ValueError):
        compute_uniqueness([[0, 1], [1]])
    with pytest.raises(ValueError):
        compute_uniqueness([[], []])


def test_non_byte_aligned_crps_preserve_lengths():
    db = CRPDatabase()
    db.enroll([1], [1, 0, 1])
    db.enroll([1, 0], [0, 0, 1, 0, 1])
    assert db.size == 2
    assert db.get_response([1]) == [1, 0, 1]
    assert db.get_response([1, 0]) == [0, 0, 1, 0, 1]
    assert db.verify([1], [1, 0, 1]) == (True, 0)
    with pytest.raises(ValueError):
        db.verify([1], [1, 0, 1, 0])


def test_fuzzy_reconstruction_uses_noisy_reading_and_tolerance():
    raw = [i % 2 for i in range(63)]
    f = FuzzyExtractor(63, error_tolerance=3, num_repetitions=3)
    enrolled, helper = f.enroll(raw)
    # The helper must not reveal the raw response via a public fixed pad.
    noisy = raw.copy()
    noisy[0] ^= 1
    noisy[9] ^= 1
    assert f.reproduce(noisy, helper) == enrolled
    noisy[12] ^= 1
    noisy[15] ^= 1
    with pytest.raises(ValueError, match="tolerance"):
        f.reproduce(noisy, helper)
    with pytest.raises(ValueError):
        f.reproduce(raw, helper[:-1])


def test_fuzzy_rejects_uncorrectable_majority():
    raw = [0] * 63
    f = FuzzyExtractor(63, error_tolerance=10)
    _, helper = f.enroll(raw)
    changed = raw.copy()
    changed[0] ^= 1
    changed[1] ^= 1
    recovered = f.reproduce(changed, helper)
    assert recovered != f._enrolled_key


def test_simulator_validates_dimensions():
    with pytest.raises(ValueError):
        SRAMPUF(num_cells=0)
    with pytest.raises(ValueError):
        ArbiterPUF(num_stages=0)
    with pytest.raises(ValueError):
        RingOscillatorPUF(num_oscillators=1)
    with pytest.raises(ValueError):
        SRAMPUF(device_seed=2**128)
    with pytest.raises(ValueError):
        PUFSimulator(num_devices=0)


def test_arbiter_ber_uses_majority_reference():
    sim = PUFSimulator("arbiter", num_devices=3, response_bits=32, noise_rate=0)
    assert sim.measure_reliability(0, 10) == 0.0
    assert 0.0 <= sim.measure_uniqueness(num_crps=20) <= 1.0


def test_csv_boolean_parsing():
    assert parse_boolean("FALSE") is False
    assert parse_boolean(" true ") is True
    assert parse_boolean("") is False
    assert parse_boolean("0") is False
    with pytest.raises(ValueError):
        parse_boolean("maybe")


def test_audit_signature_verification_detects_tampering():
    trail = AuditTrail(secret_key="test-not-production")
    entry = trail.log("auditor", "worker", "EVALUATION", {"status": "ok"})
    assert trail.verify_integrity()
    copy = trail.get_trail()
    copy[0]["actor"] = "external"
    assert trail.verify_integrity()  # callers cannot alter stored blocks
    trail.logs[0]["actor"] = "intruder"
    assert not trail.verify_integrity()


def test_mock_provider_is_not_misrepresented_as_live_inference():
    from agents.llm_factory import LLMFactory
    responder = LLMFactory.create("mock")
    assert "No model inference" in responder.invoke("status")
    with pytest.raises(ValueError, match="Unsupported provider"):
        LLMFactory.create("openai")


def test_validator_rejects_nonfinite_measurements():
    from puf_validator.engine import FrontierDomainEngine
    with pytest.raises(ValueError, match="finite"):
        FrontierDomainEngine.evaluate_primary_parameter(float("nan"))
    with pytest.raises(ValueError, match="finite"):
        FrontierDomainEngine.evaluate_secondary_kinetics(float("inf"), False)


def test_identifier_guard_blocks_known_patterns():
    from agents.base import PHIGuard, SecurityException
    with pytest.raises(SecurityException):
        PHIGuard.assert_no_phi("MRN:123456")
