import {mkdirSync, mkdtempSync, rmSync, symlinkSync, writeFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import path from 'node:path';

import {expect, test} from '@playwright/test';

import {Resolver} from './support/resolve';

// The consistency test trusts the resolver to read only committed bytes at
// the path a source names. These cases pin the path rules on a scratch tree.

let root: string;

test.beforeEach(() => {
  root = mkdtempSync(path.join(tmpdir(), 'resolve-'));
  mkdirSync(path.join(root, 'private'));
  writeFileSync(path.join(root, 'private', 'secret.json'), '{"token": "x"}\n');
  mkdirSync(path.join(root, 'docs', 'results', 'dev-y-2026-09-26'), {recursive: true});
  writeFileSync(
    path.join(root, 'docs', 'results', 'dev-y-2026-09-26', 'ok.json'),
    '{"token": "y"}\n',
  );
});

test.afterEach(() => {
  rmSync(root, {recursive: true, force: true});
});

test('a committed file under an allowed root resolves', () => {
  const resolver = new Resolver(root);

  expect(resolver.resolve(['ptr', 'docs/results/dev-y-2026-09-26/ok.json', '/token'])).toBe('y');
});

test('a directory link inside the repository is refused', () => {
  // A link from an allowed root to a folder that is not one would read that
  // folder's bytes under the allowed path. A junction needs no privilege on
  // Windows, and Node reports it as a link.
  const link = path.join(root, 'docs', 'results', 'dev-x-2026-09-26');
  if (process.platform === 'win32') {
    symlinkSync(path.join(root, 'private'), link, 'junction');
  } else {
    symlinkSync(path.join('..', '..', 'private'), link, 'dir');
  }
  const resolver = new Resolver(root);

  expect(() =>
    resolver.resolve(['ptr', 'docs/results/dev-x-2026-09-26/secret.json', '/token']),
  ).toThrow(/passes through a link/);
});

test('a path outside the allowed roots is refused before any read', () => {
  const resolver = new Resolver(root);

  expect(() => resolver.resolve(['ptr', 'private/secret.json', '/token'])).toThrow(
    /outside the allowed roots/,
  );
  expect(() => resolver.resolve(['ptr', 'docs/results/../../private/secret.json', ''])).toThrow(
    /not a clean path/,
  );
});
