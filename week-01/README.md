# Week 01: Retro Arcade Connect 4

## Assignment

Use an AI coding assistant to build a simple but charming one- or two-player game as a single HTML/JavaScript file, themed as a classic retro arcade game, and verify that it plays properly. The exact prompt is in [`prompt.md`](prompt.md).

## What was built

[`connect4_arcade.html`](connect4_arcade.html) is a Connect 4 game built with Claude Code:

- **Modes:** 1 player against a CPU opponent (minimax search with alpha-beta pruning), or 2 players on the same screen.
- **Theme:** neon colors, CRT scanlines, pixel font and chiptune sound effects.
- **Gameplay:** animated chip drops, flashing winning line, draw detection, running score and round counter, and the first move alternates each round.
- **Controls:** mouse or keyboard (← → to move, Space/Enter to drop, 1–7 to quick-drop, R to restart, M to mute, Esc for the menu).

## How to run

Download `connect4_arcade.html` and open it in any web browser. No installation is needed.

## Testing

Before calling it done, Claude ran 55 automated checks in a headless browser. They covered wins in all four directions, false-win cases, full columns, draws, every control, the CPU taking and blocking wins, and full games against the CPU. Claude also reviewed screenshots on desktop and phone widths.

## Reflection

_Add your notes here: what worked well, what you would change in the prompt, and what you learned about working with an AI coding assistant._
