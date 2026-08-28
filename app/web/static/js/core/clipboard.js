// ─── core/clipboard.js ─────────────────────────────────────────────────────
// One clipboard write for the whole app.
//
// Two constraints make this less trivial than navigator.clipboard suggests:
//
//  1. `navigator.clipboard` only exists in a SECURE CONTEXT. This app is
//     served over plain http:// on the LAN (http://192.0.2.10:8099), so on
//     the desktop browser the API is simply absent and the textarea +
//     execCommand path is the ONLY one that runs. It is the main path here,
//     not a legacy curiosity.
//  2. iOS Safari grants clipboard access only inside the original user
//     gesture. Any `await` before the write loses it. So callers must invoke
//     this synchronously from the click handler, and this function must not
//     await anything before its first write attempt.
//
// NOTE · a second, older copy of the fallback still lives in
// mediaview/live-detect-debug/_copy-bar.js (_execCopyFallback). That module
// is being edited elsewhere right now; it should import from here once that
// work lands, at which point its local copy goes away.

// Spawn an off-screen textarea, select it, execCommand('copy'), remove it.
// Requires a same-tick user gesture, which a click handler provides.
export function execCopyFallback(text) {
  const ta = document.createElement('textarea');
  ta.value = text;
  ta.setAttribute('readonly', '');
  ta.style.cssText = 'position:fixed;top:-9999px;left:0;opacity:0';
  document.body.appendChild(ta);
  ta.select();
  ta.setSelectionRange(0, text.length);
  let ok = false;
  try {
    ok = document.execCommand('copy');
  } catch {
    ok = false;
  }
  document.body.removeChild(ta);
  return ok;
}

// Copy `text`, calling onOk/onFail when the outcome is known. Returns true
// if a write was dispatched — with the async clipboard API the real result
// arrives via the callbacks, so do not treat the return value as success.
export function copyText(text, { onOk, onFail } = {}) {
  const ok = () => onOk?.();
  const fail = () => onFail?.();
  try {
    if (navigator.clipboard?.writeText) {
      navigator.clipboard.writeText(text).then(ok, () => {
        if (execCopyFallback(text)) ok();
        else fail();
      });
      return true;
    }
  } catch {
    // Secure-context check threw — fall through to the textarea path.
  }
  const done = execCopyFallback(text);
  if (done) ok();
  else fail();
  return done;
}
