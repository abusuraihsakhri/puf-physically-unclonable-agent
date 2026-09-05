"""
CLI for PUF (Physically Unclonable Function) Simulator.

Provides commands for:
- Creating and simulating SRAM, Arbiter, and Ring Oscillator PUFs
- Generating and verifying Challenge-Response Pairs
- Measuring reliability (bit error rate) and uniqueness
- Fuzzy extractor enrollment and reproduction
"""
import argparse
import json
import secrets
import sys

from simulator import (
    SRAMPUF, ArbiterPUF, RingOscillatorPUF,
    CRPDatabase, FuzzyExtractor, PUFSimulator,
    compute_uniqueness, compute_bit_error_rate,
    _bits_to_bytes, _bytes_to_bits, _hamming_distance,
)


def cmd_sram(args):
    """Simulate an SRAM PUF power-up."""
    puf = SRAMPUF(num_cells=args.bits, noise_rate=args.noise)
    bits = puf.power_up()
    hex_str = _bits_to_bytes(bits).hex()
    print(f"SRAM PUF Power-Up ({args.bits} cells, noise={args.noise}):")
    print(f"  Bits: {''.join(str(b) for b in bits[:64])}...")
    print(f"  Hex:  {hex_str[:32]}...")
    if args.reliability:
        ref, ber = puf.measure_reliability(num_trials=args.trials)
        print(f"  Reliability ({args.trials} trials): BER = {ber:.6f} ({ber*100:.4f}%)")
    return 0


def cmd_arbiter(args):
    """Simulate an Arbiter PUF evaluation."""
    puf = ArbiterPUF(num_stages=args.stages, noise_sigma=args.noise)
    if args.challenge:
        challenge = [1 if c == '1' else 0 for c in args.challenge]
    else:
        challenge = [secrets.randbelow(2) for _ in range(args.stages)]
    # Ensure correct length
    if len(challenge) < args.stages:
        challenge.extend([0] * (args.stages - len(challenge)))
    challenge = challenge[:args.stages]
    response = puf.evaluate(challenge)
    print(f"Arbiter PUF ({args.stages} stages):")
    print(f"  Challenge: {''.join(str(b) for b in challenge[:32])}...")
    print(f"  Response:  {response}")
    return 0


def cmd_ro(args):
    """Simulate a Ring Oscillator PUF comparison."""
    puf = RingOscillatorPUF(num_oscillators=args.oscillators, noise_rate=args.noise)
    idx_a, idx_b = args.pair[0], args.pair[1]
    result = puf.compare(idx_a, idx_b)
    fa = puf._frequencies[idx_a]
    fb = puf._frequencies[idx_b]
    print(f"Ring Oscillator PUF ({args.oscillators} oscillators):")
    print(f"  Osc[{idx_a}] freq: {fa:.3f} MHz")
    print(f"  Osc[{idx_b}] freq: {fb:.3f} MHz")
    print(f"  Response (A faster?): {result}")
    return 0


def cmd_crp(args):
    """Generate and display Challenge-Response Pairs."""
    if args.puf_type == 'sram':
        puf = SRAMPUF(num_cells=args.bits, noise_rate=args.noise)
    elif args.puf_type == 'arbiter':
        puf = ArbiterPUF(num_stages=args.bits, noise_sigma=args.noise)
    else:
        puf = RingOscillatorPUF(num_oscillators=args.bits, noise_rate=args.noise)

    db = CRPDatabase()
    for i in range(args.count):
        if args.puf_type == 'sram':
            challenge = [secrets.randbelow(2) for _ in range(args.bits)]
            response = puf.power_up()
        elif args.puf_type == 'arbiter':
            challenge = [secrets.randbelow(2) for _ in range(args.bits)]
            response = [puf.evaluate(challenge)]
        else:
            challenge = [secrets.randbelow(2) for _ in range(args.bits)]
            pairs = [(challenge[j] % puf.num_oscillators,
                       challenge[j+1] % puf.num_oscillators)
                      for j in range(0, len(challenge)-1, 2)]
            response = puf.evaluate_challenge(pairs)
        db.enroll(challenge, response)

    print(f"Generated {args.count} CRPs for {args.puf_type} PUF:")
    for c_bytes, r_bytes in db.export_crps()[:5]:
        print(f"  C: {c_bytes.hex()[:16]}... -> R: {r_bytes.hex()[:16]}...")
    if args.count > 5:
        print(f"  ... ({args.count - 5} more)")
    return 0


def cmd_uniqueness(args):
    """Measure inter-device uniqueness."""
    responses = []
    for i in range(args.devices):
        if args.puf_type == 'sram':
            puf = SRAMPUF(num_cells=args.bits, noise_rate=0.0)
        elif args.puf_type == 'arbiter':
            puf = ArbiterPUF(num_stages=args.bits, noise_sigma=0.0)
        else:
            puf = RingOscillatorPUF(num_oscillators=args.bits, noise_rate=0.0)

        if args.puf_type == 'sram':
            resp = puf.power_up()
        elif args.puf_type == 'arbiter':
            challenge = [secrets.randbelow(2) for _ in range(args.bits)]
            resp = [puf.evaluate(challenge)]
        else:
            challenge = [secrets.randbelow(2) for _ in range(args.bits)]
            pairs = [(challenge[j] % puf.num_oscillators,
                       challenge[j+1] % puf.num_oscillators)
                      for j in range(0, len(challenge)-1, 2)]
            resp = puf.evaluate_challenge(pairs)
        responses.append(resp)

    uniqueness = compute_uniqueness(responses)
    print(f"Uniqueness ({args.devices} devices, {args.puf_type}, {args.bits} bits):")
    print(f"  Average inter-device Hamming distance: {uniqueness:.4f} ({uniqueness*100:.2f}%)")
    print(f"  Target: ~50% | {'GOOD' if 0.35 <= uniqueness <= 0.65 else 'SUBOPTIMAL'}")
    return 0


def cmd_fuzzy(args):
    """Demonstrate fuzzy extractor enrollment and reproduction."""
    puf = SRAMPUF(num_cells=args.bits, noise_rate=args.noise)
    raw = puf.power_up()
    fe = FuzzyExtractor(response_length=args.bits, error_tolerance=args.tolerance)
    key, helper = fe.enroll(raw)
    print(f"Fuzzy Extractor ({args.bits} bits, tolerance={args.tolerance}):")
    print(f"  Enrolled key:  {_bits_to_bytes(key).hex()[:32]}...")
    print(f"  Helper data:   {helper.hex()[:32]}...")

    # Reproduce with a noisy reading
    noisy = puf.power_up()
    recovered = fe.reproduce(noisy, helper)
    hd = _hamming_distance(key, recovered)
    match = hd == 0
    print(f"  Recovered key: {_bits_to_bytes(recovered).hex()[:32]}...")
    print(f"  Bit errors:    {hd}/{args.bits}")
    print(f"  Match:         {'YES' if match else 'NO'}")
    return 0


def cmd_simulate(args):
    """Run a full PUF simulation with multiple devices."""
    sim = PUFSimulator(
        puf_type=args.puf_type,
        num_devices=args.devices,
        response_bits=args.bits,
        noise_rate=args.noise,
    )
    print(f"PUF Simulation: {args.puf_type}, {args.devices} devices, {args.bits} bits")
    print()

    # Enroll
    for i in range(args.devices):
        db = sim.enroll_device(i, num_crps=args.crps)
        print(f"  Device {i}: enrolled {db.size} CRPs")

    # Reliability
    print()
    for i in range(args.devices):
        ber = sim.measure_reliability(i, num_trials=args.trials)
        print(f"  Device {i} reliability: BER = {ber:.6f} ({ber*100:.4f}%)")

    # Uniqueness
    print()
    uniqueness = sim.measure_uniqueness()
    print(f"  Uniqueness: {uniqueness:.4f} ({uniqueness*100:.2f}%)")

    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog='puf-simulator',
        description='PUF (Physically Unclonable Function) Simulator'
    )
    sub = parser.add_subparsers(dest='command', required=True)

    # SRAM PUF
    p = sub.add_parser('sram', help='Simulate SRAM PUF power-up')
    p.add_argument('--bits', type=int, default=256, help='Number of SRAM cells')
    p.add_argument('--noise', type=float, default=0.02, help='Noise rate [0-0.5]')
    p.add_argument('--reliability', action='store_true', help='Measure reliability')
    p.add_argument('--trials', type=int, default=50, help='Reliability trials')
    p.set_defaults(func=cmd_sram)

    # Arbiter PUF
    p = sub.add_parser('arbiter', help='Simulate Arbiter PUF')
    p.add_argument('--stages', type=int, default=64, help='Number of stages')
    p.add_argument('--noise', type=float, default=0.0, help='Noise sigma')
    p.add_argument('--challenge', type=str, default=None, help='Challenge bit string')
    p.set_defaults(func=cmd_arbiter)

    # Ring Oscillator PUF
    p = sub.add_parser('ro', help='Simulate Ring Oscillator PUF')
    p.add_argument('--oscillators', type=int, default=128, help='Number of oscillators')
    p.add_argument('--noise', type=float, default=0.01, help='Noise rate')
    p.add_argument('--pair', type=int, nargs=2, default=[0, 1], help='Oscillator pair indices')
    p.set_defaults(func=cmd_ro)

    # CRP generation
    p = sub.add_parser('crp', help='Generate Challenge-Response Pairs')
    p.add_argument('--puf-type', choices=['sram', 'arbiter', 'ring_oscillator'], default='sram')
    p.add_argument('--bits', type=int, default=128, help='Challenge/response bits')
    p.add_argument('--noise', type=float, default=0.02, help='Noise rate')
    p.add_argument('--count', type=int, default=10, help='Number of CRPs')
    p.set_defaults(func=cmd_crp)

    # Uniqueness
    p = sub.add_parser('uniqueness', help='Measure inter-device uniqueness')
    p.add_argument('--puf-type', choices=['sram', 'arbiter', 'ring_oscillator'], default='sram')
    p.add_argument('--devices', type=int, default=5, help='Number of devices')
    p.add_argument('--bits', type=int, default=256, help='Response bits')
    p.set_defaults(func=cmd_uniqueness)

    # Fuzzy extractor
    p = sub.add_parser('fuzzy', help='Fuzzy extractor demo')
    p.add_argument('--bits', type=int, default=128, help='Response length')
    p.add_argument('--noise', type=float, default=0.02, help='Noise rate')
    p.add_argument('--tolerance', type=int, default=5, help='Error tolerance')
    p.set_defaults(func=cmd_fuzzy)

    # Full simulation
    p = sub.add_parser('simulate', help='Full PUF simulation')
    p.add_argument('--puf-type', choices=['sram', 'arbiter', 'ring_oscillator'], default='sram')
    p.add_argument('--devices', type=int, default=3, help='Number of devices')
    p.add_argument('--bits', type=int, default=128, help='Response bits')
    p.add_argument('--noise', type=float, default=0.02, help='Noise rate')
    p.add_argument('--crps', type=int, default=5, help='CRPs per device')
    p.add_argument('--trials', type=int, default=30, help='Reliability trials')
    p.set_defaults(func=cmd_simulate)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == '__main__':
    sys.exit(main())
