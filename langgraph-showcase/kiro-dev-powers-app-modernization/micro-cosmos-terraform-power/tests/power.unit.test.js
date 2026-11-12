import { test, expect } from 'vitest';
import fs from 'fs';
import yaml from 'js-yaml';

const POWER_PATH = new URL('../POWER.md', import.meta.url).pathname;
const raw = fs.readFileSync(POWER_PATH, 'utf8');
const parts = raw.split('---');
const frontmatter = yaml.load(parts[1]);
const body = parts.slice(2).join('---');

// Frontmatter values
test('name is micro-cosmos-terraform', () => {
  expect(frontmatter.name).toBe('micro-cosmos-terraform');
});
test('displayName is Micro-Cosmos Terraform', () => {
  expect(frontmatter.displayName).toBe('Micro-Cosmos Terraform');
});
test('author is Micro-Cosmos', () => {
  expect(frontmatter.author).toBe('Micro-Cosmos');
});
test('keywords include terraform', () => {
  expect(frontmatter.keywords).toContain('terraform');
});
test('keywords include microservice', () => {
  expect(frontmatter.keywords).toContain('microservice');
});
test('keywords include micro-cosmos', () => {
  expect(frontmatter.keywords).toContain('micro-cosmos');
});
test('keywords include security', () => {
  expect(frontmatter.keywords).toContain('security');
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

// Response Contract section
test('body contains Response Contract section', () => {
  expect(body).toContain('Response Contract');
});
test('body contains microservice module coverage check', () => {
  expect(body).toContain('Microservice Module Coverage');
});
test('body contains WARN for missing module', () => {
  expect(body).toContain('WARN');
});

// Security baseline
test('body contains Security Baseline section', () => {
  expect(body).toContain('Security Baseline');
});
test('body references trivy config', () => {
  expect(body).toContain('trivy config');
});
test('body references checkov', () => {
  expect(body).toContain('checkov');
});
test('body mentions encryption', () => {
  expect(body).toContain('encrypt');
});

// Pipeline gate alignment
test('body references Gate 5', () => {
  expect(body).toContain('Gate 5');
});
test('body references bounded context', () => {
  expect(body).toContain('bounded context');
});

// Module conventions
test('body references modules/ directory layout', () => {
  expect(body).toContain('modules/');
});
test('body references environments/ directory', () => {
  expect(body).toContain('environments/');
});

// Workflow presence
test('body contains Common Workflows section', () => {
  expect(body).toContain('Common Workflows');
});
test('body contains workflow for reviewing existing HCL', () => {
  expect(body).toContain('Review existing HCL');
});
test('body contains workflow for generating a new module', () => {
  expect(body).toContain('Generate a new bounded-context module');
});
test('body contains workflow for security review before apply', () => {
  expect(body).toContain('Security review before apply');
});
