/**
 * @fileoverview An independent resolver for the exporter's source ops.
 *
 * tests/consistency.spec.ts re-derives every rendered value from the
 * committed files with this module, never from apps/web/data. It shares no
 * code with scripts/export_web_data.py: the seven ops are written again here
 * from their definitions, over the same allowed roots, so a defect in either
 * implementation shows up as a mismatch instead of agreeing with itself.
 *
 * Ops (paths are relative to the repository root):
 * - ['ptr', path, pointer]: an RFC 6901 pointer into a JSON file.
 * - ['row', path, {key: text}, pointer]: the one JSONL row whose keys all
 *   equal the given strings, then a pointer into it.
 * - ['count', path, pointer | null, {key: [text]}]: the JSONL rows (pointer
 *   null) or the array items at the pointer whose every key holds one of
 *   the listed strings.
 * - ['len', path, pointer]: the length of the array at the pointer.
 * - ['sum', [op]]: the sum of integer operands.
 * - ['sha256', path]: the SHA-256 of the file's bytes, in hex.
 * - ['input', path, item_id, pointer]: the INPUT_JSON object of a prepared
 *   prompt's user message, then a pointer into it.
 */

import {createHash} from 'node:crypto';
import {lstatSync, readdirSync, readFileSync, realpathSync} from 'node:fs';
import path from 'node:path';

/** The repository root: apps/web/tests/support is four levels down. */
export const REPOSITORY_ROOT = path.resolve(__dirname, '..', '..', '..', '..');

const ROOTS = ['docs/results/', 'docs/decisions/evidence/', 'docs/ablations/evidence/'];
const FREEZE = 'src/dfilterforge/held_out_freeze.json';
const RANKINGS = 'docs/decisions/evidence/bakeoff';
const TEST_RUNS = 'docs/decisions/evidence/test-runs.json';
const MAX_BYTES = 32 * 1024 * 1024;
const INPUT_PREFIX = 'INPUT_JSON\n';
const INDEX = /^(?:0|[1-9][0-9]*)$/;
const ARITY: ReadonlyMap<string, number> = new Map([
  ['count', 4],
  ['input', 4],
  ['len', 3],
  ['ptr', 3],
  ['row', 4],
  ['sha256', 2],
  ['sum', 2],
]);
const SLOTS = ['small', 'mid', 'frontier'];
const TEST_ROLES = ['pass_a', 'pass_b', ...SLOTS];
const EXECUTED = new Set(['strong_exact', 'shortcut', 'silent_wrong']);

type Json = Readonly<Record<string, unknown>>;

/** One receipt page's route parameters. */
export interface ReceiptRoute {
  readonly run: string;
  readonly cond: string;
  readonly item: string;
}

class ResolveError extends Error {}

function refuse(message: string): never {
  throw new ResolveError(message);
}

function isRecord(value: unknown): value is Json {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function record(value: unknown, where: string): Json {
  return isRecord(value) ? value : refuse(`${where} is not an object`);
}

function list(value: unknown, where: string): readonly unknown[] {
  return Array.isArray(value) ? value : refuse(`${where} is not an array`);
}

function string(value: unknown, where: string): string {
  return typeof value === 'string' ? value : refuse(`${where} is not a string`);
}

/** Refuses a path outside the allowed roots or with an empty or dot segment. */
export function checkPath(file: string): string {
  const dotted = file.split('/').some((part) => part === '' || part === '.' || part === '..');
  if (file === '' || dotted || file.includes('\\') || file.includes(':')) {
    return refuse(`${JSON.stringify(file)} is not a clean path`);
  }
  if (file !== FREEZE && !ROOTS.some((root) => file.startsWith(root))) {
    return refuse(`${JSON.stringify(file)} is outside the allowed roots`);
  }
  return file;
}

/** Resolves an RFC 6901 pointer, refusing any missing step. */
export function pointerGet(document: unknown, pointer: string): unknown {
  if (pointer === '') {
    return document;
  }
  if (!pointer.startsWith('/')) {
    return refuse(`${JSON.stringify(pointer)} is not a pointer`);
  }
  let value = document;
  for (const token of pointer.slice(1).split('/')) {
    const key = token.replaceAll('~1', '/').replaceAll('~0', '~');
    if (Array.isArray(value)) {
      if (!INDEX.test(key) || Number(key) >= value.length) {
        return refuse(`${JSON.stringify(pointer)} is missing`);
      }
      value = value[Number(key)] as unknown;
    } else if (isRecord(value) && Object.hasOwn(value, key)) {
      value = value[key];
    } else {
      return refuse(`${JSON.stringify(pointer)} is missing`);
    }
  }
  return value;
}

/** Cuts text to at most limit UTF-8 bytes without splitting a character. */
export function capUtf8(text: string, limit: number): string {
  const bytes = Buffer.from(text, 'utf8');
  if (bytes.length <= limit) {
    return text;
  }
  let end = limit;
  // A continuation byte at the cut means a character straddles it.
  while (end > 0 && ((bytes[end] ?? 0) & 0xc0) === 0x80) {
    end -= 1;
  }
  return bytes.subarray(0, end).toString('utf8');
}

/** Reads committed files under the allowed roots and evaluates source ops. */
export class Resolver {
  private readonly root: string;
  private readonly realRoot: string;
  private readonly bytes = new Map<string, Buffer>();
  private readonly documents = new Map<string, unknown>();
  private readonly lines = new Map<string, readonly Json[]>();
  private readonly payloads = new Map<string, unknown>();

  constructor(root = REPOSITORY_ROOT) {
    this.root = root;
    this.realRoot = realpathSync(root);
  }

  /** Returns the absolute location of an allowed path. */
  private locate(file: string): string {
    return path.join(this.root, ...checkPath(file).split('/'));
  }

  /** Whether a regular file exists at an allowed path. */
  exists(file: string): boolean {
    try {
      return lstatSync(this.locate(file)).isFile();
    } catch {
      return false;
    }
  }

  /** Reads one regular file's bytes; links and oversized files are refused. */
  data(file: string): Buffer {
    const cached = this.bytes.get(file);
    if (cached !== undefined) {
      return cached;
    }
    const location = this.locate(file);
    const status = lstatSync(location);
    if (!status.isFile()) {
      return refuse(`${file} is not a regular file`);
    }
    if (status.size > MAX_BYTES) {
      return refuse(`${file} exceeds 32 MiB`);
    }
    if (!realpathSync(location).startsWith(this.realRoot + path.sep)) {
      return refuse(`${file} leaves the repository`);
    }
    const read = readFileSync(location);
    this.bytes.set(file, read);
    return read;
  }

  private text(file: string): string {
    return new TextDecoder('utf-8', {fatal: true, ignoreBOM: true}).decode(this.data(file));
  }

  /** Parses one JSON file. */
  json(file: string): unknown {
    if (!this.documents.has(file)) {
      this.documents.set(file, JSON.parse(this.text(file)));
    }
    return this.documents.get(file);
  }

  /** Parses one JSONL file; every non-empty line is an object. */
  rows(file: string): readonly Json[] {
    const cached = this.lines.get(file);
    if (cached !== undefined) {
      return cached;
    }
    const parsed = this.text(file)
      .split('\n')
      .filter((line) => line !== '')
      .map((line) => record(JSON.parse(line), `${file} row`));
    this.lines.set(file, parsed);
    return parsed;
  }

  private payload(file: string, itemId: string): unknown {
    const key = `${file}\n${itemId}`;
    if (!this.payloads.has(key)) {
      const prompts = list(record(this.json(file), file)['prompts'], `${file} prompts`);
      const matches = prompts.filter((prompt) => record(prompt, file)['item_id'] === itemId);
      if (matches.length !== 1) {
        return refuse(`${file}: ${itemId} is not one prompt`);
      }
      const content = string(pointerGet(matches[0], '/messages/1/content'), `${file} content`);
      if (!content.startsWith(INPUT_PREFIX)) {
        return refuse(`${file} ${itemId} has no INPUT_JSON`);
      }
      this.payloads.set(key, JSON.parse(content.slice(INPUT_PREFIX.length)));
    }
    return this.payloads.get(key);
  }

  /**
   * Evaluates one source op against the committed files.
   *
   * @param source A parsed data-src value.
   * @return The value the op names.
   * @throws ResolveError When the op is malformed, a path is refused or a
   *     step is missing.
   */
  resolve(source: unknown): unknown {
    const op = list(source, 'a source');
    const name = op[0];
    if (typeof name !== 'string' || ARITY.get(name) !== op.length) {
      return refuse(`${JSON.stringify(source)} is not a source op`);
    }
    switch (name) {
      case 'ptr':
        return pointerGet(this.json(string(op[1], 'path')), string(op[2], 'pointer'));
      case 'row':
        return this.row(string(op[1], 'path'), record(op[2], 'row keys'), string(op[3], 'pointer'));
      case 'count':
        return this.count(string(op[1], 'path'), op[2], record(op[3], 'count keys'));
      case 'len':
        return list(
          pointerGet(this.json(string(op[1], 'path')), string(op[2], 'pointer')),
          'a len target',
        ).length;
      case 'sum':
        return list(op[1], 'sum operands').reduce<number>((total, operand) => {
          const value = this.resolve(operand);
          return typeof value === 'number' && Number.isInteger(value)
            ? total + value
            : refuse(`${JSON.stringify(operand)} is not an integer`);
        }, 0);
      case 'sha256':
        return createHash('sha256')
          .update(this.data(string(op[1], 'path')))
          .digest('hex');
      default:
        return pointerGet(
          this.payload(string(op[1], 'path'), string(op[2], 'item_id')),
          string(op[3], 'pointer'),
        );
    }
  }

  private row(file: string, keys: Json, pointer: string): unknown {
    const matches = this.rows(file).filter((row) =>
      Object.entries(keys).every(([key, value]) => row[key] === value),
    );
    if (matches.length !== 1) {
      return refuse(`${file}: ${matches.length} rows match ${JSON.stringify(keys)}`);
    }
    return pointerGet(matches[0], pointer);
  }

  private count(file: string, at: unknown, where: Json): number {
    const items =
      at === null
        ? this.rows(file)
        : list(pointerGet(this.json(file), string(at, 'pointer')), `${file} count target`);
    const wanted = Object.entries(where).map(
      ([key, values]) => [key, list(values, 'count values')] as const,
    );
    return items.filter((item) => {
      const found = record(item, `${file} item`);
      return wanted.every(([key, values]) => values.includes(found[key]));
    }).length;
  }

  /**
   * Lists the runs the site shows, from the committed files alone: the
   * latest bake-off ranking's anchor, then its small, mid and frontier
   * candidates by rank, then, once every run that test-runs.json registers
   * is scored or listed as not run, the registered test runs by role.
   */
  shownRuns(): string[] {
    const names = readdirSync(this.locate(RANKINGS))
      .filter((name) => name.startsWith('ranking-') && name.endsWith('.json'))
      .sort();
    const latest = names.at(-1) ?? refuse('no bake-off ranking is committed');
    const ranking = record(this.json(`${RANKINGS}/${latest}`), latest);
    const runs = [string(record(ranking['anchor'], 'anchor')['run_id'], 'anchor run')];
    const slots = record(ranking['slots'], 'slots');
    for (const slot of SLOTS) {
      const candidates = list(record(slots[slot], slot)['candidates'], `${slot} candidates`)
        .map((candidate) => record(candidate, slot))
        .sort((first, second) => Number(first['rank']) - Number(second['rank']));
      runs.push(...candidates.map((candidate) => string(candidate['run_id'], `${slot} run`)));
    }
    if (this.exists(TEST_RUNS)) {
      runs.push(...this.settledTestRuns());
    }
    return runs;
  }

  private settledTestRuns(): string[] {
    const registration = record(this.json(TEST_RUNS), TEST_RUNS);
    const registered = list(registration['runs'], 'runs').map((entry) => record(entry, 'run'));
    const notRun = list(registration['not_run'] ?? [], 'not_run');
    const settled = registered.every((entry) => {
      const runId = string(entry['run_id'], 'run_id');
      return notRun.includes(runId) || this.exists(`docs/results/${runId}/scored/summary.json`);
    });
    if (!settled) {
      return [];
    }
    return TEST_ROLES.flatMap((role) =>
      registered
        .filter((entry) => entry['role'] === role && !notRun.includes(entry['run_id']))
        .map((entry) => string(entry['run_id'], 'run_id')),
    );
  }

  private outcomeRows(runId: string): readonly Json[] {
    return this.rows(`docs/results/${runId}/scored/outcomes.jsonl`);
  }

  /** Every executed answer of the shown runs, as receipt route params. */
  executedRoutes(): ReceiptRoute[] {
    return this.shownRuns().flatMap((runId) =>
      this.outcomeRows(runId)
        .filter((row) => EXECUTED.has(string(row['outcome'], 'outcome')))
        .map((row) => ({
          run: runId.replaceAll('.', '_'),
          cond: string(row['condition'], 'condition'),
          item: string(row['item_id'], 'item_id'),
        })),
    );
  }

  /** Every case of the shown runs, sorted. */
  caseIds(): string[] {
    const cases = new Set(
      this.shownRuns().flatMap((runId) =>
        this.outcomeRows(runId).map((row) => string(row['case_id'], 'case_id')),
      ),
    );
    return [...cases].sort();
  }
}
