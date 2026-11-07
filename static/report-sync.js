/* ReportSync — keeps the displayed report consistent with the latest edits.
 *
 * Rules:
 *  - invalidate() is called on EVERY edit: the previous report is dropped at once
 *    (so exports/Continue can't use stale data) and a rebuild is scheduled.
 *  - Each invalidate() bumps a sequence number; a response is applied only if no
 *    newer edit happened while it was in flight, so stale responses never win.
 *
 * Works in the browser (window.FixItReportSync) and in Node (module.exports) for tests.
 */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.FixItReportSync = api;
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  class ReportSync {
    constructor({ request, onChange = () => {}, delayMs = 250,
                  // Wrapped so the browser's timers are never called with `this` set to
                  // this object (window.setTimeout throws "Illegal invocation" otherwise).
                  setTimer = (fn, ms) => setTimeout(fn, ms),
                  clearTimer = (id) => clearTimeout(id) }) {
      if (typeof request !== "function") throw new TypeError("request must be a function");
      this.request = request;
      this.onChange = onChange;
      this.delayMs = delayMs;
      this.setTimer = setTimer;
      this.clearTimer = clearTimer;
      this.seq = 0;
      this.timer = null;
      this.report = null;
      this.error = null;
      this.pending = false;
    }

    /** True only when a report exists that reflects the latest edits. */
    get ready() {
      return this.report !== null && !this.pending && this.error === null;
    }

    snapshot() {
      return { report: this.report, error: this.error, pending: this.pending, ready: this.ready };
    }

    /** Drop the current report now; rebuild after a short debounce (or at once). */
    invalidate({ immediate = false } = {}) {
      this.seq += 1;
      this.report = null;
      this.error = null;
      this.pending = true;
      this._cancelTimer();
      this.onChange(this.snapshot());
      if (immediate) return this._run(this.seq);
      this.timer = this.setTimer(() => { this.timer = null; this._run(this.seq); }, this.delayMs);
      return null;
    }

    /** Forget everything (e.g. a new photo); in-flight responses are discarded. */
    reset() {
      this.seq += 1;
      this._cancelTimer();
      this.report = null;
      this.error = null;
      this.pending = false;
      this.onChange(this.snapshot());
    }

    _cancelTimer() {
      if (this.timer !== null) {
        this.clearTimer(this.timer);
        this.timer = null;
      }
    }

    async _run(seq) {
      if (seq !== this.seq) return false;
      let report = null;
      let error = null;
      try {
        report = await this.request();
      } catch (e) {
        error = (e && e.message) || String(e);
      }
      if (seq !== this.seq) return false; // a newer edit happened — discard
      this.report = error === null ? report : null;
      this.error = error;
      this.pending = false;
      this.onChange(this.snapshot());
      return true;
    }
  }

  return { ReportSync };
});
