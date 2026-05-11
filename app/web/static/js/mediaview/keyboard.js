// ─── mediaview/keyboard.js ─────────────────────────────────────────────────
// Window keydown listener active while the MediaView modal is mounted:
//   Space      → toggle play/pause (preventDefault to kill scroll)
//   ArrowLeft  → seek -5 s, clamp at 0
//   ArrowRight → seek +5 s, clamp at duration
// Ignored when the focused element is INPUT / TEXTAREA / SELECT /
// contenteditable. The shell calls install/uninstall on
// mount/unmount so the listener never leaks across modals.
//
// SKELETON — task #6 fills this in.

export function installMediaViewKeyboard(/* videoEl */){
  return () => {};  // teardown: no-op until task #6 lands.
}
