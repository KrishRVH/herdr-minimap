# herdr-minimap

A [herdr](https://herdr.dev) plugin for a [firstmate](https://github.com/kunchenguid/firstmate) fleet: a nav column
that stands in for herdr's sidebar (every space and agent to jump to, then the first mate, its crew and their agents
fanned out like a chart), a one-line version for herdr's tab bar, and under the column a pixel bonsai that grows with
your Claude Code token usage. The bonsai comes in three varieties (sakura, Japanese maple, Japanese black pine), each
with its own day tree and lifetime tree, through twenty named stages.

It reads herdr's live snapshot, firstmate's `state/<id>.meta` and `.status` under `$FM_HOME` (default `~/dev`),
and Claude Code's transcripts (`~/.claude*/projects`). It writes only its own panes, focus and its state under
`$XDG_STATE_HOME/qd`.

## Install

```sh
git clone https://github.com/KrishRVH/herdr-minimap.git
herdr plugin link herdr-minimap
```

Bind its actions in herdr's config (`toggle` for the nav, `deck` for Captain's Deck in its own space) and, for
the tab bar, add a command entry running `minimap.py --line`.

Python 3.9 or later, standard library only.

## Tests

```sh
python3 tests/herdr-minimap.test.py
```
