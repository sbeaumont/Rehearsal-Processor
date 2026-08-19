# Interface decisions

Most of these look arbitrary until you know what went wrong without them. They are
recorded so they do not get "simplified" back.

## Review is two separate steps

A single keypress picks an action; naming is its own mode with its own prompt.

Do not merge these by treating "any other key" as the start of a title. Real song titles
begin with command letters — `Sex on Fire`, `Somewhere Only We Know`, `Summer of '69`,
`Smoke on the Water`, `Stil in mij` all start with `s`, which is skip. When the steps were
merged, typing a title silently skipped the segment instead.

The action step reads one raw keypress rather than a line. `input()` waits for Enter,
which reads as a dead prompt — you press `1`, nothing happens, you press Enter, and the
empty line does something else entirely.

Titles complete with tab against the songlist. An unrecognised title is kept verbatim,
which is what improvisations need.

## Previews never play by themselves

They wait for a keypress. Do not "helpfully" autoplay on arrival at a segment.

Any key stops playback, and what happens to that key depends on which it is:

- `1`–`5` **only** stop. Feeding them back restarts the very snippet just stopped, because
  the natural key to press during a preview is the one that started it.
- Everything else stops **and** acts. Swallowing them strands you at the action prompt
  believing you are somewhere else: Enter reads as "name this", so the next thing typed is
  a title, and its first letter lands on the menu.

## One list per rehearsal date, never per take

A night recorded start-stop is nine takes holding one song each. Reviewing take by take
shows the first take's two segments and hides the rest, and each sitting restarts the
numbering. When a date has several takes, a wall-clock column says which take a segment
came from, since every take's timeline starts at zero.

## Encoding is explicit

`q` quits and encodes nothing; `e` encodes. Nothing about leaving the review may start
writing audio on its own.

Export happens in two stages. Everything is encoded into the local work directory first;
copying to the archive happens only after an explicit confirmation. Nothing reaches remote
storage unconfirmed, and a broken or unmounted archive costs you nothing — the finished
mp3s are already on local disk.

## Progress survives

Titles and start corrections are written to `session.json` in the work directory after
every change, so quitting or interrupting costs nothing. The next run reports how many
were resumed and jumps to the first unnamed segment.

Entries are keyed by the **detected** segment start, never the corrected one. Keying by
the corrected value would orphan the entry the moment detection ran again.

## Merging is a mark, not a deletion

`m` folds a segment into the one above when detection split one song in two. The absorbed
segment is not removed from the list — it is marked, hidden from the rows, and skipped by
navigation. Its detected start still exists, which is what lets the merge persist: it is
written to `session.json` under its own key, and detection producing the same two segments
next run re-applies it.

Deleting the row instead would shift every index after it, and the entry would have no key
to be stored under. The segment above takes its end from the last segment absorbed into it
and keeps its own start, origin and BPM, because its start did not change.

Merging refuses across takes. Two takes are two files with independent timelines, so a
merged span would be meaningless.

Names live in a dict keyed by segment index, so moving back shows and replaces the title
already given. Export order follows segment order however you navigated.

## Times match the audio editor

Positions are shown as `h:mm:ss.xx`, the same format Fission displays, so a number can be
read off one and typed into the other without conversion. Durations omit the hours field;
they are never that long.

`t` accepts the same forms plus shorthand — `12.34`, `2:03.45`, `1:02:03.45`. A `.` is
*not* accepted as a field separator: it would collide with the fractional seconds, since
`12.34` cannot mean both 12.34 seconds and 12 minutes 34 seconds.

## Filenames

Playing order, then the title, then a repeat suffix from the second take onwards:
`01 Creep.mp3`, `02 Vertigo.mp3`, `03 Creep 2.mp3`. Order is zero-padded so a plain
lexical listing sorts correctly.

`already_filed()` reads the target folder first, so both the order number and the repeat
counts continue from what is there. Filing into a folder holding `03 Creep 2.mp3` starts at
`04`, and another Creep becomes `Creep 3`. Without this, a second sitting overwrites the
first.

## Format

Loudness normalisation (EBU R128) matters far more than bitrate here: sources peak around
−17 dBFS. mp3 V7 is about 100 kbps, roughly 7% of the WAV size, and was chosen by
listening to a bass part at four settings. These are copies for learning parts, not
masters.
