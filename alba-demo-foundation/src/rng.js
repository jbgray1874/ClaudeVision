/**
 * Deterministic pseudo-random numbers.
 *
 * The demo must produce identical figures on every run and on every machine —
 * a scenario walkthrough where the numbers move between rehearsal and the
 * meeting is worse than no demo at all. Everything generated in this package
 * is seeded.
 */

/** mulberry32 — small, fast, adequate for synthetic data. */
export function makeRng(seed) {
  let a = seed >>> 0;
  return function next() {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** Stable 32-bit hash so a string key can seed its own stream. */
export function seedFrom(key) {
  let h = 2166136261 >>> 0;
  for (let i = 0; i < key.length; i++) {
    h ^= key.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

export function rngFor(key) {
  return makeRng(seedFrom(key));
}

/** Uniform in [min, max). */
export function between(rng, min, max) {
  return min + rng() * (max - min);
}

/** Approximately normal via sum of uniforms, clamped to ±3 sd. */
export function jitter(rng, sd = 1) {
  const n = (rng() + rng() + rng() + rng() + rng() + rng() - 3) / 0.7071;
  return Math.max(-3, Math.min(3, n)) * sd;
}

export function pick(rng, items) {
  return items[Math.floor(rng() * items.length)];
}
