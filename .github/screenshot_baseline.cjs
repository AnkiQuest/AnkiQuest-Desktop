// SPDX-License-Identifier: AGPL-3.0-or-later
// Finds the screenshot baseline the "Screenshots" check compares with: the one
// screenshot_store.yml stored for the exact base commit, from a master push or a
// dispatch, never a pull request's. It waits while that run is still drawing.

const WORKFLOW = "screenshot_store.yml";
const ARTIFACT = "screenshot-baseline";
const TRUSTED_EVENTS = ["push", "workflow_dispatch"];
const NOT_FOUND = 404;
const RETRY_MS = 30_000;
// A store run takes a few minutes; 30 minutes covers a queue of them.
const ATTEMPTS = 60;
const WAIT_MINUTES = (ATTEMPTS * RETRY_MS) / 60_000;

// The base commit: a pull request's merge commit's first parent, the master
// commit a merge group was built on, or the pushed commit itself.
async function baseCommit({ github, context }) {
    // The event's base.sha can lag the branch; the merge commit's first parent is what was merged into.
    if (context.payload.pull_request) {
        const {
            data: { parents },
        } = await github.rest.repos.getCommit({ ...context.repo, ref: context.sha });
        return parents[0].sha;
    }

    // A group's parent can be an earlier queue group, which has no baseline.
    const group = context.payload.merge_group;
    if (group) {
        const ref = group.base_ref.replace(/^refs\/heads\//, "");
        const {
            data: { merge_base_commit: mergeBase },
        } = await github.rest.repos.compareCommitsWithBasehead({
            ...context.repo,
            basehead: `${ref}...${group.head_sha}`,
            per_page: 1,
        });
        return mergeBase.sha;
    }
    return context.sha;
}

// The store runs of `sha`; none while GitHub does not know the workflow yet.
async function runsAt({ github, context, sha }) {
    try {
        // No status filter: status=success can omit a finished run.
        const {
            data: { workflow_runs: runs },
        } = await github.rest.actions.listWorkflowRuns({
            ...context.repo,
            workflow_id: WORKFLOW,
            head_sha: sha,
            per_page: 100,
        });
        return runs;
    } catch (error) {
        if (error.status === NOT_FOUND) {
            return [];
        }
        throw error;
    }
}

// The id of a finished, trusted store run of `sha` whose baseline has not expired.
async function storedRun({ github, context, sha }) {
    for (const run of await runsAt({ github, context, sha })) {
        const trusted = TRUSTED_EVENTS.includes(run.event);
        if (run.head_sha !== sha || !trusted || run.status !== "completed" || run.conclusion !== "success") {
            continue;
        }
        const {
            data: { artifacts },
        } = await github.rest.actions.listWorkflowRunArtifacts({ ...context.repo, run_id: run.id, per_page: 100 });
        if (artifacts.some(artifact => artifact.name === ARTIFACT && !artifact.expired)) {
            return run.id;
        }
    }
    return null;
}

module.exports = async function screenshotBaseline({
    github,
    context,
    core,
    sleep = delay => new Promise(resolve => setTimeout(resolve, delay)),
}) {
    const sha = await baseCommit({ github, context });
    core.setOutput("base", sha);

    // Only the store run of this exact commit is used, never another commit's.
    for (let attempt = 0; attempt < ATTEMPTS; attempt++) {
        const id = await storedRun({ github, context, sha });
        if (id !== null) {
            core.info(`Using the screenshot baseline of ${sha}: run ${id}`);
            core.setOutput("run-id", String(id));
            return id;
        }
        core.info(`Waiting for the screenshot baseline of ${sha}`);
        await sleep(RETRY_MS);
    }
    throw new Error(
        `No screenshot baseline for ${sha} after ${WAIT_MINUTES} minutes. ` +
            `Run ${WORKFLOW} (Run workflow) on a branch at that commit, then rerun this check.`,
    );
};

module.exports.ATTEMPTS = ATTEMPTS;
