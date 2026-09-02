// ─── mediaview/_live-detect-tick-status.js ─────────────────────────────────
// The two pure verdicts the poll loop reaches about a tick: how long the
// current request has been in flight (and whether that means "stand down"),
// and what an ok=false response actually said. Lifted verbatim out of
// live-detect-poll.js so both can be tested without a session or a socket.
//
// Deliberately constant-free: the in-flight ceiling stays declared in
// live-detect.js next to the stall watchdog that shares it, and is passed
// in here. These functions decide nothing about timing on their own.

/**
 * Age of the in-flight request, or 0 when none is out.
 *
 * @param {number|undefined} inflightSince epoch ms the request went out
 * @param {number} now epoch ms
 * @returns {number} age in ms, 0 when nothing is in flight
 */
export function _inflightAgeMs(inflightSince, now) {
  return inflightSince ? now - inflightSince : 0;
}

/**
 * P7 · the in-flight contract. A request younger than the ceiling is never
 * aborted: Flask cannot cancel a request — the handler runs all of its
 * inferences to completion whatever we do to the socket — so aborting hides
 * the cost from the UI without removing it from the box, and the backend's
 * single slot then answers the replacement with 429 busy anyway. Wait
 * instead of racing.
 *
 * True means "a request is genuinely out and still young": the caller must
 * stand down rather than issue a second one.
 *
 * @param {number} inflightMs age of the in-flight request (0 when none)
 * @param {number} ceilingMs _INFLIGHT_ABORT_CEILING_MS
 * @returns {boolean}
 */
export function _isInflightPending(inflightMs, ceilingMs) {
  return inflightMs > 0 && inflightMs < ceilingMs;
}

/**
 * B23' · read an ok=false response. Status first so screenshots of the
 * fold's "Letzter Tick" banner stay greppable, and the message kept
 * separately so the two 429 codes can paint their own explanation —
 * leaving either of them wordless is what let the stall watchdog's guess
 * stand in for the real reason.
 *
 * @param {number|string|undefined} status HTTP status of the response
 * @param {object|null} data parsed body, null when it did not parse
 * @returns {{code: string|number, msg: string, text: string}}
 */
export function _classifyTickFailure(status, data) {
  const code = data?.code || status || '?';
  const msg = data?.error || data?.message || '';
  return { code, msg, text: msg ? `${code} · ${msg}` : String(code) };
}
