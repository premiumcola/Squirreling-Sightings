// ─── mediaview/fine-analysis-fold.js ───────────────────────────────────────
// Permanent strip BELOW the panel content. Header: chevron + terminal
// icon + "Fein-Analyse · Trace-Log" + tiny subtitle (capture · coral ·
// verdict · matrix · armed · telegram · schedule · final). Closed by
// default; open state renders the decision-trace lines on a darker
// monospace surface (#050810) with PASS=success, REJECTED=warning,
// no-detection=danger. Persists open/closed in
// localStorage["tamspy.mediaview.fineFold"].
//
// SKELETON — task #6 fills this in.

export const FINE_FOLD_STORAGE_KEY = 'tamspy.mediaview.fineFold';

export function renderFineAnalysisFold(/* host, traceLines */){}
