import { test, expect } from 'vitest';
import fs from 'fs';
import yaml from 'js-yaml';

const POWER_PATH = new URL('../POWER.md', import.meta.url).pathname;
const raw = fs.readFileSync(POWER_PATH, 'utf8');
const parts = raw.split('---');
const frontmatter = yaml.load(parts[1]);
const body = parts.slice(2).join('---');

// Frontmatter values
test('name is micro-cosmos-monitoring', () => {
  expect(frontmatter.name).toBe('micro-cosmos-monitoring');
});
test('displayName is Micro-Cosmos Monitoring', () => {
  expect(frontmatter.displayName).toBe('Micro-Cosmos Monitoring');
});
test('author is Micro-Cosmos', () => {
  expect(frontmatter.author).toBe('Micro-Cosmos');
});
test('keywords include monitoring', () => {
  expect(frontmatter.keywords).toContain('monitoring');
});
test('keywords include opentelemetry', () => {
  expect(frontmatter.keywords).toContain('opentelemetry');
});
test('keywords include micro-cosmos', () => {
  expect(frontmatter.keywords).toContain('micro-cosmos');
});
test('keywords include java', () => {
  expect(frontmatter.keywords).toContain('java');
});
test('keywords include csharp', () => {
  expect(frontmatter.keywords).toContain('csharp');
});
test('keywords include typescript', () => {
  expect(frontmatter.keywords).toContain('typescript');
});

// File structure
test('POWER.md file exists', () => {
  expect(fs.existsSync(POWER_PATH)).toBe(true);
});
test('README.md exists', () => {
  const p = new URL('../README.md', import.meta.url).pathname;
  expect(fs.existsSync(p)).toBe(true);
});

// Response contract
test('body contains Response Contract section', () => {
  expect(body).toContain('Response Contract');
});
test('body contains maturity score 0-100', () => {
  expect(body).toContain('0–100');
});
test('body contains five monitoring dimensions', () => {
  expect(body).toContain('Logging');
  expect(body).toContain('Metrics');
  expect(body).toContain('Tracing');
  expect(body).toContain('Health');
  expect(body).toContain('Alerting');
});

// OTel instrumentation for all language stacks
test('body contains Java OTel instrumentation', () => {
  expect(body).toContain('OpenTelemetry Instrumentation — Java');
});
test('body contains C# OTel instrumentation', () => {
  expect(body).toContain('OpenTelemetry Instrumentation — C#');
});
test('body contains Node.js/TypeScript OTel instrumentation', () => {
  expect(body).toContain('OpenTelemetry Instrumentation — Node.js');
});
test('body contains Scala OTel instrumentation', () => {
  expect(body).toContain('OpenTelemetry Instrumentation — Scala');
});
test('body contains F# OTel instrumentation', () => {
  expect(body).toContain('OpenTelemetry Instrumentation — F#');
});
test('body contains VB.NET OTel instrumentation', () => {
  expect(body).toContain('OpenTelemetry Instrumentation — VB.NET');
});
test('body references InMemorySpanExporter for JVM/Node.js testing', () => {
  expect(body).toContain('InMemorySpanExporter');
});
test('body references ActivityListener for .NET testing', () => {
  expect(body).toContain('ActivityListener');
});

// Scoring table
test('body contains score interpretation table', () => {
  expect(body).toContain('Production-ready');
  expect(body).toContain('BLOCKER');
});

// Workflows
test('body contains Common Workflows section', () => {
  expect(body).toContain('Common Workflows');
});
test('body contains workflow for scoring legacy app', () => {
  expect(body).toContain('Score legacy application monitoring');
});
test('body contains workflow for generating OTel instrumentation', () => {
  expect(body).toContain('Generate OTel instrumentation');
});
test('body contains workflow for reviewing translated code', () => {
  expect(body).toContain('Review translated code for OTel coverage');
});
