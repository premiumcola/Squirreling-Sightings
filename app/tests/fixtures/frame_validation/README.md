# Frame validation fixtures

Ground-truth JPEGs for `test_frame_validation_fixtures.py` — the
parametrised regression suite for `app.frame_helpers.is_valid_frame`.

## Layout

```
fixtures/frame_validation/
├── corrupt/      # frames the validator MUST reject
│   └── *.jpg
└── clean/        # frames the validator MUST pass
    └── *.jpg
```

Each JPEG is hand-classified. Drop new frames into the right folder
and the parametrised test will pick them up automatically — no
glue code needed. The test runs the picker first
(`pick_profile_from_baseline([img])`) so the validator is called
with the same profile the production capture loop would have
chosen, mirroring the real call path.

## Adding new fixtures

1. Pull a frame from `<storage>/weather/<cam_id>/sunset_timelapse/_test_*_raw/`
   (test-mode raw frames) or from any `_rejected/<reason>/slot*.jpg`
   path under the same tree.
2. Verify by eye whether it is a corruption case or a genuine scene.
3. Drop it into `corrupt/` or `clean/`.
4. Run `pytest -q app/tests/test_frame_validation_fixtures.py` —
   any regression in `is_valid_frame` will fail this fixture next.

## Privacy note

These are real camera frames. The repo is public; the data owner
(repo maintainer) has accepted that these night IR frames showing
their own property are committed here. If a future fixture would
include identifiable people or readable plates, drop it.

## Why the corrupt/ folder may be empty

Earlier check-in copied "corrupt" frames from the latest test run
under `_test_022610_2026-05-09_sunset_raw/`, but those slot numbers
no longer matched corrupt frames — by the time the run executed,
the validator improvements had already prevented the bottom-strip /
mid-band corruption from passing validation. The frames at those
slot indices were in fact backfill copies of clean references.

The maintainer is expected to drop in real corrupt fixtures from
their own debugging sessions; the test suite handles an empty
`corrupt/` directory gracefully (pytest collects 0 cases).
