# herdr-minimap

A [herdr](https://herdr.dev) plugin for a [firstmate](https://github.com/kunchenguid/firstmate) fleet: a nav column
that stands in for herdr's sidebar (every space and agent to jump to, then the first mate, its crew and their agents
fanned out like a chart), a one-line version for herdr's tab bar, and under the column a pixel bonsai that grows with
your coding agents’ token usage. To run the tree on its own or customize a variety, see
[Pixel Bonsai](https://github.com/KrishRVH/pixel-bonsai).

It reads herdr's live snapshot, firstmate's `state/<id>.meta` and `.status` under `$FM_HOME` (default `~/dev`),
and Claude Code subagent transcripts. Pixel Bonsai counts usage across supported harnesses and custom usage events.
The plugin manages its panes and focus, and the tree stores its garden under `$XDG_STATE_HOME/qd`.

## Install

```sh
git clone https://github.com/KrishRVH/herdr-minimap.git
herdr plugin link herdr-minimap
```

Bind its actions in herdr's config (`toggle` for the nav, `deck` for Captain's Deck in its own space) and, for
the tab bar, add a command entry running `minimap.py --line`.

Python 3.9 or later, standard library only.

## Bonsai pane

The plugin ships the standalone tree as a Python zipapp, so a plain clone includes the tree.
Both the plugin and the standalone command use the same token history and garden. The plugin keeps its
day or lifetime view preference in the usual Herdr plugin state directory.

The archive contains the Python sources from [pixel-bonsai at c1dd3bd](https://github.com/KrishRVH/pixel-bonsai/tree/c1dd3bde28ada18339839dfd7f924885e10f8778).
To rebuild it from a sibling checkout at the desired commit, run this from the minimap directory:

```sh
git -C ../pixel-bonsai archive --format=zip HEAD -- LICENSE ':(top,glob)*.py' > vendor/pixel-bonsai.pyz
```

## Tests

```sh
python3 tests/herdr-minimap.test.py
```
