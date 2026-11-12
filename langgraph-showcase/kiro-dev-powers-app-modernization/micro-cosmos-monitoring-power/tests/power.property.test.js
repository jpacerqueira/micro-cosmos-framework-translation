import { describe, test, expect } from 'vitest';
import * as fc from 'fast-check';
import fs from 'fs';
import yaml from 'js-yaml';

const POWER_PATH = new URL('../POWER.md', import.meta.url).pathname;
const raw = fs.readFileSync(POWER_PATH, 'utf8');
const parts = raw.split('---');
const frontmatter = yaml.load(parts[1]);
const body = parts.slice(2).join('---');

// Feature: micro-cosmos-monitoring-power, Property 1: Frontmatter Schema Completeness
test('Property 1: Frontmatter Schema Completeness', () => {
  fc.assert(fc.property(
    fc.record({
      name: fc.string({ minLength: 1, maxLength: 100 }),
      displayName: fc.string({ minLength: 1, maxLength: 100 }),
      author: fc.string({ minLength: 1, maxLength: 100 }),
      description: fc.string({ minLength: 10, maxLength: 1024 }),
      keywords: fc.array(fc.string({ minLength: 1, maxLength: 50 }), { minLength: 1, maxLength: 50 }),
    }),
    (fm) => {
      expect(typeof fm.name).toBe('string');
      expect(fm.name.length).toBeGreaterThan(0);
      expect(typeof fm.description).toBe('string');
      expect(fm.description.length).toBeGreaterThanOrEqual(10);
      expect(Array.isArray(fm.keywords)).toBe(true);
      expect(fm.keywords.length).toBeGreaterThan(0);
      fm.keywords.forEach(k => expect(typeof k).toBe('string'));
    }
  ), { numRuns: 100 });
});

// Feature: micro-cosmos-monitoring-power, Property 2: Keyword Category Coverage
test('Property 2: Keyword Category Coverage', () => {
  const observabilityKeywords = ['monitoring', 'observability', 'telemetry', 'opentelemetry', 'otel'];
  const brandKeywords = ['micro-cosmos', 'legacy'];
  const languageKeywords = ['java', 'csharp', 'typescript', 'nodejs'];
  const signalKeywords = ['logging', 'metrics', 'tracing', 'health'];

  fc.assert(fc.property(
    fc.tuple(
      fc.constantFrom(...observabilityKeywords),
      fc.constantFrom(...brandKeywords),
      fc.constantFrom(...languageKeywords),
      fc.constantFrom(...signalKeywords),
      fc.array(fc.string({ minLength: 1, maxLength: 30 }), { minLength: 0, maxLength: 5 }),
    ).map(([obs, alc, lang, sig, extra]) => [obs, alc, lang, sig, ...extra]),
    (keywords) => {
      const hasObservability = keywords.some(k => observabilityKeywords.includes(k));
      const hasBrand = keywords.some(k => brandKeywords.includes(k));
      const hasLanguage = keywords.some(k => languageKeywords.includes(k));
      const hasSignal = keywords.some(k => signalKeywords.includes(k));
      expect(hasObservability).toBe(true);
      expect(hasBrand).toBe(true);
      expect(hasLanguage).toBe(true);
      expect(hasSignal).toBe(true);
    }
  ), { numRuns: 100 });
});

// Validate actual POWER.md
test('Actual POWER.md satisfies Property 1', () => {
  expect(typeof frontmatter.name).toBe('string');
  expect(frontmatter.name.length).toBeGreaterThan(0);
  expect(typeof frontmatter.description).toBe('string');
  expect(frontmatter.description.length).toBeGreaterThanOrEqual(10);
  expect(Array.isArray(frontmatter.keywords)).toBe(true);
  expect(frontmatter.keywords.length).toBeGreaterThan(0);
});

test('Actual POWER.md satisfies Property 2 — keyword categories covered', () => {
  const kw = frontmatter.keywords;
  expect(kw.some(k => ['monitoring', 'observability', 'opentelemetry', 'otel', 'telemetry'].includes(k))).toBe(true);
  expect(kw.some(k => ['micro-cosmos', 'legacy'].includes(k))).toBe(true);
  expect(kw.some(k => ['java', 'csharp', 'typescript', 'nodejs'].includes(k))).toBe(true);
  expect(kw.some(k => ['logging', 'metrics', 'tracing', 'health'].includes(k))).toBe(true);
});
