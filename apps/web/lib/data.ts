/**
 * @fileoverview Reads the exported site data while the static export builds.
 *
 * scripts/export_web_data.py writes apps/web/data/ from committed files, and
 * the Docker build copies it in before next build. Pages read it here, on
 * the server only: no client code fetches data, so every value is in the
 * static HTML. Each document is checked against its schema id and a closed
 * key set at every level, so a renamed, missing or extra field fails the
 * build instead of dropping a value or showing one no page expects.
 */

import 'server-only';

import {readFileSync} from 'node:fs';
import path from 'node:path';

/**
 * A source op naming committed bytes and the reading that yields a value;
 * scripts/export_web_data.py lists the seven ops.
 */
export type Src = readonly [string, ...unknown[]];

/** A sourced string; cap marks model text cut to that many UTF-8 bytes. */
export interface StrNode {
  readonly t: string;
  readonly src: Src;
  readonly cap?: number;
}

/** A sourced number, boolean or list of integers. */
export interface NumNode {
  readonly v: number | boolean | readonly number[];
  readonly src: Src;
}

/** Checks a parsed value and returns it typed, or throws naming the place. */
type Guard<T> = (value: unknown, where: string) => T;
type Guarded<G> = G extends Guard<infer T> ? T : never;

const DATA_DIR = path.join(process.cwd(), 'data');

// The exporter's arity per op, counting the op name.
const OP_ARITY: ReadonlyMap<string, number> = new Map([
  ['count', 4],
  ['input', 4],
  ['len', 3],
  ['ptr', 3],
  ['row', 4],
  ['sha256', 2],
  ['sum', 2],
]);

// The exporter's allowed roots; a permalink is built from these paths.
const INPUT_PATH = new RegExp(
  '^(?:docs/(?:results|decisions/evidence|ablations/evidence)/[A-Za-z0-9._/-]+' +
    '|src/dfilterforge/held_out_freeze[.]json)$',
);
const COMMIT = /^[0-9A-Za-z][0-9A-Za-z._-]{0,63}$/;

class DataError extends Error {}

function fail(where: string, problem: string): never {
  throw new DataError(`apps/web/data: ${where} ${problem}`);
}

function isRecord(value: unknown): value is Readonly<Record<string, unknown>> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

const text: Guard<string> = (value, where) =>
  typeof value === 'string' ? value : fail(where, 'is not a string');

const flag: Guard<boolean> = (value, where) =>
  typeof value === 'boolean' ? value : fail(where, 'is not a boolean');

function literal<T extends string>(expected: T): Guard<T> {
  return (value, where) =>
    value === expected ? expected : fail(where, `is not ${JSON.stringify(expected)}`);
}

function array<T>(item: Guard<T>): Guard<readonly T[]> {
  return (value, where) =>
    Array.isArray(value)
      ? value.map((each: unknown, index) => item(each, `${where}[${index}]`))
      : fail(where, 'is not an array');
}

/** An object with exactly the shape's keys, each checked by its guard. */
function object<S extends Readonly<Record<string, Guard<unknown>>>>(
  shape: S,
): Guard<{readonly [K in keyof S]: Guarded<S[K]>}> {
  const expected = Object.keys(shape).sort();
  return (value, where) => {
    if (!isRecord(value)) {
      return fail(where, 'is not an object');
    }
    const found = Object.keys(value).sort();
    if (found.join('\n') !== expected.join('\n')) {
      return fail(where, `has keys [${found.join(', ')}], not [${expected.join(', ')}]`);
    }
    const checked: Record<string, unknown> = {};
    for (const [key, guard] of Object.entries(shape)) {
      checked[key] = guard(value[key], `${where}.${key}`);
    }
    return checked as {readonly [K in keyof S]: Guarded<S[K]>};
  };
}

const inputPath: Guard<string> = (value, where) => {
  const file = text(value, where);
  const dotted = file.split('/').some((part) => part === '' || part === '.' || part === '..');
  return INPUT_PATH.test(file) && !dotted ? file : fail(where, 'is not a committed input path');
};

const src: Guard<Src> = (value, where) => {
  if (!Array.isArray(value) || typeof value[0] !== 'string') {
    return fail(where, 'is not a source op');
  }
  if (OP_ARITY.get(value[0]) !== value.length) {
    return fail(where, `is not a ${JSON.stringify(value[0])} op`);
  }
  if (value[0] === 'sum') {
    array(src)(value[1], `${where}[1]`);
  } else {
    inputPath(value[1], `${where}[1]`);
  }
  return value as unknown as Src;
};

const numValue: Guard<NumNode['v']> = (value, where) => {
  if (typeof value === 'boolean' || (typeof value === 'number' && Number.isFinite(value))) {
    return value;
  }
  return array((each, place) =>
    typeof each === 'number' && Number.isSafeInteger(each)
      ? each
      : fail(place, 'is not an integer'),
  )(value, where);
};

// The exporter cuts untrusted model text, a completion's response_text and
// nothing else, at 4 KiB of UTF-8.
const RAW_TEXT_CAP = 4096;
const RESPONSE_TEXT_FILE = /^docs\/results\/[^/]+\/completions\/[^/]+[.]json$/;
const RESPONSE_TEXT_POINTER = /^\/completions\/(?:0|[1-9][0-9]*)\/response_text$/;

function isResponseText(source: Src): boolean {
  const [op, file, pointer] = source;
  return (
    op === 'ptr' &&
    typeof file === 'string' &&
    typeof pointer === 'string' &&
    RESPONSE_TEXT_FILE.test(file) &&
    RESPONSE_TEXT_POINTER.test(pointer)
  );
}

const cap: Guard<number> = (value, where) =>
  value === RAW_TEXT_CAP ? value : fail(where, `is not ${RAW_TEXT_CAP}`);

/** A sourced string; a model answer carries the cap, and nothing else does. */
const strNode: Guard<StrNode> = (value, where) => {
  const node =
    isRecord(value) && 'cap' in value
      ? object({t: text, src, cap})(value, where)
      : object({t: text, src})(value, where);
  const answer = isResponseText(node.src);
  if ('cap' in node && !answer) {
    return fail(where, 'carries a cap, which only a model answer may');
  }
  if (!('cap' in node) && answer) {
    return fail(where, 'is a model answer without its cap');
  }
  return node;
};

const numNode: Guard<NumNode> = object({v: numValue, src});

const commit: Guard<string> = (value, where) => {
  const found = text(value, where);
  return COMMIT.test(found) ? found : fail(where, 'is not a revision');
};

const SITE = object({
  schema: literal('web-site/1.0'),
  source_commit: commit,
  inputs: array(object({path: text, sha256: text})),
  phase: object({dev: flag, test: flag, repair: flag, training: flag, aa: flag}),
  runs: array(object({run_id: text, slug: text, split: text, role: text, pool: flag})),
});

const ENVIRONMENT = object({
  tshark_version: strNode,
  executable_sha256: strNode,
  runner_source_sha256: strNode,
  identity_scope: strNode,
  environment_hash: strNode,
  unmeasured: array(strNode),
});

const MUTANTS = object({executed: numNode, killed: numNode, survived: numNode, waived: numNode});

const METHODOLOGY = object({
  schema: literal('web-methodology/1.0'),
  conditions: array(object({label: strNode, output_contract: strNode, retrieval: strNode})),
  top_k: numNode,
  bootstrap: object({
    cases: numNode,
    non_ready_cases: numNode,
    resamples: numNode,
    seed: numNode,
    min_discordant_cases: numNode,
  }),
  environment: ENVIRONMENT,
  mutants: object({dev: MUTANTS, test: MUTANTS, all: MUTANTS}),
  mutant_categories: array(strNode),
  witnesses: object({count: numNode, names: array(strNode)}),
  probes: array(
    object({
      probe_id: strNode,
      split: strNode,
      role: strNode,
      capture_sha256: strNode,
      frames: numNode,
      benchmark_frames: numNode,
    }),
  ),
  shortcuts: object({
    position_typed_fields: numNode,
    gold_candidates: numNode,
    gold_flagged: numNode,
    answer_candidates: numNode,
    answers_flagged: numNode,
  }),
  not_measured: array(object({key: text, value: strNode})),
  admitted_prepares: array(strNode),
});

/** site.json: the build's source commit, inputs, phases and run slugs. */
export type Site = Guarded<typeof SITE>;

/** methodology.json: conditions, bootstrap, environment, gates. */
export type Methodology = Guarded<typeof METHODOLOGY>;

const loaded = new Map<string, unknown>();

function load<T>(name: string, guard: Guard<T>): T {
  if (loaded.has(name)) {
    return loaded.get(name) as T;
  }
  let bytes: Buffer;
  try {
    bytes = readFileSync(path.join(DATA_DIR, name));
  } catch (error) {
    throw new DataError(
      `apps/web/data/${name} cannot be read; export the data first ` +
        '(apps/web/Dockerfile, target data)',
      {cause: error},
    );
  }
  const document: unknown = JSON.parse(
    new TextDecoder('utf-8', {fatal: true, ignoreBOM: true}).decode(bytes),
  );
  const checked = guard(document, name);
  loaded.set(name, checked);
  return checked;
}

/** Returns site.json, checked. */
export function loadSite(): Site {
  return load('site.json', SITE);
}

/** Returns methodology.json, checked. */
export function loadMethodology(): Methodology {
  return load('methodology.json', METHODOLOGY);
}

/** Lists the committed files a source reads, in order, with repeats. */
export function sourcePaths(source: Src): string[] {
  if (source[0] === 'sum') {
    return (source[1] as readonly Src[]).flatMap(sourcePaths);
  }
  return [source[1] as string];
}
