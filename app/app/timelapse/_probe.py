"""Post-encode validation of the written MP4.

Kept as a mixin rather than plain functions because the encode tests
monkeypatch ``TimelapseBuilder._ffprobe_validate`` to skip the real
ffprobe call, which only works while it is an attribute of the class.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from ._consts import log


class ProbeMixin:
    """ffprobe validation + the rejection sidecar."""

    @staticmethod
    @staticmethod
    def _ffprobe_validate(out_path: Path) -> tuple[bool, str, dict]:
        """Run ffprobe against ``out_path`` and check three invariants:

          • ``nb_streams >= 1`` — at least one video stream landed in
            the container (catches zero-frame writer crashes that leave
            a tiny mp4 header behind).
          • ``format.duration > 0.5`` — the file actually carries
            timeline data (catches "encode wrote header, then died").
          • first-video-stream ``nb_frames > 1`` — guards against the
            single-frame fallback that ffmpeg silently produces when the
            concat list has exactly one entry.

        Returns ``(ok, reason, info)`` where ``info`` is the parsed
        ffprobe JSON (or ``{}`` on probe failure). On the failure path
        the caller should delete the file and write the diag sidecar."""
        try:
            import json as _json

            cmd = [
                "ffprobe",
                "-v",
                "error",
                "-print_format",
                "json",
                "-show_format",
                "-show_streams",
                "-count_packets",  # populates nb_read_packets even when nb_frames is missing
                str(out_path),
            ]
            r = subprocess.run(cmd, capture_output=True, timeout=15)
            if r.returncode != 0:
                return (
                    False,
                    f"ffprobe rc={r.returncode}: {r.stderr.decode(errors='replace')[-200:]}",
                    {},
                )
            info = _json.loads(r.stdout.decode(errors="replace") or "{}")
        except Exception as e:
            return (False, f"ffprobe exception: {e}", {})
        streams = info.get("streams") or []
        if len(streams) < 1:
            return (False, "nb_streams=0", info)
        # Find the first video stream — audio streams (or future
        # data streams) shouldn't satisfy the frame-count check.
        v_stream = next(
            (s for s in streams if (s.get("codec_type") == "video")),
            None,
        )
        if v_stream is None:
            return (False, "no video stream", info)
        try:
            duration = float((info.get("format") or {}).get("duration") or 0.0)
        except (TypeError, ValueError):
            duration = 0.0
        if duration <= 0.5:
            return (False, f"duration={duration:.3f}s ≤ 0.5s", info)
        # nb_frames is sometimes "N/A" for variable-fps mp4. Fall back
        # to packet count (filled by -count_packets above) — for the
        # short timelapse outputs we ship 1 packet ≈ 1 frame.
        nb = v_stream.get("nb_frames")
        try:
            nb_int = int(nb) if nb and nb != "N/A" else 0
        except (TypeError, ValueError):
            nb_int = 0
        if nb_int <= 1:
            pkt = v_stream.get("nb_read_packets")
            try:
                pkt_int = int(pkt) if pkt and pkt != "N/A" else 0
            except (TypeError, ValueError):
                pkt_int = 0
            nb_int = max(nb_int, pkt_int)
        if nb_int <= 1:
            return (False, f"nb_frames={nb_int} ≤ 1", info)
        return (True, "", info)

    @staticmethod
    def _write_encode_diag(out_path: Path, reason: str, info: dict, encode_args: dict) -> None:
        """Write a sibling ``<basename>.encode-diag.txt`` next to the
        bad MP4 with the rejection reason, encode args, and (when the
        probe succeeded enough to parse JSON) the ffprobe summary.
        Stays plain text so an operator inspecting via SSH doesn't need
        a JSON viewer. Best-effort — write errors are swallowed."""
        diag_path = out_path.with_suffix(out_path.suffix + ".encode-diag.txt")
        lines = [
            "Squirreling · Sightings timelapse · encode validation failed",
            f"  output       : {out_path.name}",
            f"  reason       : {reason}",
            "  encode args  :",
        ]
        for k, v in (encode_args or {}).items():
            lines.append(f"    {k} = {v}")
        if info:
            lines.append("  ffprobe      :")
            fmt = info.get("format") or {}
            lines.append(f"    duration       = {fmt.get('duration')!r}")
            lines.append(f"    nb_streams     = {fmt.get('nb_streams')!r}")
            lines.append(f"    size           = {fmt.get('size')!r}")
            for i, s in enumerate(info.get("streams") or []):
                lines.append(f"    stream[{i}].codec_type     = {s.get('codec_type')!r}")
                lines.append(f"    stream[{i}].codec_name     = {s.get('codec_name')!r}")
                lines.append(f"    stream[{i}].nb_frames      = {s.get('nb_frames')!r}")
                lines.append(f"    stream[{i}].nb_read_packets= {s.get('nb_read_packets')!r}")
        try:
            diag_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        except Exception as e:
            log.debug("[timelapse] encode-diag write failed for %s: %s", diag_path.name, e)
