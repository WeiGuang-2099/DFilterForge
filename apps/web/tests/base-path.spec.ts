import {readFileSync} from 'node:fs';
import path from 'node:path';

import {expect, test} from '@playwright/test';

import {DEFAULT_BASE_PATH} from '../scripts/base_path.mjs';

// scripts/base_path.mjs resolves the base path, but three files that cannot
// import it write its default again. A Docker build always sets the
// variable from its build argument, and the composite action hands one
// literal to both the build and the tests, so a default changed only in the
// module would leave CI green while the deployed prefix stays the old one.
// This test makes that drift fail.

const REPOSITORY = path.join(__dirname, '..', '..', '..');

function read(...segments: string[]): string {
  return readFileSync(path.join(REPOSITORY, ...segments), 'utf8').replaceAll('\r\n', '\n');
}

test('the Dockerfile build argument defaults to the module default', () => {
  const dockerfile = read('apps', 'web', 'Dockerfile');
  const defaults = Array.from(
    dockerfile.matchAll(/^ARG PAGES_BASE_PATH=(.*)$/gm),
    (match) => match[1],
  );

  expect(defaults).toEqual([DEFAULT_BASE_PATH]);
});

test('the web-site action input defaults to the module default', () => {
  const action = read('.github', 'actions', 'web-site', 'action.yml');
  const input = /^ {2}base-path:\n(?: {4}.*\n)*? {4}default: (.*)$/m.exec(action);

  expect(input?.[1]).toBe(DEFAULT_BASE_PATH);
});

test('the CI loopback probe asks for the module default', () => {
  const workflow = read('.github', 'workflows', 'ci.yml');
  const probes = Array.from(
    workflow.matchAll(/http:\/\/127\.0\.0\.1:3000(\S*)/g),
    (match) => match[1],
  );

  expect(probes).toEqual([`${DEFAULT_BASE_PATH}/`]);
});
