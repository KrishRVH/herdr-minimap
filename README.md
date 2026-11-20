# herdr-minimap

A [herdr](https://herdr.dev) plugin for a [firstmate](https://github.com/kunchenguid/firstmate) fleet: a nav column
that stands in for herdr's sidebar (every space and agent to jump to, then the first mate, its crew and their agents
fanned out like a chart), a one-line version for herdr's tab bar, and under the column a pixel bonsai that grows with
your coding agents’ token usage. To run the tree on its own or customize a variety, see
[Pixel Bonsai](https://github.com/KrishRVH/pixel-bonsai).

It reads herdr's live snapshot, firstmate's `state/<id>.meta` and `.status` under `$FM_HOME` (default `~/dev`),
and Claude Code subagent transcripts, and manages only its own panes, focus and plugin state.

## Install

```sh
git clone https://github.com/KrishRVH/herdr-minimap.git
herdr plugin link herdr-minimap
```

Bind its actions in herdr's config (`toggle` for the nav, `deck` for Captain's Deck in its own space) and, for
the tab bar, add a command entry running `minimap.py --line`.

Python 3.9 or later, standard library only.

## Bonsai pane

The pane under the nav column runs the `pixel-bonsai` command, so install
[Pixel Bonsai](https://github.com/KrishRVH/pixel-bonsai) and put it on `PATH` (`~/.local/bin` and `~/go/bin`
are found too). Its keys, garden and usage sources are its own, and the pane shares the garden with any other
`pixel-bonsai` you run. Without it the pane says how to get it.

## Tests

```sh
python3 tests/herdr-minimap.test.py
```
