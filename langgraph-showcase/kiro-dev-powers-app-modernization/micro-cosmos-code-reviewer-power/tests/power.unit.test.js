import { test, expect } from 'vitest';
import fs from 'fs';
import yaml from 'js-yaml';

const POWER_PATH = new URL('../POWER.md', import.meta.url).pathname;
const raw = fs.readFileSync(POWER_PATH, 'utf8');
const parts = raw.split('---');
const frontmatter = yaml.load(parts[1]);
const body = parts.slice(2).join('---');

// Frontmatter values
test('name is micro-cosmos-code-reviewer', () => {
  expect(frontmatter.name).toBe('micro-cosmos-code-reviewer');
});
test('displayName is Micro-Cosmos Code Reviewer', () => {
  expect(frontmatter.displayName).toBe('Micro-Cosmos Code Reviewer');
});
test('author is Micro-Cosmos', () => {
  expect(frontmatter.author).toBe('Micro-Cosmos');
});
test('keywords include code-review', () => {
  expect(frontmatter.keywords).toContain('code-review');
});
test('keywords include micro-cosmos', () => {
  expect(frontmatter.keywords).toContain('micro-cosmos');
});
test('keywords include blocker', () => {
  expect(frontmatter.keywords).toContain('blocker');
});

// File structure
test('POWER.md file exists', () => {
  expect(fs.existsSync(POWER_PATH)).toBe(true);
});
test('README.md exists', () => {
  const p = new URL('../README.md', import.meta.url).pathname;
  expect(fs.existsSync(p)).toBe(true);
});
test('package.json exists', () => {
  const p = new URL('../package.json', import.meta.url).pathname;
  expect(fs.existsSync(p)).toBe(true);
});

// Response Contract
test('body contains Response Contract section', () => {
  expect(body).toContain('Response Contract');
});
test('body contains verdict PASS/WARN/FAIL', () => {
  expect(body).toContain('PASS');
  expect(body).toContain('FAIL');
});

// Severity definitions
test('body contains Severity Definitions', () => {
  expect(body).toContain('Severity Definitions');
});
test('body defines BLOCKER severity', () => {
  expect(body).toContain('BLOCKER');
});
test('body defines MAJOR severity', () => {
  expect(body).toContain('MAJOR');
});
test('body defines MINOR severity', () => {
  expect(body).toContain('MINOR');
});
test('body defines NIT severity', () => {
  expect(body).toContain('NIT');
});

// 7-category checklist
test('body contains 7-Category Checklist', () => {
  expect(body).toContain('7-Category Checklist');
});
test('body covers Functional Equivalence', () => {
  expect(body).toContain('Functional Equivalence');
});
test('body covers Decimal Hygiene', () => {
  expect(body).toContain('Decimal Hygiene');
});
test('body covers Hexagonal Compliance', () => {
  expect(body).toContain('Hexagonal Compliance');
});
test('body covers OTel / Observability', () => {
  expect(body).toContain('OTel');
});

// Gate 5
test('body references Gate 5 verdict', () => {
  expect(body).toContain('Gate 5');
});

// Workflows
test('body contains Common Workflows section', () => {
  expect(body).toContain('Common Workflows');
});
test('body contains skeptical first-pass review workflow', () => {
  expect(body).toContain('Skeptical first-pass review');
});
