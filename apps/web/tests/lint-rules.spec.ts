import path from 'node:path';

import {expect, test} from '@playwright/test';
import {ESLint} from 'eslint';

import {TERMS} from '../lib/terms';

// Proves that the digit backstop in eslint.config.mjs fires on each way a
// hand-written number can be typed into markup, and stays quiet on the
// sourced components and on numbers that never reach the page. Fixtures are
// linted in memory under paths the config matches; no file is written.

const WEB = path.join(__dirname, '..');

let eslint: ESLint;

test.beforeAll(() => {
  eslint = new ESLint({cwd: WEB});
});

/** Returns the rule ids that fire on one in-memory file. */
async function ruleIds(code: string, file = 'app/fixture.tsx'): Promise<string[]> {
  const results = await eslint.lintText(code, {filePath: path.join(WEB, file)});
  return results.flatMap((result) =>
    result.messages.map((message) => message.ruleId ?? `parse error: ${message.message}`),
  );
}

/** The ids of the rules under test among those that fire, and parse errors. */
async function guardIds(code: string, file?: string): Promise<string[]> {
  return (await ruleIds(code, file)).filter(
    (id) => id === 'no-restricted-syntax' || id === 'react/no-danger' || id.startsWith('parse'),
  );
}

const PLANTED = [
  {name: 'a digit in JSX text', code: 'export const F = () => <p>Cases: 12</p>;'},
  {name: 'a number literal as a child', code: 'export const F = () => <p>{12}</p>;'},
  {name: 'a string literal as a child', code: "export const F = () => <p>{'C4'}</p>;"},
  {
    name: 'a literal in a conditional child',
    code: "export const F = ({a}: {a: boolean}) => <p>{a ? 'none' : 'C4'}</p>;",
  },
  {
    name: 'a literal in a logical child',
    code: 'export const F = ({a}: {a: number | null}) => <p>{a ?? 0}</p>;',
  },
  {
    name: 'a concatenated literal',
    code: "export const F = ({a}: {a: string}) => <p>{a + ' of ' + 12}</p>;",
  },
  {
    name: 'a digit in a template child',
    code: 'export const F = ({a}: {a: string}) => <p>{`${a} of 12`}</p>;',
  },
  {name: 'a digit in aria-label', code: 'export const F = () => <nav aria-label="Top 3" />;'},
  {name: 'a digit in title', code: "export const F = () => <abbr title={'C4'}>x</abbr>;"},
  {name: 'a digit in placeholder', code: 'export const F = () => <input placeholder="80" />;'},
  {name: 'a digit in alt', code: 'export const F = () => <img alt="Probe 2" src="/a.png" />;'},
  {name: 'a number in value', code: 'export const F = () => <li value={3}>x</li>;'},
  {
    name: 'a digit in a template attribute',
    code: 'export const F = ({a}: {a: string}) => <abbr title={`${a} 2`}>x</abbr>;',
  },
  {name: 'a digit in a page title', code: "export const metadata = {title: 'Run 3'};"},
  {
    name: 'a digit in a title template',
    code: "export const metadata = {title: {default: 'Runs', template: '%s 2'}};",
  },
  {
    name: 'a digit in a description',
    code: "export const metadata = {description: 'Ten passes, 4 conditions.'};",
  },
  {
    name: 'a computed page title',
    code: "const name = 'Runs';\nexport const metadata = {title: name};",
  },
  {
    name: 'a computed generateMetadata title',
    code:
      'export function generateMetadata({item}: {item: string}) {\n' +
      '  return {title: `Receipt ${item}`};\n}',
  },
  {name: 'toFixed outside lib/fmt.ts', code: 'export const f = (n: number) => n.toFixed(2);'},
  {
    name: 'toLocaleString outside lib/fmt.ts',
    code: 'export const f = (n: number) => n.toLocaleString();',
  },
  {
    name: 'Intl outside lib/fmt.ts',
    code: "export const f = (n: number) => new Intl.NumberFormat('en').format(n);",
  },
  {
    name: 'a digit in JSX passed as a label',
    code:
      "import type {ReactNode} from 'react';\n" +
      'type G = (props: {label: ReactNode}) => ReactNode;\n' +
      'export const F = ({G}: {G: G}) => <G label={<>Run 3</>} />;',
  },
  {
    name: 'a digit in markup under lib/',
    code: 'export const F = () => <p>Cases: 12</p>;',
    file: 'lib/fixture.tsx',
  },
] as const;

for (const {name, code, ...rest} of PLANTED) {
  test(`lint fails on ${name}`, async () => {
    const file = 'file' in rest ? rest.file : undefined;
    expect(await guardIds(code, file)).toEqual(['no-restricted-syntax']);
  });
}

test('lint fails on dangerouslySetInnerHTML everywhere, tests included', async () => {
  const code =
    'export const F = ({h}: {h: string}) => ' +
    '<div dangerouslySetInnerHTML={{__html: h}} />;';

  expect(await guardIds(code)).toEqual(['react/no-danger']);
  expect(await guardIds(code, 'tests/fixture.tsx')).toEqual(['react/no-danger']);
});

test('lint passes sourced values, terms and numbers that never render', async () => {
  const code = [
    "import type {ReactNode} from 'react';",
    '',
    "import type {NumNode, StrNode} from '@/lib/data';",
    "import {Num, Str, Term} from '@/lib/sourced';",
    '',
    "export const metadata = {title: {default: 'Runs', template: '%s - Runs'}};",
    '',
    'function Fact({label}: {label: ReactNode}) {',
    '  return <dt>{label}</dt>;',
    '}',
    '',
    'export function F({n, s, rows}: {n: NumNode; s: StrNode; rows: readonly string[]}) {',
    '  return (',
    '    <table tabIndex={0}>',
    '      <caption>',
    '        Capture <Term name="SHA-256" />',
    '      </caption>',
    '      <tbody>',
    '        <tr>',
    '          <td colSpan={2}>',
    '            <Num kind="int" node={n} /> <Str node={s} />',
    '            <Fact label={<>Runner <Term name="SHA-256" /></>} />',
    '          </td>',
    '        </tr>',
    '        {rows.length > 0 && rows.slice(0, 3).map((row) => <tr key={row} />)}',
    '      </tbody>',
    '    </table>',
    '  );',
    '}',
  ].join('\n');

  expect(await ruleIds(code)).toEqual([]);
});

test('the formatter and the tests may hold digits', async () => {
  expect(await guardIds('export const f = (n: number) => n.toFixed(2);', 'lib/fmt.ts')).toEqual(
    [],
  );
  expect(await guardIds('export const F = () => <p>Cases: 12</p>;', 'tests/fixture.tsx')).toEqual(
    [],
  );
});

test('the term list is closed and each term holds a letter', () => {
  // Changing this list is a reviewed change: a term is exempt from the
  // digit sweep wherever <Term> renders it.
  expect([...TERMS]).toEqual(['IPv4', 'SHA-256']);
  for (const term of TERMS) {
    expect(term).toMatch(/[A-Za-z]/);
    expect(term).toMatch(/[0-9]/);
  }
});
