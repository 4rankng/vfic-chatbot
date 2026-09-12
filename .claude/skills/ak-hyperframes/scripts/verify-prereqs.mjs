#!/usr/bin/env node
/**
 * verify-prereqs.mjs — one-shot prerequisite check for the ak-hyperframes skill.
 *
 * Usage:
 *   node verify-prereqs.mjs [--json]
 *
 * Checks:
 *   - Node.js >= 22.0.0 (semver-compared against process.versions.node).
 *   - FFmpeg on PATH (spawnSync('ffmpeg', ['-version'])).
 *
 * Tests run with AK_HYPERFRAMES_TEST_MODE=1 to unlock MOCK_NODE_VERSION /
 * MOCK_FFMPEG_PRESENT=0|1 overrides without depending on real system state.
 * Both the test-mode flag and the individual MOCK_ var are required — a
 * stray MOCK_FFMPEG_PRESENT left in a real shell must not silently fake a
 * READY result for an actual user.
 *
 * Exit 0 with a "READY" line when both checks pass. Exit non-zero with
 * actionable remediation (also printed to stderr) when any check fails.
 * A structured summary is always printed to stdout — JSON with --json,
 * a human-readable table otherwise.
 */

import { parseArgs } from 'node:util';
import { spawnSync } from 'node:child_process';

const MIN_NODE_VERSION = '22.0.0';
const TEST_MODE = process.env.AK_HYPERFRAMES_TEST_MODE === '1';

function parseCliArgs(argv) {
  return parseArgs({
    args: argv,
    options: {
      json: { type: 'boolean', default: false },
      help: { type: 'boolean', default: false },
    },
    allowPositionals: false,
  });
}

/** Parse a `major.minor.patch`-shaped string into a comparable tuple. Missing/non-numeric parts default to 0. */
function parseSemver(version) {
  const [major = '0', minor = '0', patch = '0'] = String(version).split('.');
  return [Number(major) || 0, Number(minor) || 0, Number(patch) || 0];
}

/** Full major.minor.patch comparison; returns <0, 0, or >0 like Array.prototype.sort comparators. */
function compareVersions(a, b) {
  const va = parseSemver(a);
  const vb = parseSemver(b);
  for (let i = 0; i < 3; i += 1) {
    if (va[i] !== vb[i]) return va[i] - vb[i];
  }
  return 0;
}

function isVersionAtLeast(version, minVersion) {
  return compareVersions(version, minVersion) >= 0;
}

function checkNodeVersion() {
  const version = (TEST_MODE && process.env.MOCK_NODE_VERSION) || process.versions.node;
  const ok = isVersionAtLeast(version, MIN_NODE_VERSION);
  return {
    name: 'node',
    ok,
    detail: `Node ${version}`,
    remediation: ok ? null : `Node 22+ required (found ${version}). Upgrade Node: nvm install 22`,
  };
}

function checkFfmpeg() {
  const FFMPEG_INSTALL_HINT = 'Install FFmpeg: brew install ffmpeg (macOS) or apt install ffmpeg (Debian/Ubuntu)';

  if (TEST_MODE && process.env.MOCK_FFMPEG_PRESENT === '0') {
    return { name: 'ffmpeg', ok: false, detail: 'ffmpeg not found on PATH (mocked)', remediation: FFMPEG_INSTALL_HINT };
  }
  if (TEST_MODE && process.env.MOCK_FFMPEG_PRESENT === '1') {
    return { name: 'ffmpeg', ok: true, detail: 'ffmpeg present (mocked)', remediation: null };
  }

  // shell:true is needed on win32 to resolve ffmpeg via PATH lookup rules
  // (PATHEXT-based .exe resolution) the way cmd.exe would. Safe here — argv
  // is the fixed literal ['-version'], never user- or caller-supplied
  // content, so there's nothing for shell:true to misinterpret.
  const result = spawnSync('ffmpeg', ['-version'], {
    encoding: 'utf8',
    shell: process.platform === 'win32',
  });

  const ok = !result.error && result.status === 0;
  return {
    name: 'ffmpeg',
    ok,
    detail: ok ? (result.stdout || '').split('\n')[0].trim() : 'ffmpeg not found on PATH',
    remediation: ok ? null : FFMPEG_INSTALL_HINT,
  };
}

function printHuman(checks, allOk) {
  for (const check of checks) {
    console.log(`[${check.ok ? 'OK' : 'FAIL'}] ${check.name}: ${check.detail}`);
  }
  if (allOk) {
    console.log('READY — all ak-hyperframes prerequisites satisfied.');
  } else {
    console.log('NOT READY — see remediation below.');
    for (const check of checks.filter((c) => !c.ok)) {
      console.error(check.remediation);
    }
  }
}

function printJson(checks, allOk) {
  console.log(JSON.stringify({ ready: allOk, checks }, null, 2));
  for (const check of checks.filter((c) => !c.ok)) {
    console.error(check.remediation);
  }
}

function main() {
  let values;
  try {
    ({ values } = parseCliArgs(process.argv.slice(2)));
  } catch (error) {
    console.error(`[verify-prereqs] invalid arguments: ${error.message}`);
    process.exitCode = 1;
    return;
  }

  if (values.help) {
    console.log('Usage: node verify-prereqs.mjs [--json]');
    return;
  }

  const checks = [checkNodeVersion(), checkFfmpeg()];
  const allOk = checks.every((c) => c.ok);

  if (values.json) {
    printJson(checks, allOk);
  } else {
    printHuman(checks, allOk);
  }

  process.exitCode = allOk ? 0 : 1;
}

main();
