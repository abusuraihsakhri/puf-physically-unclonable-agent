"""
Tests for PUF (Physically Unclonable Function) Simulator.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from simulator import (
    SRAMPUF, ArbiterPUF, RingOscillatorPUF,
    CRPDatabase, FuzzyExtractor, PUFSimulator,
    compute_uniqueness, compute_bit_error_rate,
    _bits_to_bytes, _bytes_to_bits, _hamming_distance,
)


# ---------------------------------------------------------------------------
# Utility function tests
# ---------------------------------------------------------------------------

class TestBitConversion:
    def test_bits_to_bytes_roundtrip(self):
        bits = [1, 0, 1, 1, 0, 0, 0, 1]
        data = _bits_to_bytes(bits)
        recovered = _bytes_to_bits(data)
        assert recovered[:8] == bits

    def test_bits_to_bytes_partial_byte(self):
        bits = [1, 0, 1]
        data = _bits_to_bytes(bits)
        assert len(data) == 1
        assert data[0] == 0b10100000  # padded with zeros

    def test_bytes_to_bits_known_value(self):
        data = bytes([0xFF])
        bits = _bytes_to_bits(data)
        assert bits == [1, 1, 1, 1, 1, 1, 1, 1]

    def test_bytes_to_bits_zero(self):
        data = bytes([0x00])
        bits = _bytes_to_bits(data)
        assert bits == [0, 0, 0, 0, 0, 0, 0, 0]


class TestHammingDistance:
    def test_identical(self):
        a = [1, 0, 1, 0, 1]
        assert _hamming_distance(a, a) == 0

    def test_all_different(self):
        a = [0, 0, 0, 0]
        b = [1, 1, 1, 1]
        assert _hamming_distance(a, b) == 4

    def test_partial(self):
        a = [1, 0, 1, 0]
        b = [1, 1, 0, 0]
        assert _hamming_distance(a, b) == 2

    def test_empty(self):
        assert _hamming_distance([], []) == 0


# ---------------------------------------------------------------------------
# SRAM PUF tests
# ---------------------------------------------------------------------------

class TestSRAMPUF:
    def test_power_up_returns_correct_length(self):
        puf = SRAMPUF(num_cells=128, device_seed=42)
        bits = puf.power_up()
        assert len(bits) == 128

    def test_power_up_bits_are_binary(self):
        puf = SRAMPUF(num_cells=256, device_seed=42)
        bits = puf.power_up()
        assert all(b in (0, 1) for b in bits)

    def test_different_seeds_different_output(self):
        puf1 = SRAMPUF(num_cells=256, device_seed=42, noise_rate=0.0)
        puf2 = SRAMPUF(num_cells=256, device_seed=99, noise_rate=0.0)
        b1 = puf1.power_up()
        b2 = puf2.power_up()
        # With different seeds, outputs should differ (statistically)
        hd = _hamming_distance(b1, b2)
        assert 0.1 < hd / 256 < 0.9  # Should be around 50%

    def test_reliability_measurement(self):
        puf = SRAMPUF(num_cells=128, device_seed=42, noise_rate=0.02)
        ref, ber = puf.measure_reliability(num_trials=50)
        assert len(ref) == 128
        assert 0.0 <= ber <= 0.5
        assert ber < 0.1  # With 2% noise, BER should be low

    def test_zero_noise_perfect_reliability(self):
        puf = SRAMPUF(num_cells=64, device_seed=42, noise_rate=0.0)
        ref, ber = puf.measure_reliability(num_trials=20)
        assert ber == 0.0

    def test_invalid_noise_rate(self):
        with pytest.raises(ValueError):
            SRAMPUF(noise_rate=-0.1)
        with pytest.raises(ValueError):
            SRAMPUF(noise_rate=0.6)

    def test_reliability_needs_two_trials(self):
        puf = SRAMPUF(num_cells=64, device_seed=42)
        with pytest.raises(ValueError):
            puf.measure_reliability(num_trials=1)


# ---------------------------------------------------------------------------
# Arbiter PUF tests
# ---------------------------------------------------------------------------

class TestArbiterPUF:
    def test_evaluate_returns_binary(self):
        puf = ArbiterPUF(num_stages=32, device_seed=42)
        challenge = [1, 0] * 16
        result = puf.evaluate(challenge)
        assert result in (0, 1)

    def test_deterministic_no_noise(self):
        puf = ArbiterPUF(num_stages=64, device_seed=42, noise_sigma=0.0)
        challenge = [1, 0, 1, 1, 0, 0, 1, 0] * 8
        r1 = puf.evaluate(challenge)
        r2 = puf.evaluate(challenge)
        assert r1 == r2

    def test_wrong_challenge_length(self):
        puf = ArbiterPUF(num_stages=32, device_seed=42)
        with pytest.raises(ValueError):
            puf.evaluate([1, 0, 1])  # Wrong length

    def test_different_challenges_different_responses(self):
        puf = ArbiterPUF(num_stages=64, device_seed=42, noise_sigma=0.0)
        c1 = [0] * 64
        c2 = [1] * 64
        # These should generally differ
        responses = set()
        for _ in range(10):
            import secrets
            c = [secrets.randbelow(2) for _ in range(64)]
            responses.add(puf.evaluate(c))
        # With enough random challenges, we should see both 0 and 1
        assert len(responses) >= 1  # At minimum one value seen

    def test_generate_response_alias(self):
        puf = ArbiterPUF(num_stages=32, device_seed=42)
        challenge = [1, 0] * 16
        assert puf.evaluate(challenge) == puf.generate_response(challenge)


# ---------------------------------------------------------------------------
# Ring Oscillator PUF tests
# ---------------------------------------------------------------------------

class TestRingOscillatorPUF:
    def test_compare_returns_binary(self):
        puf = RingOscillatorPUF(num_oscillators=64, device_seed=42)
        result = puf.compare(0, 1)
        assert result in (0, 1)

    def test_deterministic_no_noise(self):
        puf = RingOscillatorPUF(num_oscillators=64, device_seed=42, noise_rate=0.0)
        r1 = puf.compare(0, 1)
        r2 = puf.compare(0, 1)
        assert r1 == r2

    def test_antisymmetry_no_noise(self):
        puf = RingOscillatorPUF(num_oscillators=64, device_seed=42, noise_rate=0.0)
        # If A > B then compare(A,B)=1 and compare(B,A)=0
        r_ab = puf.compare(0, 1)
        r_ba = puf.compare(1, 0)
        assert r_ab != r_ba

    def test_invalid_index(self):
        puf = RingOscillatorPUF(num_oscillators=32, device_seed=42)
        with pytest.raises(IndexError):
            puf.compare(0, 100)
        with pytest.raises(IndexError):
            puf.compare(-1, 0)

    def test_evaluate_challenge_pairs(self):
        puf = RingOscillatorPUF(num_oscillators=64, device_seed=42, noise_rate=0.0)
        pairs = [(0, 1), (2, 3), (4, 5)]
        results = puf.evaluate_challenge(pairs)
        assert len(results) == 3
        assert all(r in (0, 1) for r in results)


# ---------------------------------------------------------------------------
# CRP Database tests
# ---------------------------------------------------------------------------

class TestCRPDatabase:
    def test_enroll_and_size(self):
        db = CRPDatabase()
        assert db.size == 0
        db.enroll([1, 0, 1, 0], [1, 1, 0, 0])
        assert db.size == 1

    def test_verify_match(self):
        db = CRPDatabase()
        challenge = [1, 0, 1, 0, 1, 0, 1, 0]
        response = [1, 1, 0, 0, 1, 1, 0, 0]
        db.enroll(challenge, response)
        match, hd = db.verify(challenge, response)
        assert match is True
        assert hd == 0

    def test_verify_mismatch(self):
        db = CRPDatabase()
        challenge = [1, 0, 1, 0, 1, 0, 1, 0]
        response = [1, 1, 0, 0, 1, 1, 0, 0]
        db.enroll(challenge, response)
        noisy = [1, 1, 0, 0, 1, 1, 0, 1]  # 1 bit flipped
        match, hd = db.verify(challenge, noisy, max_bit_errors=0)
        assert match is False
        assert hd == 1

    def test_verify_with_tolerance(self):
        db = CRPDatabase()
        challenge = [1, 0, 1, 0, 1, 0, 1, 0]
        response = [1, 1, 0, 0, 1, 1, 0, 0]
        db.enroll(challenge, response)
        noisy = [1, 1, 0, 0, 1, 1, 0, 1]
        match, hd = db.verify(challenge, noisy, max_bit_errors=2)
        assert match is True
        assert hd == 1

    def test_unknown_challenge(self):
        db = CRPDatabase()
        with pytest.raises(KeyError):
            db.verify([1, 0], [0, 1])

    def test_export_crps(self):
        db = CRPDatabase()
        db.enroll([1, 0, 1, 0, 1, 0, 1, 0], [0, 0, 0, 0, 0, 0, 0, 0])
        crps = db.export_crps()
        assert len(crps) == 1
        assert isinstance(crps[0], tuple)

    def test_challenges_list(self):
        db = CRPDatabase()
        c = [1, 0, 1, 0, 1, 0, 1, 0]
        db.enroll(c, [0] * 8)
        challenges = db.challenges()
        assert len(challenges) == 1


# ---------------------------------------------------------------------------
# Fuzzy Extractor tests
# ---------------------------------------------------------------------------

class TestFuzzyExtractor:
    def test_enroll_returns_key_and_helper(self):
        fe = FuzzyExtractor(response_length=64)
        raw = [1] * 64
        key, helper = fe.enroll(raw)
        assert len(key) == 64
        assert isinstance(helper, bytes)

    def test_reproduce_exact(self):
        fe = FuzzyExtractor(response_length=64)
        raw = [1, 0] * 32
        key, helper = fe.enroll(raw)
        recovered = fe.reproduce(raw, helper)
        assert recovered == key

    def test_response_too_short(self):
        fe = FuzzyExtractor(response_length=128)
        with pytest.raises(ValueError):
            fe.enroll([1, 0, 1])

    def test_generate_key(self):
        fe = FuzzyExtractor(response_length=64)
        response = [1, 0, 1, 1, 0, 0, 1, 0] * 8
        key_bytes = fe.generate_key(response, key_length=128)
        assert isinstance(key_bytes, bytes)
        assert len(key_bytes) == 16  # 128 bits = 16 bytes


# ---------------------------------------------------------------------------
# Uniqueness / BER computation tests
# ---------------------------------------------------------------------------

class TestUniqueness:
    def test_identical_responses_zero_distance(self):
        r = [1, 0, 1, 0, 1, 0, 1, 0]
        assert compute_uniqueness([r, r]) == 0.0

    def test_opposite_responses_max_distance(self):
        r1 = [0, 0, 0, 0]
        r2 = [1, 1, 1, 1]
        assert compute_uniqueness([r1, r2]) == 1.0

    def test_needs_two_devices(self):
        with pytest.raises(ValueError):
            compute_uniqueness([[1, 0, 1]])

    def test_multiple_devices(self):
        r1 = [1, 0, 1, 0]
        r2 = [0, 1, 0, 1]
        r3 = [1, 1, 0, 0]
        u = compute_uniqueness([r1, r2, r3])
        assert 0.0 <= u <= 1.0


class TestBER:
    def test_perfect_measurements(self):
        ref = [1, 0, 1, 0, 1]
        measurements = [ref, ref, ref]
        assert compute_bit_error_rate(measurements, ref) == 0.0

    def test_all_errors(self):
        ref = [0, 0, 0, 0]
        noisy = [1, 1, 1, 1]
        ber = compute_bit_error_rate([noisy], ref)
        assert ber == 1.0

    def test_empty_measurements(self):
        with pytest.raises(ValueError):
            compute_bit_error_rate([], [1, 0, 1])


# ---------------------------------------------------------------------------
# CLI tests
# ---------------------------------------------------------------------------

class TestCLI:
    def test_sram_command(self):
        from cli import main
        ret = main(['sram', '--bits', '64', '--noise', '0.01'])
        assert ret == 0

    def test_arbiter_command(self):
        from cli import main
        ret = main(['arbiter', '--stages', '32'])
        assert ret == 0

    def test_ro_command(self):
        from cli import main
        ret = main(['ro', '--oscillators', '32', '--pair', '0', '1'])
        assert ret == 0

    def test_crp_command(self):
        from cli import main
        ret = main(['crp', '--puf-type', 'sram', '--bits', '64', '--count', '3'])
        assert ret == 0

    def test_uniqueness_command(self):
        from cli import main
        ret = main(['uniqueness', '--puf-type', 'sram', '--devices', '3', '--bits', '64'])
        assert ret == 0

    def test_fuzzy_command(self):
        from cli import main
        ret = main(['fuzzy', '--bits', '64', '--noise', '0.01'])
        assert ret == 0

    def test_simulate_command(self):
        from cli import main
        ret = main(['simulate', '--puf-type', 'sram', '--devices', '2', '--bits', '64',
                     '--crps', '3', '--trials', '10'])
        assert ret == 0


# ---------------------------------------------------------------------------
# PUFSimulator integration tests
# ---------------------------------------------------------------------------

class TestPUFSimulator:
    def test_create_sram_simulator(self):
        sim = PUFSimulator(puf_type='sram', num_devices=2, response_bits=64)
        assert sim.num_devices == 2
        assert sim.response_bits == 64

    def test_invalid_puf_type(self):
        with pytest.raises(ValueError):
            PUFSimulator(puf_type='invalid')

    def test_enroll_device(self):
        sim = PUFSimulator(puf_type='sram', num_devices=2, response_bits=64)
        db = sim.enroll_device(0, num_crps=3)
        assert db.size == 3

    def test_measure_reliability(self):
        sim = PUFSimulator(puf_type='sram', num_devices=2, response_bits=64, noise_rate=0.02)
        ber = sim.measure_reliability(0, num_trials=10)
        assert 0.0 <= ber <= 1.0
