# How detection works

Finding songs in a rehearsal recording is not a silence-detection problem. The gaps
between songs are full of talking, tuning and counting; and songs themselves contain quiet
intros and breakdowns. Two weak signals are used together, because each one fails where
the other holds.

## Level classes

`detect.calibrate` separates the recording into three classes rather than two: room
silence, talking, and playing. It runs Otsu's method twice — once to strip the silence,
then again on what remains to split talking from playing.

Song *ends* come from this: the level falls back into the talking class and stays there
past `min_gap_seconds`. That is what handles a pause which is not silent.

**Calibration pools every take in a rehearsal**, and this is load-bearing. Per-file
calibration fails in both directions, as observed on real recordings:

- A take containing only music has no talking to find, so the split lands inside the
  *music*, dividing it into loud and quiet halves.
- A silent 2 GB rollover continuation has no music at all, so the split lands inside the
  noise floor and invents a music class at −54 dBFS.

Otsu always returns a split, even on unimodal noise. `Calibration.reliable` reports when
the classes sit too close together to trust. Expect it on rehearsals recorded start-stop
per song, where hardly any talking was captured.

## Count-in clicks

`detect.count_ins` looks for the drummer's four drumstick clicks: evenly spaced transients
in a high-passed onset envelope, picked against a **local** rolling baseline. A global
threshold misses count-ins during quiet passages — in a 93-minute file dominated by loud
music, a global gate found 260 onsets in total and only 2 real count-ins.

Spacing alone is not enough. Four evenly spaced transients also describes a drummer
playing time, and a naive detector reported nine overlapping "count-ins" inside one
continuous groove.

What makes it a count-in is the level context around it: **quiet before the clicks, a
sustained rise after the downbeat.** That test must be *relative* (`rise_db`), never a
comparison against the absolute session threshold. Gain and band volume vary enough
between takes that an absolute test rejects real count-ins — one verified by hand was
rejected because that take's music sat at −35 dB while the session split was −32.7 dB.

The lead window asks whether it was quiet at *any* point before the clicks, using a low
percentile (`lead_percentile`) rather than a median. A median fails on restarts, where the
aborted take still occupies part of the window. Narrowing the window instead was tried and
traded away real detections.

There is also a ~85 ms room reflection after each click, which a peak-picker will
double-count unless the minimum separation exceeds it.

## Putting them together

Count-ins do two jobs:

- **Place the start precisely.** A level gate alone put one song's start at 1:07; the
  count-in put it at 0:11. The gate had missed a 56-second quiet intro.
- **Split merged regions.** Two songs with a short gap form one loud region; a count-in
  inside it marks the boundary.

Genuine restarts survive as short, low-confidence segments. That is deliberate — an
aborted take is real information, not noise. Two count-ins closer together than
`merge_beats` are one 8-click count and get merged, keeping the earlier: a count-in is
four clicks, so a longer run means the band was already playing, and keeping the later
group would start the song after its first bar.

## Accuracy

Validated against a rehearsal cut by hand into 18 songs: the detector finds 20. The
extras are a flagged 11-second restart and one uncertain split, both visible as
low-confidence in the review list.

The known weakness is that `level`-origin segments start where the band got loud, so they
run late by however long the intro was. Key `1` plays the audio before the start and `t`
corrects it.

## Cost

The whole inbox — around five hours of audio — analyses in about seven seconds. Envelopes
are computed in one streaming pass per take, and nothing is written.
