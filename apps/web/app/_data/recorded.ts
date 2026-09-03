export interface PredicateTrace {
  readonly field: string;
  readonly operator: string;
  readonly expected: string;
  readonly observed: string;
  readonly passed: boolean;
}

export interface PacketDiff {
  readonly frame: number;
  readonly source: string;
  readonly destination: string;
  readonly summary: string;
  readonly bucket: 'missing' | 'extra';
  readonly failedPredicate: string;
  readonly capture: string;
  readonly traces: readonly PredicateTrace[];
}

export interface ProbeResult {
  readonly capture: string;
  readonly correct: number;
  readonly missing: number;
  readonly extra: number;
  readonly runtimeMs: number;
}

export const recordedEvaluation = {
  id: 'ev-recorded-dns',
  intent:
    'Show DNS queries from the internal subnet for A or AAAA records, excluding responses.',
  filter:
    'ip.src == 10.0.0.0/8 && udp && dns.flags.response == 0 && dns.qry.type in {1, 28}',
  ir: [
    'ALL',
    'ip.src in_subnet 10.0.0.0/8',
    'udp exists',
    'dns.flags.response eq false',
    'dns.qry.type in [1, 28]',
  ],
  probes: [
    {
      capture: 'positive-and-distractor',
      correct: 18,
      missing: 0,
      extra: 0,
      runtimeMs: 182,
    },
    {
      capture: 'direction-counterexample',
      correct: 7,
      missing: 2,
      extra: 0,
      runtimeMs: 171,
    },
    {
      capture: 'ipv6-boundary',
      correct: 6,
      missing: 0,
      extra: 1,
      runtimeMs: 190,
    },
  ] satisfies readonly ProbeResult[],
  packets: [
    {
      frame: 42,
      source: '10.1.2.3',
      destination: '8.8.8.8',
      summary: 'DNS query AAAA',
      bucket: 'missing',
      failedPredicate: 'ip.src',
      capture: 'direction-counterexample',
      traces: [
        {
          field: 'ip.src',
          operator: 'in_subnet',
          expected: '10.0.0.0/8',
          observed: '8.8.8.8',
          passed: false,
        },
        {
          field: 'udp',
          operator: 'exists',
          expected: 'present',
          observed: 'present',
          passed: true,
        },
        {
          field: 'dns.flags.response',
          operator: 'eq',
          expected: 'false',
          observed: 'false',
          passed: true,
        },
      ],
    },
    {
      frame: 87,
      source: '10.2.0.9',
      destination: '1.1.1.1',
      summary: 'DNS query A',
      bucket: 'missing',
      failedPredicate: 'dns.qry.type',
      capture: 'direction-counterexample',
      traces: [
        {
          field: 'dns.qry.type',
          operator: 'in',
          expected: '[1, 28]',
          observed: '15',
          passed: false,
        },
      ],
    },
    {
      frame: 113,
      source: 'fd00::4',
      destination: '2001:db8::1',
      summary: 'DNS response AAAA',
      bucket: 'extra',
      failedPredicate: 'dns.flags.response',
      capture: 'ipv6-boundary',
      traces: [
        {
          field: 'dns.flags.response',
          operator: 'eq',
          expected: 'false',
          observed: 'true',
          passed: false,
        },
      ],
    },
  ] satisfies readonly PacketDiff[],
} as const;

export const benchmarkRows = [
  {pipeline: 'Prompt only', exact: '41/80', f1: 0.742, invalid: 11, p95: 820},
  {pipeline: 'Field retrieval', exact: '49/80', f1: 0.801, invalid: 5, p95: 910},
  {pipeline: 'Typed IR', exact: '61/80', f1: 0.884, invalid: 1, p95: 1040},
  {pipeline: 'SFT + typed IR', exact: '67/80', f1: 0.921, invalid: 0, p95: 760},
] as const;
