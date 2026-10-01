import {defineConfig, globalIgnores} from 'eslint/config';
import nextCoreWebVitals from 'eslint-config-next/core-web-vitals';
import nextTypeScript from 'eslint-config-next/typescript';

// Model output is untrusted and is rendered as text only. react/no-danger
// sees the prop only where it is written on an element, so the name itself
// is banned too: in a spread object, a createElement props object, a member
// access or a string key, on any component. The name is only ever written
// inside these selectors, never as a string of its own, or this file would
// match them.
const BASE_SYNTAX = [
  {
    selector: 'TSNonNullExpression',
    message: 'Handle the nullable case explicitly.',
  },
  {
    selector:
      ":matches(Identifier, JSXIdentifier)[name='dangerouslySetInnerHTML'], " +
      "Literal[value='dangerouslySetInnerHTML'], " +
      "TemplateElement[value.cooked='dangerouslySetInnerHTML']",
    message: 'Model output is rendered as text only; never set inner HTML.',
  },
];

// No hand-written number on a page: every value comes from a committed file
// through <Num> or <Str> (lib/sourced.tsx), which tests/consistency.spec.ts
// re-derives. These selectors catch digits typed into markup, where a value
// would otherwise bypass that path; tests/lint-rules.spec.ts proves each one
// fires. The runtime sweep in the consistency test is the full check; this
// is the backstop that fails before a build.
const DIGIT_MESSAGE =
  'A digit in markup is a hand-written number. Render values with <Num> or ' +
  '<Str> from lib/sourced.tsx, and a reviewed name that holds a digit with ' +
  '<Term> from lib/terms.ts.';
// Any Unicode number character, not only ASCII digits: a fullwidth or
// Arabic-Indic digit, a superscript or a Roman numeral is as hand-written.
const DIGIT = '/\\p{N}/u';
// A JSX child expression, as opposed to an attribute's value.
const CHILD = ':matches(JSXElement, JSXFragment) > JSXExpressionContainer';
// Attributes whose value a browser shows or a screen reader announces; a
// list shows its start as the first marker.
const TEXT_ATTRIBUTE =
  'JSXAttribute[name.name=/^(alt|label|placeholder|start|title|value|' +
  'aria-(description|label|placeholder|roledescription|valuemax|valuemin|valuenow|valuetext))$/]';
const METADATA =
  ":matches(VariableDeclarator[id.name='metadata'], " +
  "FunctionDeclaration[id.name='generateMetadata'])";
const METADATA_TEXT = 'Property[key.name=/^(absolute|default|description|template|title)$/]';

const NUMBER_SYNTAX = [
  {selector: `JSXText[value=${DIGIT}]`, message: DIGIT_MESSAGE},
  {selector: `${CHILD} > Literal[raw=${DIGIT}]`, message: DIGIT_MESSAGE},
  {
    selector:
      `${CHILD} :matches(ConditionalExpression, LogicalExpression) > ` +
      `Literal[raw=${DIGIT}]`,
    message: DIGIT_MESSAGE,
  },
  {
    selector: `${CHILD} BinaryExpression[operator='+'] > Literal[raw=${DIGIT}]`,
    message: DIGIT_MESSAGE,
  },
  {selector: `${CHILD} TemplateElement[value.raw=${DIGIT}]`, message: DIGIT_MESSAGE},
  // An attribute's own value only: JSX passed in a prop, such as a <Term>
  // inside a label, is checked by the child rules above.
  {selector: `${TEXT_ATTRIBUTE} > Literal[raw=${DIGIT}]`, message: DIGIT_MESSAGE},
  {
    selector: `${TEXT_ATTRIBUTE} > JSXExpressionContainer > Literal[raw=${DIGIT}]`,
    message: DIGIT_MESSAGE,
  },
  {
    selector:
      `${TEXT_ATTRIBUTE} > JSXExpressionContainer > TemplateLiteral > ` +
      `TemplateElement[value.raw=${DIGIT}]`,
    message: DIGIT_MESSAGE,
  },
  {
    selector:
      `${METADATA} ${METADATA_TEXT} :matches(Literal[raw=${DIGIT}], ` +
      `TemplateElement[value.raw=${DIGIT}])`,
    message: 'A page title or description is fixed text without a digit.',
  },
  {
    selector:
      `${METADATA} ${METADATA_TEXT}` + '[value.type!=/^(Literal|ObjectExpression)$/]',
    message: 'A page title or description is fixed text, never a computed value.',
  },
  {
    selector:
      'MemberExpression[property.name=/^(toExponential|toFixed|' +
      'toLocaleDateString|toLocaleString|toLocaleTimeString|toPrecision)$/]',
    message: 'Format values in lib/fmt.ts only.',
  },
  {
    selector: "MemberExpression[object.name='Intl']",
    message: 'Format values in lib/fmt.ts only.',
  },
];

export default defineConfig([
  ...nextCoreWebVitals,
  ...nextTypeScript,
  {
    rules: {
      '@typescript-eslint/no-explicit-any': 'error',
      '@typescript-eslint/consistent-type-imports': 'error',
      'no-restricted-syntax': ['error', ...BASE_SYNTAX],
      // No exception anywhere, tests included; '*' extends the rule from DOM
      // elements to every component. BASE_SYNTAX bans the name elsewhere.
      'react/no-danger': ['error', {customComponentNames: ['*']}],
    },
  },
  {
    files: ['app/**/*.{ts,tsx}', 'lib/**/*.{ts,tsx}'],
    ignores: ['lib/fmt.ts'],
    rules: {
      'no-restricted-syntax': ['error', ...BASE_SYNTAX, ...NUMBER_SYNTAX],
    },
  },
  globalIgnores(['.next/**', 'out/**', 'next-env.d.ts']),
]);
