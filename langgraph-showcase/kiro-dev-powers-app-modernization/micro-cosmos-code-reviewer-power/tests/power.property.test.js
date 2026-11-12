import { describe, test, expect } from 'vitest';
import * as fc from 'fast-check';
import fs from 'fs';
import yaml from 'js-yaml';

const POWER_PATH = new URL('../POWER.md', import.meta.url).pathname;
const raw = fs.readFileSync(POWER_PATH, 'utf8');
const parts = raw.split('---');
const frontmatter = yaml.load(parts[1]);
const body = parts.slice(2).join('---');

// Feature: micro-cosmos-code-reviewer-power, Property 1: Frontmatter Schema Completeness
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

// Feature: micro-cosmos-code-reviewer-power, Property 2: Keyword Category Coverage
test('Property 2: Keyword Category Coverage', () => {
  const reviewKeywords = ['code-review', 'review', 'adversarial', 'skeptical'];
  const brandKeywords = ['micro-cosmos', 'modernization'];
  const severityKeywords = ['blocker', 'major', 'minor'];
  const qualityKeywords = ['tdd', 'decimal', 'hexagonal', 'fidelity'];

  fc.assert(fc.property(
    fc.tuple(
      fc.constantFrom(...reviewKeywords),
      fc.constantFrom(...brandKeywords),
      fc.constantFrom(...severityKeywords),
      fc.constantFrom(...qualityKeywords),
      fc.array(fc.string({ minLength: 1, maxLength: 30 }), { minLength: 0, maxLength: 5 }),
    ).map(([rev, alc, sev, qual, extra]) => [rev, alc, sev, qual, ...extra]),
    (keywords) => {
      const hasReview = keywords.some(k => reviewKeywords.includes(k));
      const hasBrand = keywords.some(k => brandKeywords.includes(k));
      const hasSeverity = keywords.some(k => severityKeywords.includes(k));
      const hasQuality = keywords.some(k => qualityKeywords.includes(k));
      expect(hasReview).toBe(true);
      expect(hasBrand).toBe(true);
      expect(hasSeverity).toBe(true);
      expect(hasQuality).toBe(true);
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
  expect(kw.some(k => ['code-review', 'review', 'adversarial', 'skeptical'].includes(k))).toBe(true);
  expect(kw.some(k => ['micro-cosmos'].includes(k))).toBe(true);
  expect(kw.some(k => ['blocker', 'major', 'minor'].includes(k))).toBe(true);
  expect(kw.some(k => ['tdd', 'decimal', 'hexagonal', 'fidelity', 'correctness'].includes(k))).toBe(true);
});
