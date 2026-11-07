// Run with: node --test tests/js/*.test.js   (also executed by tests/test_frontend_js.py)
"use strict";
const { test } = require("node:test");
const assert = require("node:assert/strict");
const { ReportSync } = require("../../static/report-sync.js");

function deferred() {
  let resolve, reject;
  const promise = new Promise((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}

function harness(opts = {}) {
  const calls = [];
  const changes = [];
  const timers = [];
  const sync = new ReportSync({
    request: () => { const d = deferred(); calls.push(d); return d.promise; },
    onChange: (s) => changes.push(s),
    setTimer: (fn) => { timers.push(fn); return timers.length; },
    clearTimer: (id) => { if (id) timers[id - 1] = null; },
    ...opts,
  });
  const fireTimers = () => timers.splice(0).forEach((fn) => fn && fn());
  return { sync, calls, changes, fireTimers };
}

const tick = () => new Promise((r) => setImmediate(r));

test("an edit drops the previous report immediately and blocks exports", async () => {
  const { sync, calls } = harness();
  sync.invalidate({ immediate: true });
  calls[0].resolve({ text: "v1" });
  await tick();
  assert.equal(sync.ready, true);
  assert.equal(sync.report.text, "v1");

  sync.invalidate(); // user edits a field
  assert.equal(sync.report, null, "stale report must be cleared synchronously");
  assert.equal(sync.pending, true);
  assert.equal(sync.ready, false, "Continue/exports must be disabled while pending");
});

test("a slow stale response never overwrites a newer edit (out-of-order)", async () => {
  const { sync, calls } = harness();
  sync.invalidate({ immediate: true }); // request #1 (old edits)
  sync.invalidate({ immediate: true }); // request #2 (new edits)
  calls[1].resolve({ text: "new" });
  await tick();
  calls[0].resolve({ text: "old" });   // arrives late
  await tick();
  assert.equal(sync.report.text, "new");
  assert.equal(sync.ready, true);
});

test("a stale response arriving first leaves the report pending", async () => {
  const { sync, calls } = harness();
  sync.invalidate({ immediate: true });
  sync.invalidate({ immediate: true });
  calls[0].resolve({ text: "old" });
  await tick();
  assert.equal(sync.report, null);
  assert.equal(sync.pending, true);
  calls[1].resolve({ text: "new" });
  await tick();
  assert.equal(sync.report.text, "new");
});

test("stale errors are ignored; current errors block readiness", async () => {
  const { sync, calls } = harness();
  sync.invalidate({ immediate: true });
  sync.invalidate({ immediate: true });
  calls[0].reject(new Error("old failure"));
  await tick();
  assert.equal(sync.error, null);
  calls[1].reject(new Error("description: too short"));
  await tick();
  assert.equal(sync.error, "description: too short");
  assert.equal(sync.pending, false);
  assert.equal(sync.ready, false);
});

test("rapid typing is debounced into one request built from the latest state", async () => {
  const { sync, calls, fireTimers } = harness();
  sync.invalidate();
  sync.invalidate();
  sync.invalidate();
  assert.equal(calls.length, 0);
  fireTimers();
  assert.equal(calls.length, 1);
  calls[0].resolve({ text: "latest" });
  await tick();
  assert.equal(sync.report.text, "latest");
});

test("reset discards in-flight responses (e.g. a new photo)", async () => {
  const { sync, calls } = harness();
  sync.invalidate({ immediate: true });
  sync.reset();
  calls[0].resolve({ text: "for old photo" });
  await tick();
  assert.equal(sync.report, null);
  assert.equal(sync.pending, false);
});

test("default timers work when the host rejects method-style calls (browser behaviour)", async () => {
  // Browsers throw "Illegal invocation" if window.setTimeout is called with `this` set
  // to another object. Emulate that, then use ReportSync WITHOUT injected timers.
  const realSet = globalThis.setTimeout;
  const realClear = globalThis.clearTimeout;
  const strict = (real) => function (...args) {
    if (this !== undefined && this !== globalThis) throw new TypeError("Illegal invocation");
    return real(...args);
  };
  globalThis.setTimeout = strict(realSet);
  globalThis.clearTimeout = strict(realClear);
  try {
    let calls = 0;
    const sync = new ReportSync({ request: async () => { calls += 1; return { text: "ok" }; }, delayMs: 5 });
    assert.doesNotThrow(() => sync.invalidate());
    assert.doesNotThrow(() => sync.invalidate()); // exercises clearTimer too
    await new Promise((r) => realSet(r, 30));
    assert.equal(calls, 1);
    assert.equal(sync.ready, true);
  } finally {
    globalThis.setTimeout = realSet;
    globalThis.clearTimeout = realClear;
  }
});

test("onChange reports pending state so the UI can disable actions", async () => {
  const { sync, calls, changes } = harness();
  sync.invalidate({ immediate: true });
  assert.deepEqual(changes.at(-1), { report: null, error: null, pending: true, ready: false });
  calls[0].resolve({ text: "v1" });
  await tick();
  assert.equal(changes.at(-1).ready, true);
});
