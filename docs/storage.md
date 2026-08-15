# Storage

Where files live, and what the storage will not tolerate.

## Layout

**Inbox** — local disk. Recordings pulled off the card, plus a `work/` subdirectory of
staged output and resumable progress. It accumulates old and already-processed files, so
nothing may treat it as a work queue.

Recorder files are `YYMMDD_HHMMSS[_NNN]_Mic.wav`, 48 kHz stereo Float32, either loose or
one folder per take. `_002_` and up are 2 GB rollover continuations of the *same*
recording; `audio.Take` joins them into one timeline, because songs straddle the boundary.

**Archive** — one folder per rehearsal, `YYYY MM DD/`, holding the finished mp3s. May be
on network or cloud storage.

Sources can be deleted once a rehearsal is archived. That is a real decision: the mp3s are
~100 kbps, so a different cut is no longer possible afterwards.

**All intermediates stay local.** Encoding, previews and progress files are written under
the inbox, never to the archive. Working files on a synced volume mean constant sync
traffic, and on a slow mount, constant waiting.

## When the archive is a mounted cloud volume

This project's archive sits on a WebDAV-backed mount (Mountain Duck over a Stack account).
Several ordinary filesystem operations do not behave, and finding out cost real data.

### Purely numeric folder names are dangerous

A folder called `20260420.` never syncs. A folder called `xxx1234123.` is fine. The
difference is that `20260420.` reads as a numeric literal, so something in the chain
type-guesses the name and coerces it — `Number("20260420.")` is `20260420` — and the dot
survives on one side only. Local and remote names then disagree permanently, so
reconciliation can never converge.

Worse, a *rename* in that state resolves the delete against the remote name and creates
the replacement under a name the backend will not keep: the folder arrives empty and the
contents land in the provider's trash. Eleven rehearsals were emptied this way, needing a
provider-side restore. No sequence of renames through the mount ever fixed it.

The escape is to keep folder names unambiguously strings: `2026 05 18`, built by
`archive_folder()`. Do not "tidy" them back to digits. `safe()` strips trailing dots and
spaces from titles for the same reason.

### Do not rename directories on the mount

Even without the numeric trap, a directory rename is delete-plus-create rather than a
rename. To change a name, create the new folder and copy the contents in.

### The execute bit is not preserved

Files written to the mount come back `-rw-------`, and `chmod +x` is silently reverted.
This breaks shell scripts and every console script in a virtualenv created there. The
broken modes survive a copy to local disk, so a venv built on the mount must be deleted and
rebuilt rather than repaired.

This is why the project itself lives on local disk.

Taken together: treat such a mount as write-once storage that accepts new files and
nothing else.

## Songlist

The songlist path should name a **single file** — a plain list, one title per line, or a
markdown table with a `Nummer` column. A directory works, but merges every list it finds;
pointing at one that also held older repertoire markdown produced 64 titles including
other bands and stale arrangements instead of the current 52.

Archive filenames need not match songlist spellings (`Sweet Child o' Mine` versus
`Sweet Child of Mine`), which is why title matching is fuzzy and a match wins on spelling
and case.
