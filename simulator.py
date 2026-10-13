"""
PUF (Physically Unclonable Function) Simulator.

Implements realistic simulations of hardware PUF types:
- SRAM PUF: power-up state depends on manufacturing variations
- Arbiter PUF: race condition between two delay paths
- Ring Oscillator PUF: frequency differences between oscillators
- Challenge-Response Pair (CRP) generation and management
- Reliability measurement (bit error rate across repeated measurements)
- Uniqueness measurement (inter-device Hamming distance)
- Helper data / fuzzy extractor for error correction

Uses only Python stdlib (hashlib, hmac, secrets, struct, math).
"""
import hashlib
import hmac
import secrets
import struct
import math
from typing import List, Tuple, Dict, Optional


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------

def _bits_to_bytes(bits: List[int]) -> bytes:
    """Convert a list of 0/1 bits to bytes (big-endian, MSB first)."""
    out = bytearray()
    for i in range(0, len(bits), 8):
        byte = 0
        for b in range(8):
            if i + b < len(bits):
                byte = (byte << 1) | (bits[i + b] & 1)
            else:
                byte <<= 1
        out.append(byte)
    return bytes(out)


def _bytes_to_bits(data: bytes) -> List[int]:
    """Convert bytes to a list of 0/1 bits (big-endian, MSB first)."""
    bits = []
    for byte in data:
        for b in range(7, -1, -1):
            bits.append((byte >> b) & 1)
    return bits


def _hamming_distance(a: List[int], b: List[int]) -> int:
    """Count differing bits; incompatible lengths are an error, not a partial match."""
    if len(a) != len(b):
        raise ValueError("Bit vectors must have the same length")
    return sum(x != y for x, y in zip(a, b))


def _positive_int(value: int, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _device_seed(seed: Optional[int]) -> int:
    if seed is None:
        return secrets.randbits(128)
    if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed < 2**128:
        raise ValueError("device_seed must be a 128-bit unsigned integer")
    return seed


def _bits(bits: List[int], name: str) -> None:
    if not bits or any(type(b) is not int or b not in (0, 1) for b in bits):
        raise ValueError(f"{name} must contain one or more binary bits")


def _seed_from_challenge(challenge: bytes, device_id: bytes) -> int:
    """Derive a deterministic seed from a challenge and device identity."""
    h = hmac.new(device_id, challenge, hashlib.sha256).digest()
    return int.from_bytes(h[:8], 'big')


# ---------------------------------------------------------------------------
# SRAM PUF
# ---------------------------------------------------------------------------

class SRAMPUF:
    """
    Simulates an SRAM PUF.

    On real hardware, each SRAM cell powers up to 0 or 1 depending on
    manufacturing variations (transistor threshold voltage mismatch).
    The simulator models this with a per-cell bias derived from a device
    seed.  Each cell has a deterministic preferred state (bias > 0.5 => 1,
    bias <= 0.5 => 0).  Repeated measurements flip bits with probability
    = noise_rate to model thermal noise.
    """

    def __init__(self, num_cells: int = 256, device_seed: Optional[int] = None,
                 noise_rate: float = 0.02):
        _positive_int(num_cells, "num_cells")
        if not 0.0 <= noise_rate <= 0.5:
            raise ValueError("noise_rate must be in [0.0, 0.5]")
        self.num_cells = num_cells
        self.noise_rate = noise_rate
        self._seed = _device_seed(device_seed)
        # Generate per-cell bias from seed.  Bias > 0.5 => cell tends to 1.
        self._biases = self._generate_biases()

    def _generate_biases(self) -> List[float]:
        """Generate per-cell power-up bias from device seed."""
        biases = []
        seed_bytes = self._seed.to_bytes(16, 'big')
        for i in range(self.num_cells):
            h = hashlib.sha256(
                seed_bytes + struct.pack('<I', i)
            ).digest()
            # Use first 4 bytes as a 32-bit float proxy
            val = int.from_bytes(h[:4], 'big') / 0xFFFFFFFF
            # Map to [0.05, 0.95] so cells are strongly biased
            bias = 0.05 + val * 0.90
            biases.append(bias)
        return biases

    def power_up(self) -> List[int]:
        """Simulate one power-up cycle. Returns list of 0/1 bits.

        The base value is deterministic from the cell bias (bias > 0.5 => 1).
        Noise flips bits with probability = noise_rate to model thermal noise.
        """
        bits = []
        for i in range(self.num_cells):
            # Base value: deterministic from bias (preferred power-up state)
            base = 1 if self._biases[i] > 0.5 else 0
            # Noise flip
            if secrets.randbelow(10000) / 10000.0 < self.noise_rate:
                base ^= 1
            bits.append(base)
        return bits

    def measure_reliability(self, num_trials: int = 100) -> Tuple[List[int], float]:
        """
        Measure reliability by performing multiple power-ups.

        Returns (reference_bits, bit_error_rate).
        The reference is the majority-vote across all trials.
        """
        if num_trials < 2:
            raise ValueError("Need at least 2 trials for reliability measurement")
        accumulators = [0] * self.num_cells
        trials = []
        for _ in range(num_trials):
            bits = self.power_up()
            trials.append(bits)
            for i, b in enumerate(bits):
                accumulators[i] += b

        # Majority vote reference
        reference = [1 if accumulators[i] > num_trials // 2 else 0
                     for i in range(self.num_cells)]

        # Compute average BER against reference
        total_errors = 0
        for trial in trials:
            total_errors += _hamming_distance(reference, trial)
        ber = total_errors / (num_trials * self.num_cells)
        return reference, ber


# ---------------------------------------------------------------------------
# Arbiter PUF
# ---------------------------------------------------------------------------

class ArbiterPUF:
    """
    Simulates an Arbiter PUF.

    A challenge bit stream selects between two delay paths.  Each stage
    has a pair of delays (upper, lower).  A challenge bit of 0 means
    straight-through; 1 means cross.  The arbiter outputs 0 if the upper
    path is faster, 1 otherwise.

    The response is deterministic for a given (device, challenge) pair.
    Noise is modelled by occasionally flipping the final comparison.
    """

    def __init__(self, num_stages: int = 64, device_seed: Optional[int] = None,
                 noise_sigma: float = 0.0):
        _positive_int(num_stages, "num_stages")
        if not 0.0 <= noise_sigma < float("inf"):
            raise ValueError("noise_sigma must be finite and non-negative")
        self.num_stages = num_stages
        self.noise_sigma = noise_sigma
        self._seed = _device_seed(device_seed)
        # Generate per-stage delay parameters
        self._delta_delays = self._generate_stage_delays()

    def _generate_stage_delays(self) -> List[Tuple[float, float]]:
        """Generate (delta_upper, delta_lower) for each stage from device seed."""
        stages = []
        seed_bytes = self._seed.to_bytes(16, 'big')
        for i in range(self.num_stages):
            h = hashlib.sha256(
                seed_bytes + struct.pack('<I', i)
            ).digest()
            # Two floats from hash
            du = (int.from_bytes(h[0:4], 'big') / 0xFFFFFFFF) * 2.0 - 1.0  # [-1, 1]
            dl = (int.from_bytes(h[4:8], 'big') / 0xFFFFFFFF) * 2.0 - 1.0
            stages.append((du, dl))
        return stages

    def evaluate(self, challenge: List[int]) -> int:
        """
        Evaluate the arbiter PUF for a given challenge.

        Returns 0 or 1.
        """
        if len(challenge) != self.num_stages:
            raise ValueError(f"Challenge must be {self.num_stages} bits")
        _bits(challenge, "challenge")

        # Accumulate delay difference
        delta_upper = 0.0
        delta_lower = 0.0
        for i, bit in enumerate(challenge):
            du, dl = self._delta_delays[i]
            if bit == 0:
                # Straight: upper stays upper, lower stays lower
                delta_upper += du
                delta_lower += dl
            else:
                # Cross: swap
                delta_upper += dl
                delta_lower += du

        # Add Gaussian noise if configured
        if self.noise_sigma > 0:
            import random
            delta_upper += random.gauss(0, self.noise_sigma)
            delta_lower += random.gauss(0, self.noise_sigma)

        # Arbiter: if upper path is faster (smaller delay) => 0, else 1
        return 0 if delta_upper <= delta_lower else 1

    def generate_response(self, challenge: List[int]) -> int:
        """Alias for evaluate()."""
        return self.evaluate(challenge)


# ---------------------------------------------------------------------------
# Ring Oscillator PUF
# ---------------------------------------------------------------------------

class RingOscillatorPUF:
    """
    Simulates a Ring Oscillator PUF.

    Each ring oscillator has a characteristic frequency determined by
    manufacturing variations.  A challenge selects a pair of oscillators;
    the response is 1 if the first oscillator is faster, 0 otherwise.
    """

    def __init__(self, num_oscillators: int = 128, device_seed: Optional[int] = None,
                 noise_rate: float = 0.01):
        if num_oscillators < 2:
            raise ValueError("num_oscillators must be at least 2")
        _positive_int(num_oscillators, "num_oscillators")
        if not 0.0 <= noise_rate < float("inf"):
            raise ValueError("noise_rate must be finite and non-negative")
        self.num_oscillators = num_oscillators
        self.noise_rate = noise_rate
        self._seed = _device_seed(device_seed)
        self._frequencies = self._generate_frequencies()

    def _generate_frequencies(self) -> List[float]:
        """Generate characteristic frequency for each oscillator."""
        freqs = []
        seed_bytes = self._seed.to_bytes(16, 'big')
        for i in range(self.num_oscillators):
            h = hashlib.sha256(
                seed_bytes + struct.pack('<I', i)
            ).digest()
            # Map to frequency range [100 MHz, 200 MHz] with fine granularity
            val = int.from_bytes(h[:4], 'big') / 0xFFFFFFFF
            freq = 100.0 + val * 100.0  # MHz
            freqs.append(freq)
        return freqs

    def compare(self, idx_a: int, idx_b: int) -> int:
        """
        Compare two oscillators. Returns 1 if osc_a is faster, else 0.

        The challenge is the pair selection; the response is the comparison.
        """
        if not (0 <= idx_a < self.num_oscillators):
            raise IndexError(f"idx_a={idx_a} out of range [0, {self.num_oscillators})")
        if not (0 <= idx_b < self.num_oscillators):
            raise IndexError(f"idx_b={idx_b} out of range [0, {self.num_oscillators})")

        fa = self._frequencies[idx_a]
        fb = self._frequencies[idx_b]

        # Noise: small random perturbation
        if self.noise_rate > 0:
            import random
            fa += random.gauss(0, fa * self.noise_rate)
            fb += random.gauss(0, fb * self.noise_rate)

        return 1 if fa > fb else 0

    def evaluate_challenge(self, challenge_pairs: List[Tuple[int, int]]) -> List[int]:
        """
        Evaluate a list of (idx_a, idx_b) pairs, returning one bit per pair.
        """
        return [self.compare(a, b) for a, b in challenge_pairs]


# ---------------------------------------------------------------------------
# Challenge-Response Pair (CRP) Management
# ---------------------------------------------------------------------------

class CRPDatabase:
    """In-memory challenge-response enrollment and Hamming-distance verification.

    Original bit lengths are retained to distinguish byte-padded challenges.
    Export uses packed bytes for compatibility; it does not encode bit lengths.
    """

    def __init__(self):
        self._crps: Dict[Tuple[bytes, int], Tuple[bytes, int]] = {}
        self._challenge_bits: Dict[Tuple[bytes, int], List[int]] = {}

    @staticmethod
    def _key(challenge: List[int]) -> Tuple[bytes, int]:
        _bits(challenge, "challenge")
        return _bits_to_bytes(challenge), len(challenge)

    def enroll(self, challenge: List[int], response: List[int]) -> None:
        _bits(response, "response")
        key = self._key(challenge)
        self._crps[key] = (_bits_to_bytes(response), len(response))
        self._challenge_bits[key] = list(challenge)

    def verify(self, challenge: List[int], response: List[int],
               max_bit_errors: int = 0) -> Tuple[bool, int]:
        if max_bit_errors < 0:
            raise ValueError("max_bit_errors must be non-negative")
        _bits(response, "response")
        reference = self.get_response(challenge)
        hd = _hamming_distance(reference, response)
        return hd <= max_bit_errors, hd

    def get_response(self, challenge: List[int]) -> List[int]:
        key = self._key(challenge)
        if key not in self._crps:
            raise KeyError("Challenge not found in CRP database")
        packed, length = self._crps[key]
        return _bytes_to_bits(packed)[:length]

    @property
    def size(self) -> int:
        return len(self._crps)

    def export_crps(self) -> List[Tuple[bytes, bytes]]:
        """Export packed CRPs (bit lengths are not represented in this format)."""
        return [(challenge[0], packed) for challenge, (packed, _) in self._crps.items()]

    def challenges(self) -> List[List[int]]:
        return [list(self._challenge_bits[c]) for c in self._crps]


# ---------------------------------------------------------------------------
# Fuzzy Extractor / Helper Data for Error Correction
# ---------------------------------------------------------------------------

class FuzzyExtractor:
    """Educational code-offset reconstruction using a repetition code.

    Enrolls a random repeated codeword C, publishing helper data R XOR C.
    A fresh noisy PUF reading R' gives C XOR noise, which is decoded by
    majority vote. The previous XOR-with-public-fixed-pad scheme leaked R
    directly and performed no error correction.

    This is not a production-grade fuzzy extractor: repetition codes have
    low efficiency and no entropy estimation or security proof is provided.
    """

    def __init__(self, response_length: int, error_tolerance: int = 5,
                 num_repetitions: int = 3):
        _positive_int(response_length, "response_length")
        if isinstance(num_repetitions, bool) or not isinstance(num_repetitions, int) or num_repetitions < 3 or num_repetitions % 2 != 1:
            raise ValueError("num_repetitions must be an odd integer >= 3")
        if response_length < num_repetitions:
            raise ValueError("response_length must be at least num_repetitions")
        if isinstance(error_tolerance, bool) or not isinstance(error_tolerance, int) or error_tolerance < 0:
            raise ValueError("error_tolerance must be a non-negative integer")
        self.response_length = response_length
        self.error_tolerance = error_tolerance
        self.num_repetitions = num_repetitions
        self._helper_data: Optional[bytes] = None
        self._enrolled_key: Optional[List[int]] = None

    def _block_sizes(self) -> List[int]:
        count, remainder = divmod(self.response_length, self.num_repetitions)
        return [self.num_repetitions] * (count - 1) + [self.num_repetitions + remainder]

    def enroll(self, raw_response: List[int]) -> Tuple[List[int], bytes]:
        if len(raw_response) < self.response_length:
            raise ValueError("Response too short")
        r = raw_response[:self.response_length]
        _bits(r, "raw_response")

        codeword: List[int] = []
        for size in self._block_sizes():
            codeword.extend([secrets.randbelow(2)] * size)
        helper = [r[i] ^ codeword[i] for i in range(self.response_length)]

        self._helper_data = _bits_to_bytes(helper)
        self._enrolled_key = list(codeword)
        return list(codeword), self._helper_data

    def reproduce(self, noisy_response: List[int], helper_data: bytes) -> List[int]:
        if len(noisy_response) < self.response_length:
            raise ValueError("Response too short")
        if len(helper_data) != (self.response_length + 7) // 8:
            raise ValueError("Invalid helper data length")
        reading = noisy_response[:self.response_length]
        _bits(reading, "noisy_response")
        helper = _bytes_to_bits(helper_data)[:self.response_length]
        encoded = [reading[i] ^ helper[i] for i in range(self.response_length)]

        recovered: List[int] = []
        offset = 0
        for size in self._block_sizes():
            block = encoded[offset:offset + size]
            ones = sum(block)
            if ones * 2 == size:
                raise ValueError("Ambiguous repetition block: equal number of zeros and ones")
            recovered.extend([int(ones * 2 > size)] * size)
            offset += size

        if _hamming_distance(encoded, recovered) > self.error_tolerance:
            raise ValueError("Noise exceeds error tolerance")
        return recovered

    def generate_key(self, response: List[int], key_length: int = 128) -> bytes:
        """Illustrative HMAC-based key expansion; output entropy is not guaranteed."""
        if len(response) < self.response_length:
            raise ValueError("Response too short")
        _bits(response[:self.response_length], "response")
        if not isinstance(key_length, int) or isinstance(key_length, bool) or key_length < 8 or key_length % 8 or key_length > 255 * 256:
            raise ValueError("key_length must be 8..65280 bits and divisible by 8")
        response_bytes = _bits_to_bytes(response[:self.response_length])
        prk = hmac.new(b"puf-key-extract", response_bytes, hashlib.sha256).digest()
        out = bytearray()
        block = b""
        counter = 1
        while len(out) < key_length // 8:
            block = hmac.new(prk, block + b"puf-simulation-key" + bytes([counter]), hashlib.sha256).digest()
            out.extend(block)
            counter += 1
        return bytes(out[:key_length // 8])


# ---------------------------------------------------------------------------
# Uniqueness / Inter-device Analysis
# ---------------------------------------------------------------------------

def compute_uniqueness(devices_responses: List[List[int]]) -> float:
    """
    Compute inter-device uniqueness as average pairwise Hamming distance.

    Target is ~50% for a good PUF.

    Args:
        devices_responses: list of response bit-lists, one per device

    Returns:
        Average fractional Hamming distance [0.0, 1.0]
    """
    n = len(devices_responses)
    if n < 2:
        raise ValueError("Need at least 2 devices for uniqueness computation")
    bit_len = len(devices_responses[0])
    if bit_len == 0 or any(len(r) != bit_len for r in devices_responses):
        raise ValueError("All device responses must have the same nonzero length")

    total_hd = 0
    total_pairs = 0
    for i in range(n):
        for j in range(i + 1, n):
            hd = _hamming_distance(devices_responses[i], devices_responses[j])
            total_hd += hd
            total_pairs += 1

    return (total_hd / total_pairs) / bit_len


def compute_bit_error_rate(measurements: List[List[int]],
                           reference: List[int]) -> float:
    """
    Compute the bit error rate of a set of measurements against a reference.

    Args:
        measurements: list of measurement bit-lists
        reference: reference bit-list

    Returns:
        BER as a fraction [0.0, 1.0]
    """
    if not measurements:
        raise ValueError("Empty measurements list")
    if not reference or any(len(m) != len(reference) for m in measurements):
        raise ValueError("Measurements and reference must have the same nonzero length")
    total_errors = 0
    total_bits = 0
    for m in measurements:
        total_errors += _hamming_distance(m, reference)
        total_bits += len(reference)
    return total_errors / total_bits if total_bits > 0 else 0.0


# ---------------------------------------------------------------------------
# High-level PUF Simulator combining all types
# ---------------------------------------------------------------------------

class PUFSimulator:
    """
    High-level PUF simulator that can create and manage multiple PUF devices,
    generate CRPs, measure reliability and uniqueness.
    """

    def __init__(self, puf_type: str = 'sram', num_devices: int = 2,
                 response_bits: int = 256, noise_rate: float = 0.02):
        valid_types = ('sram', 'arbiter', 'ring_oscillator')
        if puf_type not in valid_types:
            raise ValueError(f"puf_type must be one of {valid_types}")
        _positive_int(num_devices, "num_devices")
        _positive_int(response_bits, "response_bits")
        if puf_type == 'ring_oscillator' and response_bits < 2:
            raise ValueError("Ring oscillator simulation needs at least 2 oscillators")
        self.puf_type = puf_type
        self.num_devices = num_devices
        self.response_bits = response_bits
        self.noise_rate = noise_rate
        self._devices = []
        self._crp_databases: List[CRPDatabase] = []
        self._create_devices()

    def _create_devices(self):
        """Create PUF device instances."""
        for i in range(self.num_devices):
            seed = secrets.randbits(128)
            if self.puf_type == 'sram':
                dev = SRAMPUF(self.response_bits, seed, self.noise_rate)
            elif self.puf_type == 'arbiter':
                dev = ArbiterPUF(self.response_bits, seed, self.noise_rate)
            else:  # ring_oscillator
                dev = RingOscillatorPUF(self.response_bits, seed, self.noise_rate)
            self._devices.append(dev)
            self._crp_databases.append(CRPDatabase())

    def _generate_response(self, device_idx: int, challenge: List[int]) -> List[int]:
        """Generate a response from a device for a given challenge."""
        dev = self._devices[device_idx]
        if self.puf_type == 'sram':
            return dev.power_up()
        elif self.puf_type == 'arbiter':
            return [dev.evaluate(challenge)]
        else:  # ring_oscillator
            # Use oscillator pairs spanning the whole device, not just indices 0/1.
            pairs = []
            for i in range(0, len(challenge) - 1, 2):
                a, b = i % dev.num_oscillators, (i + 1) % dev.num_oscillators
                pairs.append((b, a) if challenge[i] else (a, b))
            return dev.evaluate_challenge(pairs)

    def generate_challenge(self) -> List[int]:
        """Generate a random challenge."""
        return [secrets.randbelow(2) for _ in range(self.response_bits)]

    def enroll_device(self, device_idx: int, num_crps: int = 10) -> CRPDatabase:
        """
        Enroll a device by generating and storing CRPs.

        Returns the CRP database for the device.
        """
        db = self._crp_databases[device_idx]
        for _ in range(num_crps):
            challenge = self.generate_challenge()
            response = self._generate_response(device_idx, challenge)
            db.enroll(challenge, response)
        return db

    def measure_reliability(self, device_idx: int, num_trials: int = 50) -> float:
        """Measure reliability (BER) for a device."""
        dev = self._devices[device_idx]
        if isinstance(dev, SRAMPUF):
            _, ber = dev.measure_reliability(num_trials)
            return ber
        else:
            if num_trials < 2:
                raise ValueError("Need at least 2 trials for reliability measurement")
            challenge = self.generate_challenge()
            responses = [self._generate_response(device_idx, challenge)
                         for _ in range(num_trials)]
            bit_count = len(responses[0])
            reference = [int(sum(r[i] for r in responses) > num_trials / 2)
                         for i in range(bit_count)]
            return compute_bit_error_rate(responses, reference)

    def measure_uniqueness(self, num_crps: int = 10) -> float:
        """Measure inter-device uniqueness."""
        _positive_int(num_crps, "num_crps")
        if self.num_devices < 2:
            raise ValueError("Need at least 2 devices for uniqueness computation")
        scores = []
        for _ in range(num_crps):
            challenge = self.generate_challenge()
            responses = [self._generate_response(i, challenge)
                         for i in range(self.num_devices)]
            scores.append(compute_uniqueness(responses))
        return sum(scores) / len(scores)

    def get_device(self, device_idx: int):
        """Get the underlying PUF device."""
        return self._devices[device_idx]

    def get_crp_database(self, device_idx: int) -> CRPDatabase:
        """Get the CRP database for a device."""
        return self._crp_databases[device_idx]
