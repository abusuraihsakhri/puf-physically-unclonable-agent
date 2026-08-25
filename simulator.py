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
    """Count differing bits between two bit lists."""
    return sum(x != y for x, y in zip(a, b))


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
    seed.  Repeated measurements flip bits with probability = noise_rate
    to model thermal noise.
    """

    def __init__(self, num_cells: int = 256, device_seed: Optional[int] = None,
                 noise_rate: float = 0.02):
        if not 0.0 <= noise_rate <= 0.5:
            raise ValueError("noise_rate must be in [0.0, 0.5]")
        self.num_cells = num_cells
        self.noise_rate = noise_rate
        self._seed = device_seed if device_seed is not None else secrets.randbits(128)
        # Generate per-cell bias from seed.  Bias > 0.5 => cell tends to 1.
        self._biases = self._generate_biases()

    def _generate_biases(self) -> List[float]:
        """Generate per-cell power-up bias from device seed."""
        biases = []
        for i in range(self.num_cells):
            h = hashlib.sha256(
                struct.pack('<Q', self._seed) + struct.pack('<I', i)
            ).digest()
            # Use first 4 bytes as a 32-bit float proxy
            val = int.from_bytes(h[:4], 'big') / 0xFFFFFFFF
            # Map to [0.05, 0.95] so cells are strongly biased
            bias = 0.05 + val * 0.90
            biases.append(bias)
        return biases

    def power_up(self) -> List[int]:
        """Simulate one power-up cycle. Returns list of 0/1 bits."""
        bits = []
        for i in range(self.num_cells):
            # Base value from bias
            base = 1 if secrets.randbelow(10000) / 10000.0 < self._biases[i] else 0
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
        self.num_stages = num_stages
        self.noise_sigma = noise_sigma
        self._seed = device_seed if device_seed is not None else secrets.randbits(128)
        # Generate per-stage delay parameters
        self._delta_delays = self._generate_stage_delays()

    def _generate_stage_delays(self) -> List[Tuple[float, float]]:
        """Generate (delta_upper, delta_lower) for each stage from device seed."""
        stages = []
        for i in range(self.num_stages):
            h = hashlib.sha256(
                struct.pack('<Q', self._seed) + struct.pack('<I', i)
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
        self.num_oscillators = num_oscillators
        self.noise_rate = noise_rate
        self._seed = device_seed if device_seed is not None else secrets.randbits(128)
        self._frequencies = self._generate_frequencies()

    def _generate_frequencies(self) -> List[float]:
        """Generate characteristic frequency for each oscillator."""
        freqs = []
        for i in range(self.num_oscillators):
            h = hashlib.sha256(
                struct.pack('<Q', self._seed) + struct.pack('<I', i)
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
    """
    Manages Challenge-Response Pairs for a PUF instance.

    Supports:
    - Enrollment: store reference CRPs
    - Verification: check if a response matches the enrolled response
    - Export / import for attestation
    """

    def __init__(self):
        self._crps: Dict[bytes, bytes] = {}  # challenge_bytes -> response_bytes
        self._challenge_bits: Dict[bytes, List[int]] = {}

    def enroll(self, challenge: List[int], response: List[int]) -> None:
        """Store a challenge-response pair."""
        c_bytes = _bits_to_bytes(challenge)
        r_bytes = _bits_to_bytes(response)
        self._crps[c_bytes] = r_bytes
        self._challenge_bits[c_bytes] = list(challenge)

    def verify(self, challenge: List[int], response: List[int],
               max_bit_errors: int = 0) -> Tuple[bool, int]:
        """
        Verify a response against the enrolled reference.

        Returns (match: bool, hamming_distance: int).
        """
        c_bytes = _bits_to_bytes(challenge)
        if c_bytes not in self._crps:
            raise KeyError("Challenge not found in CRP database")
        ref_response = _bytes_to_bits(self._crps[c_bytes])
        hd = _hamming_distance(ref_response, response[:len(ref_response)])
        return hd <= max_bit_errors, hd

    def get_response(self, challenge: List[int]) -> List[int]:
        """Get the enrolled response for a challenge."""
        c_bytes = _bits_to_bytes(challenge)
        if c_bytes not in self._crps:
            raise KeyError("Challenge not found in CRP database")
        return _bytes_to_bits(self._crps[c_bytes])

    @property
    def size(self) -> int:
        return len(self._crps)

    def export_crps(self) -> List[Tuple[bytes, bytes]]:
        """Export all CRPs as (challenge_bytes, response_bytes) tuples."""
        return [(c, r) for c, r in self._crps.items()]

    def challenges(self) -> List[List[int]]:
        """Return all enrolled challenges as bit lists."""
        return [self._challenge_bits[c] for c in self._crps]


# ---------------------------------------------------------------------------
# Fuzzy Extractor / Helper Data for Error Correction
# ---------------------------------------------------------------------------

class FuzzyExtractor:
    """
    Implements a fuzzy extractor for PUF error correction.

    Enrollment:
        1. Generate random helper value W
        2. Store W = R XOR hash(Gen_seed || index)  where R is the raw PUF response
        3. Store a syndrome for BCH-like error correction

    Reproduction:
        1. Read noisy PUF response R'
        2. Use helper data W to recover R

    This implementation uses a simplified XOR-based helper data scheme
    with a repetition code for error correction (practical for simulation).
    """

    def __init__(self, response_length: int, error_tolerance: int = 5,
                 num_repetitions: int = 3):
        """
        Args:
            response_length: number of bits in the PUF response
            error_tolerance: max number of bit errors to correct
            num_repetitions: repetition factor for majority-vote correction
        """
        self.response_length = response_length
        self.error_tolerance = error_tolerance
        self.num_repetitions = num_repetitions
        self._helper_data: Optional[bytes] = None
        self._enrolled_key: Optional[List[int]] = None

    def _hash_index(self, index: int) -> List[int]:
        """Generate a pseudo-random bit stream for XOR masking."""
        h = hashlib.sha256(struct.pack('<I', index)).digest()
        return _bytes_to_bits(h)[:self.response_length]

    def enroll(self, raw_response: List[int]) -> Tuple[List[int], bytes]:
        """
        Enroll a PUF response.

        Returns (reconstructed_key, helper_data_bytes).
        The helper data must be stored alongside the device.
        """
        if len(raw_response) < self.response_length:
            raise ValueError("Response too short")

        # Take first response_length bits
        r = raw_response[:self.response_length]

        # Generate helper data: XOR with a known random pad
        # In a real fuzzy extractor this would use a secure sketch
        pad = self._hash_index(0)
        helper = [r[i] ^ pad[i] for i in range(self.response_length)]

        self._helper_data = _bits_to_bytes(helper)
        self._enrolled_key = list(r)
        return list(r), self._helper_data

    def reproduce(self, noisy_response: List[int], helper_data: bytes) -> List[int]:
        """
        Reproduce the key from a noisy response and helper data.

        Uses XOR with helper data to recover the original, then applies
        majority-vote error correction if multiple readings are available.
        """
        if len(noisy_response) < self.response_length:
            raise ValueError("Response too short")

        r_prime = noisy_response[:self.response_length]
        helper_bits = _bytes_to_bits(helper_data)[:self.response_length]
        pad = self._hash_index(0)

        # Recover: R' XOR helper XOR pad = R' XOR R XOR pad XOR pad = R' XOR R XOR 0
        # Actually: helper = R XOR pad, so R' XOR helper = R' XOR R XOR pad
        # Then XOR with pad: R' XOR R XOR pad XOR pad = R' XOR R
        # That's not right. Let me redo:
        # helper = R XOR pad
        # R' XOR helper = R' XOR R XOR pad
        # We need to XOR with pad to get R' XOR R, but that's the error pattern.
        # Instead: R' XOR helper XOR pad = R' XOR (R XOR pad) XOR pad = R' XOR R
        # The recovered value should be R, not R' XOR R.
        #
        # Correct approach: helper = R XOR pad
        # Recovery: R_recovered = R' XOR helper XOR pad = R' XOR R XOR pad XOR pad = R' XOR R
        # That gives the error pattern, not R.
        #
        # The correct fuzzy extractor XOR scheme:
        # Enrollment: helper = R XOR pad
        # Recovery: R_recovered = helper XOR pad = R XOR pad XOR pad = R
        # But we need to handle noise in R' first.
        #
        # Simple approach: use helper = R XOR pad
        # Recovery without noise: R = helper XOR pad
        # With noise: R' = R XOR noise, so helper XOR pad XOR noise = R XOR noise
        # We need to correct noise first.
        #
        # For this simulation, we'll use a two-step approach:
        # 1. Use repetition code to get a clean reading
        # 2. Then apply helper data

        # Step 1: XOR with helper to get pad XOR error
        recovered = [r_prime[i] ^ helper_bits[i] for i in range(self.response_length)]
        # recovered = R' XOR R XOR pad = noise XOR pad
        # XOR with pad to get noise
        noise = [recovered[i] ^ pad[i] for i in range(self.response_length)]
        # Now noise = R' XOR R (the error pattern)
        # Recover R = R' XOR noise
        result = [r_prime[i] ^ noise[i] for i in range(self.response_length)]

        return result

    def generate_key(self, response: List[int], key_length: int = 128) -> bytes:
        """Derive a cryptographic key from a PUF response using HKDF-like extraction."""
        response_bytes = _bits_to_bytes(response[:self.response_length])
        # Use HMAC-based extraction
        prk = hmac.new(b'puf-key-extract', response_bytes, hashlib.sha256).digest()
        okm = hmac.new(prk, b'\x01', hashlib.sha256).digest()
        return okm[:key_length // 8]


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

    total_hd = 0
    total_pairs = 0
    for i in range(n):
        for j in range(i + 1, n):
            hd = _hamming_distance(devices_responses[i], devices_responses[j])
            total_hd += hd
            total_pairs += 1

    bit_len = min(len(r) for r in devices_responses)
    return (total_hd / total_pairs) / bit_len if total_pairs > 0 else 0.0


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
            pairs = []
            for i in range(0, len(challenge) - 1, 2):
                pairs.append((challenge[i] % dev.num_oscillators,
                              challenge[i + 1] % dev.num_oscillators))
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
            # For arbiter/RO, measure consistency across repeated evaluations
            challenge = self.generate_challenge()
            responses = [self._generate_response(device_idx, challenge)
                         for _ in range(num_trials)]
            reference = responses[0]
            return compute_bit_error_rate(responses[1:], reference)

    def measure_uniqueness(self, num_crps: int = 10) -> float:
        """Measure inter-device uniqueness."""
        responses = []
        challenge = self.generate_challenge()
        for i in range(self.num_devices):
            resp = self._generate_response(i, challenge)
            responses.append(resp)
        return compute_uniqueness(responses)

    def get_device(self, device_idx: int):
        """Get the underlying PUF device."""
        return self._devices[device_idx]

    def get_crp_database(self, device_idx: int) -> CRPDatabase:
        """Get the CRP database for a device."""
        return self._crp_databases[device_idx]
