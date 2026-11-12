import { test, expect } from 'vitest';
import fs from 'fs';
import yaml from 'js-yaml';

const POWER_PATH = new URL('../POWER.md', import.meta.url).pathname;
const raw = fs.readFileSync(POWER_PATH, 'utf8');
const parts = raw.split('---');
const frontmatter = yaml.load(parts[1]);
const body = parts.slice(2).join('---');

// Frontmatter values
test('name is micro-cosmos-code-writer', () => {
  expect(frontmatter.name).toBe('micro-cosmos-code-writer');
});
test('displayName is Micro-Cosmos Code Writer', () => {
  expect(frontmatter.displayName).toBe('Micro-Cosmos Code Writer');
});
test('author is Micro-Cosmos', () => {
  expect(frontmatter.author).toBe('Micro-Cosmos');
});
test('keywords include code-writer', () => {
  expect(frontmatter.keywords).toContain('code-writer');
});
test('keywords include micro-cosmos', () => {
  expect(frontmatter.keywords).toContain('micro-cosmos');
});
test('keywords include hexagonal', () => {
  expect(frontmatter.keywords).toContain('hexagonal');
});
test('keywords include tdd', () => {
  expect(frontmatter.keywords).toContain('tdd');
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
test('body contains Seam ID', () => {
  expect(body).toContain('Seam ID');
});

// Hexagonal layers
test('body contains Hexagonal Layer Rules', () => {
  expect(body).toContain('Hexagonal Layer Rules');
});
test('body references domain layer', () => {
  expect(body).toContain('domain/');
});
test('body references application layer', () => {
  expect(body).toContain('application/');
});
test('body references infrastructure layer', () => {
  expect(body).toContain('infrastructure/');
});

// Decimal hygiene
test('body contains Decimal Hygiene section', () => {
  expect(body).toContain('Decimal Hygiene');
});
test('body references BigDecimal', () => {
  expect(body).toContain('BigDecimal');
});

// OTel
test('body contains OTel Instrumentation section', () => {
  expect(body).toContain('OTel');
});

// Workflows
test('body contains Common Workflows section', () => {
  expect(body).toContain('Common Workflows');
});
test('body contains workflow for translating a seam', () => {
  expect(body).toContain('Translate a new seam');
});
test('body contains workflow for fixing TDD review', () => {
  expect(body).toContain('Fix a failing TDD review');
});

// Gate 5
test('body contains PR Gate Alignment', () => {
  expect(body).toContain('Gate 5');
});
