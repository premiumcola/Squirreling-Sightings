# Frame quality — what catches what

Order matches `app/app/frame_helpers/_validator.py::is_valid_frame`. Every check that doesn't reject falls through to the next. The chain runs against a single decoded BGR ndarray; profile thresholds come from a `FrameValidatorProfile` selected at capture time by `pick_profile_from_baseline` (DAY / TWILIGHT / NIGHT).

## 1. `null/empty` — decode produced no pixels or zero-size buffer. No threshold.

## 2. `too_small` — frame width < `_MIN_FRAME_W` or height < `_MIN_FRAME_H`. Both 80. Hard floor — pre-decoded broken JPEGs.

## 3. `too_dark(brightness=X)` — mean BGR < `profile.brightness_floor` (default 2.0). Genuine dead-of-night frames still pass; only a literally-black buffer hits this.

## 4. `too_bright(brightness=X)` — mean BGR > `profile.brightness_ceil` (default 253.0). Full-frame blown-out highlights, no scene info recoverable.

## 5. `pink_artifact(r,g,b)` — full-frame H.265 pink/magenta corruption. Triggers when red dominates by `profile.pink_full_ratio` (default 2.5) over both green and blue AND red mean > `pink_full_r_min` (default 160).

## 6. `partial_pink_qN(r,g,b)` — same chroma pattern over any single quadrant. Higher thresholds (`pink_quad_r_min` 180, `pink_quad_ratio` 3.0) because a smaller patch is easier to false-positive on. N ∈ {0..3} maps to top-left / top-right / bottom-left / bottom-right.

## 7. `patterned_magenta(area=X%)` — pixel-level magenta wedge: R ≥ 130 AND B ≥ 130 AND G ≤ 110 AND `min(R,B) - G ≥ 25`. Rejects when ≥ `profile.pattern_magenta_area_frac` of pixels (default 20 %) sit in that wedge. Catches textured H.265 corruption that the smooth-fill rule above misses.

## 8. `flat_gray_full_frame(mean=X,std=Y)` — whole-frame mid-grey decoder hickup. Mean ∈ [115, 145] AND grayscale std < 10. Has its own reason head so the rejected/ folder splits this case from `dead_area`.

## 9. `horizontal_anomaly_band` / `bottom_strip_*` — H.265 NAL/slice loss producing a contiguous run of corrupted rows. Two stages: row-delta (scrambled-block macroblock smear) and chroma (saturated non-warm hue leak). Either fires reject. Bottom-25 % bands keep the legacy `bottom_strip_*` head so existing log greps survive.

## 10. `no_detail(std=X)` — grayscale std below `profile.flat_gray_std_floor` (DAY 2.0 / TWILIGHT 1.2 / NIGHT 0.8). Catches a truly flat single-colour frame after the corruption gates above have all passed.

## 11. `grey_uniform(std_sum=X)` / `grey_midband(...)` — per-channel std sum below `_GREY_CHANNEL_STD_SUM` (8.0) OR mean in [115, 140] with total std below `profile.grey_midband_total_std`. The specific "Reolink substream returned uniform mid-grey" hickup.

## 12. `dead_area(D/T=X%)` — tile-based scoring on an 8 × 5 grid. A tile is dead when its blurred std falls below `_TILE_DEAD_BLURRED_STD_FLOOR` (3.0), or it sits in the mid-grey luma band with low blurred std, or it sits in the mid-grey band with chroma std < `_TILE_CHROMA_STD_FLOOR` (4.0). Rejects when dead-fraction > `profile.tile_dead_fraction` (DAY 0.35 / TWILIGHT 0.55 / NIGHT 0.85).

## 13. `macroblock_anomaly(area=X tiles)` — localised H.264 slice-loss corruption: ≥ 3 tiles with chroma spread > 85 AND Laplacian energy > 4 × the local 5 × 5 median, forming a cluster with bbox-fill > 0.5. Two-signal gate so smooth high-chroma regions (warm lamps, sunset sky) don't false-positive.

## 14. `bright_outlier_dark_scene(max=X,base=Y,dev=Z)` — new 2026-05. Reuses the 8 × 5 tile grid: brightest tile mean > 240 AND brightest-vs-darkest-third deviation > 100 AND overall frame mean < `profile.bright_outlier_frame_mean_max` (TWILIGHT/NIGHT 100, DAY 0 = disabled). Catches the saturated-grey corruption patch that no other detector sees (no chroma, no high-frequency texture, mostly-untouched frame). Transient — `grab_valid_frame` retries.

## 15. `split_left_dead` / `split_right_dead` / `split_top_dead` / `split_bottom_dead` — exactly one half of the frame is dead-grey while the other half carries real imagery. dead_area lands near 0.5 in this case and slips through; the explicit split detector catches it.

## 16. `grey_toned(luma=X,chroma_std=Y)` — frame-level fallback for blocky H.264 corruption. Luma in [100, 160] AND trimmed chroma std (drop top-10 % differences before std) below `profile.grey_toned_chroma_std_max` (default 8.0). Trimmed metric is robust to a small chroma island.

## 17. `colorbar(...)` — SMPTE test pattern detection. 9 sampled rows: each row's std < `profile.colorbar_per_row_std` (6.0) AND row-to-row mean std > `profile.colorbar_between_row_std` (35.0). Cheap last-resort check for IR-switch-mode test bars.

If every check passes the frame is `(True, "")`. Rejections fall into two retry classes: `transient` (grab_valid_frame retries within budget — corruption usually clears on the next decode) and `scene` (cap at 2 retries — empty terrace at midnight isn't going to magically grow detail). See `_TRANSIENT_REASONS` / `_SCENE_REASONS` at the bottom of `_validator.py`.
