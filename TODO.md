# To do

## Set a segment's end

Review has `t` for the start and nothing for the end, because ends come from the level
gate and were the reliable half. On phone recordings they run late — one confirmed song
ended at 4:24 where the segment ended at 4:30.20. Harmless for relistening copies, so
this waits.

Worth deciding first whether ends drift *systematically* on a levelled recording, in
which case a threshold is the fix rather than a key. That needs a few more confirmed
endings.

## Split a segment

The counterpart to `m`. A segment running eight minutes is almost certainly two songs
that never got separated — a count-in the detector missed, or a gap shorter than
`min_gap_seconds`. Today there is no way to cut one in review; the only recourse is to
name it once and lose the boundary.

Needs a way to say where the cut goes. `t` already parses `h:mm:ss.xx`, so a split key
that takes a time and produces two segments from one would reuse it.

## Known false count-in

`New Recording 43` at 3:28.94, 60.6 BPM, click ratio 4.1 — confirmed by ear to be inside
the first song, not a start. It is the lowest-ratio mark in that file, and the only one
under 5.0 apart from a 5.0 at 33:19 whose status is unknown.

Not tuned out, deliberately: one confirmed example is not enough, and `CLAUDE.md` records
a narrowed lead window that fixed a fabricated restart and silently lost a genuine one.
Revisit with several sessions' worth of marks confirmed by ear.
