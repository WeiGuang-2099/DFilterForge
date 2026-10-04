/**
 * @fileoverview An independent resolver for the exporter's source ops.
 *
 * tests/consistency.spec.ts re-derives every rendered value from the
 * committed files with this module, never from apps/web/data. It shares no
 * code with scripts/export_web_data.py: the seven ops are written again here
 * from their definitions, over the same allowed roots, so a defect in either
 * implementation shows up as a mismatch instead of agreeing with itself. The
 * shown runs, the Disproof Reel's pool and pick, and the run whose summary
 * the methodology page's repair line cites, with the split that labels the
 * line, are written again the same way, from rule reel-v1 in
 * docs/decisions/disproof-reel.md and the test-run registry described in
 * docs/decisions/test-runs.md.
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
// The registry's schema, as scripts/test_passes.py and the exporter read it.
const REGISTRY_SCHEMA = 'test-runs/1.0';
// The note that registers the test runs (test-runs.md, Runs). It is read
// only to check its Runs table against the registry; no source op may name
// it, so it stays outside the allowed roots.
const REGISTRY_NOTE = 'docs/decisions/test-runs.md';
// A row of the note's Runs table: number, role, run id. No other table in
// the note starts with a number and then two backticked cells.
const NOTE_ROW = /^\| ([0-9]+) \| `([a-z_]+)` \| `([^`]+)` \|/;
// scripts/model_run.py's result-name pattern, with ASCII digits only.
const RUN_ID = /^(?:dev|test)-[a-z0-9][a-z0-9.-]{0,31}-[0-9]{4}-[0-9]{2}-[0-9]{2}$/;
// The schema of the bake-off ruling test-runs.json names, which holds each
// slot winner's counted dev pass.
const RULING_SCHEMA = 'bakeoff-ruling/1.0';
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
// The registry's roles in display order (test-runs.md, Runs): the A/A pair,
// then each slot's winner and its fallback. An outage re-run keeps its run's
// role, so a role may repeat.
const TEST_ROLES: readonly string[] = [
  'aa_pass_a',
  'aa_pass_b',
  'winner_small',
  'fallback_small',
  'winner_mid',
  'fallback_mid',
  'winner_frontier',
  'fallback_frontier',
];
// Runs 1 to 5 of test-runs.md, sent whatever happens, in registry order;
// every other row is conditional on the run it names.
const PLANNED_ROLES: readonly string[] = [
  'aa_pass_a',
  'aa_pass_b',
  'winner_small',
  'winner_mid',
  'winner_frontier',
];
// A row's status (test-runs.md, Status).
const STATUSES: readonly string[] = ['registered', 'unused', 'published', 'not_run'];
// What sends a conditional row: a gate stop sends a winner's fallback, an
// outage the run's -r2 re-run.
const TRIGGERS: readonly string[] = ['gate_stop', 'outage'];
// reel-v1 step 2: C4 first, then C3, C2 and C1.
const REEL_CONDITIONS = ['C4', 'C3', 'C2', 'C1'];
const EXECUTED = new Set(['strong_exact', 'shortcut', 'silent_wrong']);

type Json = Readonly<Record<string, unknown>>;

/** One receipt page's route parameters. */
export interface ReceiptRoute {
  readonly run: string;
  readonly cond: string;
  readonly item: string;
}

/** The Reel's pick by reel-v1 steps 2 and 3, and how many it was among. */
export interface ReelPick {
  readonly run: string;
  readonly cond: string;
  readonly item: string;
  readonly candidates: number;
}

/** What test-runs.json registers: its rows and the ruling's slot winners. */
interface Registration {
  readonly rows: readonly TestRun[];
  /** The small, mid and frontier winners' dev passes, from the ruling. */
  readonly winners: readonly string[];
}

/** One row of test-runs.json, with the fields the site depends on. */
interface TestRun {
  /** The row's number, counted from 1 as test-runs.md numbers it. */
  readonly number: number;
  readonly role: string;
  readonly runId: string;
  readonly status: string;
  readonly trigger: string | null;
  readonly conditionalOn: string | null;
  readonly reason: string | null;
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

function optionalString(value: unknown, where: string): string | null {
  return value === undefined || value === null ? null : string(value, where);
}

/** The pool slot a role fills: a winner and its fallback share one. */
function slotOf(role: string): string {
  return role.replace(/^(?:winner|fallback)_/, '');
}

/**
 * Says what breaks a row's condition, as the frozen-prompt guard reads it,
 * or null. A planned row has neither a trigger nor a named run and is never
 * unused. A conditional row has both, its trigger is gate_stop or outage, it
 * names another row, and it leaves unused only once that row is not_run.
 */
function conditionProblem(entry: TestRun, rows: readonly TestRun[]): string | null {
  if (entry.trigger === null && entry.conditionalOn === null) {
    return entry.status === 'unused' ? 'is a planned row marked unused' : null;
  }
  if (entry.trigger === null || entry.conditionalOn === null) {
    return 'has a trigger or a named run without the other';
  }
  if (!TRIGGERS.includes(entry.trigger)) {
    return `has the trigger ${JSON.stringify(entry.trigger)}`;
  }
  const named = rows.find((other) => other !== entry && other.runId === entry.conditionalOn);
  if (named === undefined) {
    return `names ${entry.conditionalOn}, which is no other row`;
  }
  if (entry.status !== 'unused' && named.status !== 'not_run') {
    return `is ${entry.status} while ${named.runId} is ${named.status}`;
  }
  return null;
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

/** The exporter's cut for untrusted model text, in UTF-8 bytes (4 KiB). */
export const RAW_TEXT_CAP = 4096;

const RESPONSE_TEXT_FILE = /^docs\/results\/[^/]+\/completions\/[^/]+\.json$/;
const RESPONSE_TEXT_POINTER = /^\/completions\/(?:0|[1-9][0-9]*)\/response_text$/;

/**
 * Returns the cut a sourced string must carry: RAW_TEXT_CAP for a model
 * answer's response_text, the only text the exporter cuts, and null for
 * every other source, which must be shown whole. The page's own data-cap is
 * never trusted for this.
 */
export function capFor(source: unknown): number | null {
  if (!Array.isArray(source) || source[0] !== 'ptr' || source.length !== 3) {
    return null;
  }
  const [, file, pointer] = source as readonly unknown[];
  return typeof file === 'string' &&
    typeof pointer === 'string' &&
    RESPONSE_TEXT_FILE.test(file) &&
    RESPONSE_TEXT_POINTER.test(pointer)
    ? RAW_TEXT_CAP
    : null;
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

  /**
   * Whether a regular file exists at an allowed path. A path the rules
   * refuse throws, as the exporter's exists does, rather than reading as
   * absent.
   */
  exists(file: string): boolean {
    const location = this.locate(file);
    try {
      return lstatSync(location).isFile();
    } catch {
      return false;
    }
  }

  /**
   * Reads one regular file's bytes. A file reached through a link is
   * refused, even a link to a directory inside the repository, since its
   * bytes would be read under an allowed path they do not live at; so is an
   * oversized file.
   */
  data(file: string): Buffer {
    return this.read(file, this.locate(file));
  }

  /**
   * Reads the registry note, the one file outside the allowed roots the
   * resolver reads, under the same link and size rules. No source op can
   * reach it: resolve() reads through data(), which refuses its path.
   */
  private registryNote(): string {
    const bytes = this.read(REGISTRY_NOTE, path.join(this.root, ...REGISTRY_NOTE.split('/')));
    return new TextDecoder('utf-8', {fatal: true, ignoreBOM: true}).decode(bytes);
  }

  private read(file: string, location: string): Buffer {
    const cached = this.bytes.get(file);
    if (cached !== undefined) {
      return cached;
    }
    const status = lstatSync(location);
    if (!status.isFile()) {
      return refuse(`${file} is not a regular file`);
    }
    if (status.size > MAX_BYTES) {
      return refuse(`${file} exceeds 32 MiB`);
    }
    if (realpathSync(location) !== path.join(this.realRoot, ...file.split('/'))) {
      return refuse(`${file} passes through a link`);
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

  /** The lexicographically last bake-off ranking. */
  private ranking(): Json {
    const names = readdirSync(this.locate(RANKINGS))
      .filter((name) => name.startsWith('ranking-') && name.endsWith('.json'))
      .sort();
    const latest = names.at(-1) ?? refuse('no bake-off ranking is committed');
    return record(this.json(`${RANKINGS}/${latest}`), latest);
  }

  /**
   * The dev runs the latest bake-off ranking shows: its anchor, then its
   * small, mid and frontier candidates by rank.
   */
  private devRuns(): string[] {
    const ranking = this.ranking();
    const runs = [string(record(ranking['anchor'], 'anchor')['run_id'], 'anchor run')];
    const slots = record(ranking['slots'], 'slots');
    for (const slot of SLOTS) {
      const candidates = list(record(slots[slot], slot)['candidates'], `${slot} candidates`)
        .map((candidate) => record(candidate, slot))
        .sort((first, second) => Number(first['rank']) - Number(second['rank']));
      runs.push(...candidates.map((candidate) => string(candidate['run_id'], `${slot} run`)));
    }
    return runs;
  }

  /**
   * Lists the runs the site shows, from the committed files alone: the
   * ranking's dev runs, then, once the test phase is on, the published test
   * runs in role order.
   */
  shownRuns(): string[] {
    return [...this.devRuns(), ...this.settledTestRuns()];
  }

  /**
   * Reads test-runs.json and the ruling it names, or null when no registry
   * is committed. Refuses, as the exporter does, a schema other than
   * test-runs/1.0 or a note other than test-runs.md; a role outside the
   * eight; a run id that is malformed, no test run or repeated; a status
   * outside the four; a not_run row with no reason; a broken condition;
   * planned rows other than runs 1 to 5 of test-runs.md in order; a row
   * that is not published whose run directory holds run_manifest.json or
   * scored/summary.json; two published rows that fill one pool slot; a
   * Runs table in the note that does not list the registry's rows, numbered
   * from 1, in order; and a ruling that rulingWinners refuses, in either
   * phase.
   */
  private registration(): Registration | null {
    if (!this.exists(TEST_RUNS)) {
      return null;
    }
    const registry = record(this.json(TEST_RUNS), TEST_RUNS);
    if (registry['schema'] !== REGISTRY_SCHEMA) {
      return refuse(`${TEST_RUNS} is not ${REGISTRY_SCHEMA}`);
    }
    if (registry['note'] !== REGISTRY_NOTE) {
      return refuse(`${TEST_RUNS} note is not ${REGISTRY_NOTE}`);
    }
    const seen = new Set<string>();
    const rows = list(registry['runs'], `${TEST_RUNS} runs`).map((item, index): TestRun => {
      const where = `${TEST_RUNS} row ${index + 1}`;
      const entry = record(item, where);
      const role = string(entry['role'], `${where} role`);
      const runId = string(entry['run_id'], `${where} run_id`);
      const status = string(entry['status'], `${where} status`);
      const reason = optionalString(entry['reason'], `${where} reason`);
      if (!TEST_ROLES.includes(role)) {
        return refuse(`${where} has the role ${JSON.stringify(role)}`);
      }
      if (!RUN_ID.test(runId)) {
        return refuse(`${where} run_id ${JSON.stringify(runId)} is not a run id`);
      }
      if (!runId.startsWith('test-')) {
        return refuse(`${where} ${runId} is no test run`);
      }
      if (seen.has(runId)) {
        return refuse(`${where} repeats ${runId}`);
      }
      seen.add(runId);
      if (!STATUSES.includes(status)) {
        return refuse(`${where} has the status ${JSON.stringify(status)}`);
      }
      if (status === 'not_run' && !reason) {
        return refuse(`${where} ${runId} is not_run with no reason`);
      }
      return {
        number: index + 1,
        role,
        runId,
        status,
        trigger: optionalString(entry['trigger'], `${where} trigger`),
        conditionalOn: optionalString(entry['conditional_on'], `${where} conditional_on`),
        reason,
      };
    });
    for (const entry of rows) {
      const problem = conditionProblem(entry, rows);
      if (problem !== null) {
        refuse(`${TEST_RUNS} row ${entry.number} ${entry.runId} ${problem}`);
      }
    }
    const planned = rows
      .filter((entry) => entry.trigger === null)
      .map((entry) => entry.role)
      .join(', ');
    if (planned !== PLANNED_ROLES.join(', ')) {
      refuse(`${TEST_RUNS} plans ${planned || 'no run'}, not ${PLANNED_ROLES.join(', ')}`);
    }
    for (const entry of rows.filter((each) => each.status !== 'published')) {
      for (const name of ['run_manifest.json', 'scored/summary.json']) {
        if (this.exists(`docs/results/${entry.runId}/${name}`)) {
          refuse(`docs/results/${entry.runId} holds ${name}, but its row is ${entry.status}`);
        }
      }
    }
    const filled = new Map<string, string>();
    for (const entry of rows.filter((each) => each.status === 'published')) {
      const slot = slotOf(entry.role);
      const other = filled.get(slot);
      if (other !== undefined) {
        refuse(`${TEST_RUNS} publishes ${other} and ${entry.runId} for the ${slot} slot`);
      }
      filled.set(slot, entry.runId);
    }
    this.checkNote(rows);
    return {
      rows,
      winners: this.rulingWinners(string(registry['ruling'], `${TEST_RUNS} ruling`)),
    };
  }

  /**
   * Reads each slot winner's dev pass from the bake-off ruling the registry
   * names: slots.<slot>.winner.run_id; the top-level winners holds model ids
   * and is not read. Refuses, as the exporter does, a ruling outside the
   * allowed roots, a schema other than bakeoff-ruling/1.0, a slot without a
   * winner, and a winner that is not a run id, no dev run or not shown by
   * the ranking.
   */
  private rulingWinners(ruling: string): string[] {
    const document = record(this.json(ruling), ruling);
    if (document['schema'] !== RULING_SCHEMA) {
      return refuse(`${ruling} is not ${RULING_SCHEMA}`);
    }
    const slots = record(document['slots'], `${ruling} slots`);
    const shown = new Set(this.devRuns());
    return SLOTS.map((slot) => {
      const where = `${ruling} ${slot} winner`;
      const winner = record(record(slots[slot], `${ruling} ${slot}`)['winner'], where);
      const runId = string(winner['run_id'], `${where} run_id`);
      if (!RUN_ID.test(runId)) {
        return refuse(`${where} ${JSON.stringify(runId)} is not a run id`);
      }
      if (!runId.startsWith('dev-')) {
        return refuse(`${where} ${runId} is no dev run`);
      }
      if (!shown.has(runId)) {
        return refuse(`${where} ${runId} is not shown`);
      }
      return runId;
    });
  }

  /**
   * Refuses a Runs table in the registry note that is not the registry's
   * rows as (number, role, run id), numbered from 1, in order. A run id
   * named only in the note's prose registers nothing.
   */
  private checkNote(rows: readonly TestRun[]): void {
    const noted = this.registryNote()
      .split('\n')
      .flatMap((line) => {
        const found = NOTE_ROW.exec(line);
        return found === null ? [] : [[found[1], found[2], found[3]].join(' ')];
      });
    const registered = rows.map((entry) => [String(entry.number), entry.role, entry.runId].join(' '));
    const length = Math.max(noted.length, registered.length);
    for (let index = 0; index < length; index += 1) {
      if (noted[index] !== registered[index]) {
        refuse(
          `${REGISTRY_NOTE} Runs row ${index + 1} is ${noted[index] ?? 'no row'}; ` +
            `${TEST_RUNS} has ${registered[index] ?? 'no row'}`,
        );
      }
    }
  }

  /**
   * Whether a row is final, by disproof-reel.md's reading of reel-v1 step 1
   * against the registry. A published row is final once its run has
   * scored/summary.json; until then it waits, which is no error. A not_run
   * row is final, and so is an unused row that gives a reason or whose named
   * run is not not_run, since its condition never occurred. A registered row
   * may still send requests.
   */
  private isFinal(entry: TestRun, rows: readonly TestRun[]): boolean {
    switch (entry.status) {
      case 'published':
        return this.exists(`docs/results/${entry.runId}/scored/summary.json`);
      case 'not_run':
        return true;
      case 'unused':
        return (
          Boolean(entry.reason) ||
          rows.find((other) => other.runId === entry.conditionalOn)?.status !== 'not_run'
        );
      default:
        return false;
    }
  }

  /**
   * The published registry rows in role order, then registry order, once
   * the test phase is on: no row is registered, every published row's run
   * is scored, and every other row is not_run or a final unused row. Null
   * before that, or with no registry.
   */
  private settled(): readonly TestRun[] | null {
    const rows = this.registration()?.rows;
    if (rows === undefined || !rows.every((entry) => this.isFinal(entry, rows))) {
      return null;
    }
    return TEST_ROLES.flatMap((role) =>
      rows.filter((entry) => entry.role === role && entry.status === 'published'),
    );
  }

  /**
   * Lists the test runs the site shows: none until the test phase is on,
   * then the published runs in role order, pass B and outage re-runs
   * included. Throws on a registry the exporter refuses.
   */
  private settledTestRuns(): string[] {
    return (this.settled() ?? []).map((entry) => entry.runId);
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

  /**
   * Lists the Disproof Reel's pool by reel-v1 step 1, read against the
   * registry as disproof-reel.md reads it. In the test phase: the published
   * aa_pass_a run, then per slot the published winner_<slot> run, else the
   * published fallback_<slot> run, an outage re-run included and a slot with
   * neither skipped, so the pool may be empty. Otherwise: the ranking's
   * anchor, then each slot winner's dev pass, slots.<slot>.winner.run_id of
   * the ruling test-runs.json names or, with no registry, the ranking's
   * provisional_winner, a slot without one skipped. Pass B is never pooled.
   * Throws, as the exporter stops, once scored repair results exist for the
   * pool (refuseUnreadRepair).
   */
  reelPool(): string[] {
    const settled = this.settled();
    const pool = settled === null ? this.devPool() : this.testPool(settled);
    this.refuseUnreadRepair(pool, settled === null ? 'dev' : 'test');
    return pool;
  }

  private testPool(settled: readonly TestRun[]): string[] {
    const published = (role: string): string | undefined =>
      settled.find((entry) => entry.role === role)?.runId;
    return [
      published('aa_pass_a'),
      ...SLOTS.map((slot) => published(`winner_${slot}`) ?? published(`fallback_${slot}`)),
    ].filter((runId): runId is string => runId !== undefined);
  }

  private devPool(): string[] {
    const ranking = this.ranking();
    const pool = [string(record(ranking['anchor'], 'anchor')['run_id'], 'anchor run')];
    const registration = this.registration();
    if (registration !== null) {
      return [...pool, ...registration.winners];
    }
    const slots = record(ranking['slots'], 'slots');
    for (const slot of SLOTS) {
      const winner = optionalString(record(slots[slot], slot)['provisional_winner'], slot);
      if (winner !== null) {
        pool.push(winner);
      }
    }
    return pool;
  }

  /**
   * Refuses scored repair results while reel-v1 step 5 is not built: once
   * repair runs are scored, the Reel shows the pick's counterexample-arm
   * turn, which neither the exporter nor this resolver reads yet. Throws
   * when the pool split's docs/results/repair-pool/<split>.json exists, or
   * for a pool run its repair/summary.json, or the scored summary of its
   * -cx arm run or that arm's -r2 re-run, named as repair-round.md names
   * them: the tag before the date, -r2 after the tag.
   */
  private refuseUnreadRepair(pool: readonly string[], split: string): void {
    const files = [`docs/results/repair-pool/${split}.json`];
    for (const runId of pool) {
      const parts = runId.split('-');
      const stem = parts.slice(0, -3).join('-');
      const date = parts.slice(-3).join('-');
      files.push(
        `docs/results/${runId}/repair/summary.json`,
        `docs/results/${stem}-cx-${date}/scored/summary.json`,
        `docs/results/${stem}-cx-r2-${date}/scored/summary.json`,
      );
    }
    for (const file of files) {
      if (this.exists(file)) {
        refuse(`${file} holds scored repair results, which reel-v1 step 5 would show`);
      }
    }
  }

  /**
   * Names the scored summary whose not_measured statuses the methodology
   * page shows. Its repair line describes the repair round the site
   * reports: in the test phase the test round, so the first test pool run's
   * summary, pass A's whenever pass A is published, and none with an empty
   * pool; otherwise the dev round, so the dev anchor's. Throws, as the
   * exporter stops, when that run's repair/summary.json exists: the scorer
   * keeps not_measured.repair_at_1 at not_run after a round, so the page
   * would call a measured round not measured yet.
   */
  repairStatusSummary(): string | null {
    const runId = this.repairStatusRun();
    return runId === null ? null : `docs/results/${runId}/scored/summary.json`;
  }

  /**
   * Names the split that labels the methodology page's repair line, "test"
   * for "Test repair round" or "dev" for "Dev repair round": the split the
   * summary repairStatusSummary() names records, and null with no summary.
   * Once rounds of both splits are committed, a line without it would read
   * as if no round had been measured. Throws, as the exporter stops
   * (split_mismatch), when the summary records another split than its run
   * id names.
   */
  repairStatusSplit(): string | null {
    const runId = this.repairStatusRun();
    if (runId === null) {
      return null;
    }
    const summary = `docs/results/${runId}/scored/summary.json`;
    const split = string(record(this.json(summary), summary)['split'], `${summary} split`);
    if (runId.split('-')[0] !== split) {
      refuse(`${summary} records the split ${JSON.stringify(split)}, not the one ${runId} names`);
    }
    return split;
  }

  /** The run repairStatusSummary() cites; throws once its round is scored. */
  private repairStatusRun(): string | null {
    const settled = this.settled();
    const runId =
      settled === null
        ? string(record(this.ranking()['anchor'], 'anchor')['run_id'], 'anchor run')
        : this.testPool(settled).at(0);
    if (runId === undefined) {
      return null;
    }
    const repair = `docs/results/${runId}/repair/summary.json`;
    if (this.exists(repair)) {
      refuse(`${repair} holds a scored repair round, which the methodology would call unmeasured`);
    }
    return runId;
  }

  /**
   * Picks the Reel's answer by reel-v1 steps 2 and 3, from the pool runs'
   * outcome rows and receipts alone. The candidates are the ready-gold
   * answers with outcome silent_wrong in C4, else C3, then C2, then C1. The
   * pick has the fewest frames in candidate_only plus reference_only summed
   * over its receipt's probes; ties go to the earlier pool run, then to the
   * lower item id. Null when no pool answer is silent-wrong.
   */
  reelPick(): ReelPick | null {
    const pool = this.reelPool();
    for (const cond of REEL_CONDITIONS) {
      const candidates = pool.flatMap((run, position) =>
        this.outcomeRows(run)
          .filter(
            (row) =>
              row['condition'] === cond &&
              row['gold_status'] === 'ready' &&
              row['outcome'] === 'silent_wrong',
          )
          .map((row) => {
            const item = string(row['item_id'], 'item_id');
            const receipt = `docs/results/${run}/scored/receipts/${cond}/${item}.json`;
            return {run, item, position, frames: this.disagreeing(receipt)};
          }),
      );
      const [pick] = candidates.sort(
        (first, second) =>
          first.frames - second.frames ||
          first.position - second.position ||
          (first.item < second.item ? -1 : first.item > second.item ? 1 : 0),
      );
      if (pick !== undefined) {
        return {run: pick.run, cond, item: pick.item, candidates: candidates.length};
      }
    }
    return null;
  }

  /** The frames in candidate_only plus reference_only over a receipt's probes. */
  private disagreeing(receipt: string): number {
    const probes = list(record(this.json(receipt), receipt)['probes'], `${receipt} probes`);
    return probes.reduce<number>((total, probe) => {
      const sides = record(probe, `${receipt} probe`);
      return (
        total +
        list(sides['candidate_only'], `${receipt} candidate_only`).length +
        list(sides['reference_only'], `${receipt} reference_only`).length
      );
    }, 0);
  }
}
