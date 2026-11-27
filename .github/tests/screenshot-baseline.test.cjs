// SPDX-License-Identifier: AGPL-3.0-or-later
// The screenshot check's baseline: found for the exact base commit, never from a pull request.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const baseline = require('../screenshot_baseline.cjs');

const workflows = path.join(__dirname, '../workflows');
const ci = fs.readFileSync(path.join(workflows, 'ci.yml'), 'utf8').replaceAll('\r\n', '\n');
const store = fs.readFileSync(path.join(workflows, 'screenshot_store.yml'), 'utf8').replaceAll('\r\n', '\n');

// The text of the step `name` in `workflow`, up to the next step.
function step(workflow, name) {
  const start = workflow.indexOf(`      - name: ${name}\n`);
  assert.notEqual(start, -1, `Missing workflow step: ${name}`);
  const end = workflow.indexOf('\n      - ', start + 1);
  return workflow.slice(start, end === -1 ? undefined : end);
}

function run(id, options = {}) {
  return { id, head_sha: 'base-sha', event: 'push', status: 'completed', conclusion: 'success', ...options };
}

const PR = { pull_request: { base: { sha: 'stale-sha', ref: 'master' } } };

// A fake GitHub: `batches` are the store runs each query returns, `artifacts` each run's artifacts.
function harness({ batches = [[run(42)]], artifacts = {}, payload = PR, sha = 'merge-sha', unregistered = false } = {}) {
  const calls = { runs: [], waits: [], compares: [] };
  const outputs = {};
  let query = 0;
  const context = { repo: { owner: 'AnkiQuest', repo: 'AnkiQuest-Desktop' }, sha, ref: 'refs/pull/1/merge', payload };
  const notFound = () => Object.assign(new Error('Not Found'), { status: 404 });
  const github = { rest: {
    repos: {
      // GitHub builds refs/pull/N/merge with the base it merged into as the first parent.
      async getCommit({ ref }) {
        assert.equal(ref, 'merge-sha');
        return { data: { parents: [{ sha: 'base-sha' }, { sha: 'head-sha' }] } };
      },
      async compareCommitsWithBasehead(request) {
        calls.compares.push(request);
        return { data: { merge_base_commit: { sha: 'base-sha' } } };
      },
    },
    actions: {
      async listWorkflowRuns(request) {
        calls.runs.push(request);
        if (unregistered) {
          throw notFound();
        }
        return { data: { workflow_runs: batches[Math.min(query++, batches.length - 1)] } };
      },
      async listWorkflowRunArtifacts({ run_id: id }) {
        return { data: { artifacts: artifacts[id] ?? [{ name: 'screenshot-baseline', expired: false }] } };
      },
    },
  } };
  const core = { info() {}, setOutput: (name, value) => { outputs[name] = value; } };
  return {
    calls, outputs,
    args: {
      github, context, core,
      sleep: async delay => { calls.waits.push(delay); },
    },
  };
}

test('a pull request compares with the store run of the commit it was merged into', async () => {
  const { args, calls, outputs } = harness();
  assert.equal(42, await baseline(args));
  assert.deepEqual({ base: 'base-sha', 'run-id': '42' }, outputs);
  assert.equal('screenshot_store.yml', calls.runs[0].workflow_id);
  assert.equal('base-sha', calls.runs[0].head_sha);
  assert.deepEqual([], calls.waits);
});

test('only a finished push or dispatch run of that commit with its artifact counts', async () => {
  const runs = [
    run(1, { event: 'pull_request' }),
    run(2, { conclusion: 'failure' }),
    run(3, { status: 'in_progress', conclusion: null }),
    run(4, { head_sha: 'other-sha' }),
    run(5),
    run(6),
    run(7, { event: 'workflow_dispatch' }),
  ];
  const artifacts = { 5: [{ name: 'screenshot-baseline', expired: true }], 6: [{ name: 'other', expired: false }] };
  const { args } = harness({ batches: [runs], artifacts });
  assert.equal(7, await baseline(args));
});

test('a baseline still being stored is waited for', async () => {
  const { args, calls } = harness({ batches: [[], [run(9, { status: 'in_progress', conclusion: null })], [run(9)]] });
  assert.equal(9, await baseline(args));
  assert.equal(2, calls.waits.length);
});

test('no baseline fails after the wait and names the store workflow', async () => {
  const { args, calls } = harness({ batches: [[]] });
  await assert.rejects(baseline(args), /base-sha.*screenshot_store\.yml/s);
  assert.equal(baseline.ATTEMPTS, calls.runs.length);
});

test('a store workflow GitHub does not know yet counts as no run', async () => {
  const { args } = harness({ unregistered: true });
  await assert.rejects(baseline(args), /No screenshot baseline/);
});

test('a merge group compares with the master commit it was built on', async () => {
  const payload = { merge_group: { base_ref: 'refs/heads/master', head_sha: 'group-sha' } };
  const { args, calls, outputs } = harness({ payload, sha: 'group-sha' });
  assert.equal(42, await baseline(args));
  assert.equal('master...group-sha', calls.compares[0].basehead);
  assert.equal('base-sha', outputs.base);
});

test('a push compares with its own commit', async () => {
  const { args, outputs } = harness({ payload: {}, sha: 'base-sha' });
  assert.equal(42, await baseline(args));
  assert.equal('base-sha', outputs.base);
});

test('the check downloads only the run the script found', () => {
  const wait = step(ci, 'Find the base commit\'s screenshot baseline');
  assert.match(wait, /require\('\.\/\.github\/screenshot_baseline\.cjs'\)/);
  const download = step(ci, 'Download the screenshot baseline');
  assert.match(download, /run-id: \$\{\{ steps\.baseline\.outputs\.run-id \}\}/);
  assert.match(download, /name: screenshot-baseline\n/);
  assert.doesNotMatch(download, /continue-on-error/);
  const compare = step(ci, 'Compare the screenshots with the baseline');
  assert.match(compare, /ANKIQUEST_SCREENSHOTS_BASELINE/);
  assert.ok(ci.indexOf('Download the screenshot baseline') < ci.indexOf('Compare the screenshots with the baseline'));
});

test('only master pushes and dispatches store a baseline', () => {
  assert.match(store, /on:\n  push:\n    branches:\n      - master\n/);
  assert.doesNotMatch(store, /pull_request/);
  const upload = step(store, 'Upload the baseline');
  assert.match(upload, /name: screenshot-baseline\n/);
  assert.match(upload, /if-no-files-found: error/);
});
