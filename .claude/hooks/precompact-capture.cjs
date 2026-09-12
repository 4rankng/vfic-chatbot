#!/usr/bin/env node
'use strict';

/**
 * PreCompact Hook - Capture orientation anchors before compaction
 *
 * Fires: Before the transcript is compacted (manual or auto).
 * Purpose: Persist the machine-derivable orientation (worktree, main project
 *   root, branch, HEAD, dirty count, active plan) into session state so the
 *   post-compaction SessionStart:compact reminder can present concrete anchors.
 *
 * Why a side-effect capture and not a printed reminder: PreCompact stdout is
 * NOT injected into the model's post-compaction context (unlike
 * SessionStart:compact, which is). The agent also does not get a turn between
 * "context full" and an auto-compact, so it cannot be prompted to journal at
 * that instant. This hook therefore records what it can derive deterministically;
 * session-init.cjs surfaces it and reminds the agent to re-establish the rest.
 *
 * Exit code: always 0 (non-blocking; never obstruct compaction).
 */

try {
  const fs = require('fs');
  const { execFileSync } = require('child_process');
  const {
    createSessionStateContext,
    updateSessionState,
    isHookEnabled
  } = require('./lib/ck-config-utils.cjs');

  if (!isHookEnabled('precompact-capture')) process.exit(0);

  function cleanGitEnvironment() {
    const environment = { ...process.env };
    for (const key of Object.keys(environment)) {
      const normalized = key.toUpperCase();
      if (normalized === 'GIT_CONFIG_COUNT' || normalized.startsWith('GIT_')) delete environment[key];
    }
    return environment;
  }

  function git(args, cwd) {
    try {
      return execFileSync('git', args, {
        cwd,
        env: cleanGitEnvironment(),
        encoding: 'utf8',
        timeout: 2000,
        stdio: ['ignore', 'pipe', 'ignore']
      }).trim() || null;
    } catch {
      return null;
    }
  }

  function readBoundedStdin(maxBytes = 256 * 1024) {
    const chunks = [];
    let total = 0;
    for (;;) {
      const chunk = Buffer.allocUnsafe(Math.min(8192, maxBytes + 1 - total));
      const count = fs.readSync(0, chunk, 0, chunk.length, null);
      if (count === 0) break;
      total += count;
      if (total > maxBytes) return null;
      chunks.push(chunk.subarray(0, count));
    }
    return Buffer.concat(chunks, total).toString('utf8').trim();
  }

  const stdin = readBoundedStdin();
  if (stdin === null) process.exit(0);
  const data = stdin ? JSON.parse(stdin) : {};
  const piRuntime = data.runtime === 'pi';
  const cwd = (piRuntime ? data.cwd : process.env.CK_PROJECT_ROOT || data.cwd) || process.cwd();
  const context = createSessionStateContext({
    sessionId: data.session_id,
    cwd,
    ...(piRuntime
      ? { runtime: 'pi', bindSession: true }
      : { requireBinding: true })
  });
  if (!context) process.exit(0);

  const worktree = git(['rev-parse', '--show-toplevel'], cwd);
  // For a linked worktree, --git-common-dir points at the main repo's .git;
  // its parent is the primary working tree (the "root project" directory).
  const commonDir = git(['rev-parse', '--path-format=absolute', '--git-common-dir'], cwd);
  const mainRoot = commonDir ? commonDir.replace(/[\\/]\.git\/?$/, '') : null;
  const dirty = git(['status', '--porcelain'], cwd);

  const compactRecovery = {
    capturedAt: new Date().toISOString(),
    trigger: data.trigger || null,
    worktree,
    mainRoot: mainRoot && mainRoot !== worktree ? mainRoot : null,
    branch: git(['branch', '--show-current'], cwd),
    head: git(['rev-parse', '--short', 'HEAD'], cwd),
    dirtyCount: dirty ? dirty.split('\n').filter(Boolean).length : 0
  };

  updateSessionState(context, (state) => ({
    ...state,
    compactRecovery: {
      ...compactRecovery,
      // Carry the active plan the checkpoint pipeline already tracks, if any.
      activePlan: typeof state?.activePlan === 'string' ? state.activePlan : null
    }
  }));

  process.exit(0);
} catch {
  process.exit(0);
}
