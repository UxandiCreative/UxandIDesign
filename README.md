# Uxandi

UI layout canvas for agentic workflows. Each shape becomes a UI element, defined by your notes.

Design tooling turns the layout into rules. Prompt-based context, programmatic placement.

Any project, framework or language. The agent only needs the JSON.

- Desktop app, Python + PySide6
- Containers only: rectangles, circles / ovals, lines
- Freehand drawing: any stroke is a shape with notes (marks, corrections, arrows)
- Real device canvases: desktop, iPad, phone
- Notes on every shape, page and project carry the meaning
- No text element, no role presets
- Export: pixel boxes, styles, nesting, notes
- Export adds nothing beyond what you wrote
- 29 agent tools over MCP and command line

## How Uxandi differs

### Scope
- Layout plus written intent: position, size, nesting, purpose, look
- The look is described in words: notes and the project brief
- Optional visual hints: fill, border, corners, pictures
- No visual design step. The agent builds what the user wrote
- No component library. Every element is a container, and its meaning is in its notes
- No text element, no role presets

### Input
- Rectangles, circles / ovals, lines and freehand strokes on fixed device canvases
- Notes on every shape and page: content, behaviour, states, style
- Project brief: product, audience, visual style, rules
- Dot grid from 1 px

### Output
- One JSON file of data only: pixel boxes, nesting, styles, notes
- Nothing added beyond what the user wrote
- Format published as a JSON Schema (2020-12), with a validator included
- Compact form: same facts, about 5x smaller
- Re-importable

### AI
- No built-in model, no generation limits, no API key
- Works with any MCP agent
- The same agent can lay out and then build
- 29 tools covering layout, copies, templates, checks, screenshots, export, import
- Live mode: the agent edits the open app, each command one undo step
- File mode: the agent edits project files with the app closed

### Running it
- Local, offline after install
- No account, no cloud, no telemetry
- Free, open source
- Agent server: Python standard library only

## Examples

Left: layout in Uxandi. Right: UI an agent built from the export.

![Phone app, 3 screens: layout in Uxandi, then the screens an agent built from the export](media/examples/phone-app.jpg)

<p align="center"><sub><b>Phone app</b> · iPhone 16 Pro · 3 screens</sub></p>

![Streaming site home page: layout in Uxandi, then the page an agent built from the export](media/examples/streaming-site.jpg)

<p align="center"><sub><b>Streaming site</b> · desktop web, 1440 × 2400 · poster and hero art: Codex</sub></p>

![Strategy game HUD: layout in Uxandi, then the HUD an agent built from the export](media/examples/strategy-game-hud.jpg)

<p align="center"><sub><b>Strategy game HUD</b> · 1920 × 1080 · 123 boxes · game art: Codex</sub></p>

## Use cases

Any task where an agent needs to know what goes where. Shapes mark areas, notes say what they are, the export gives exact positions.

### Core
| Use | Shapes and notes |
|---|---|
| App and web screens | Regions, components, content, behaviour |
| Responsive layouts | One page per device preset. The differences are the rules |
| Design systems | Templates for repeated elements. Brief for colours, type, spacing |
| Redesigns | Current screen as a picture, new layout over it |
| Layout to code | Export to any agent, any framework, any language |
| Handoff specs | Exact sizes, gaps and nesting instead of a written spec |

### Interaction and motion
| Use | Shapes and notes |
|---|---|
| States | One page per state: empty, loading, error, success |
| User flows | One page per step. Notes link the pages |
| Animation keyframes | Copy a page, move the shapes, keep the names. Notes: timing, easing |
| Transitions | Start page, end page. Notes describe the motion |
| Gestures | Drawn path for the swipe or drag. Notes: the result |
| Onboarding, tooltips | Overlay boxes on top of the screen they explain |

### Games
| Use | Shapes and notes |
|---|---|
| HUDs and menus | Bars, slots, counters, prompts |
| Levels | Platforms, spawns, triggers, hazards. Dot grid as tile grid |
| Hitboxes | Boxes and circles as collision and damage zones |
| Enemy routes, camera rails | Drawn paths. Notes: speed, timing |
| Board and card games | Card template page, board page, zones |
| Puzzles | Cell grids. Rules in the brief |

### Screens and hardware
| Use | Shapes and notes |
|---|---|
| Embedded displays | Custom canvas at exact pixels: watch, OLED, e-ink, car dash |
| Kiosks, POS, signage | Fixed-resolution screens |
| TV and console UIs | Focus order in notes |
| VR and AR panels | One canvas per panel. Depth and anchoring in notes |
| Stream overlays | Camera, chat, alerts, lower thirds |
| Video frames | Margins as title-safe area. Boxes for captions and graphics |

### Pictures and documents
| Use | Shapes and notes |
|---|---|
| Computer-use target maps | Screenshot in a box, boxes over buttons and fields |
| UI test locators | Expected positions for visual and end-to-end tests |
| Form and invoice extraction | Boxes over a scan: total, date, signature |
| Image labelling | Boxes over photos as labelled bounding boxes |
| Art direction | Crop, subject placement, text-safe zones |
| Plan markup | Floor plan or map as a picture, rooms and routes over it |

### Review and feedback
| Use | Shapes and notes |
|---|---|
| Design review | Draw around a problem, write the fix |
| Bug reports | Screenshot, circled area, expected behaviour |
| Critique and grading | Marks and comments over a screenshot or page |
| Accessibility audit | `check_layout` for small targets. Notes for contrast and labels |
| Change requests to an agent | Marks and notes over its last build |

### Physical and print
| Use | Shapes and notes |
|---|---|
| Print | Posters, slides, labels, packaging, book pages. Scale in the brief: 1 px = 1 mm |
| Spaces | Floor plans, seating, stage plots, shelf planograms, warehouse zones |
| Fabrication | Laser cut, CNC, panel cutouts. Shapes as outlines, material in notes |
| Land | Garden beds, paths, planting and event zones |

### Agents and automation
| Use | Shapes and notes |
|---|---|
| Agent to agent | One agent lays out, another builds. The JSON is the contract |
| Build checks | A tester agent compares the result against the export |
| Procedural generation | Zones placed by hand, contents generated inside them |
| Dashboards | Widget slots. Data source and refresh per slot in notes |
| Email and PDF templates | Fixed-width layouts with content slots |
| Robots and drones | Areas over a camera view or top-down map. Task per area |

### Experimental
| Use | Shapes and notes |
|---|---|
| Storyboards, comics | Pages as shots or panels. Action and dialogue in notes |
| Video edits | Split screens, picture-in-picture, graphic positions |
| Sound | Source positions on a stage canvas, or a cell grid as a sequencer |
| Diagrams | Containers as systems, nesting as ownership, lines as links |
| Boards and mind maps | Note clusters, groups as themes |
| Image generation | Layout as a composition guide for an image model |
| Teaching | Layout exercises an agent checks and comments on |
| Agent memory | A page as a spatial map an agent reads and updates |

## Requirements

| Need | Version | Notes |
|---|---|---|
| Python | 3.9+ | Tested on 3.14. Windows: tick "Add python.exe to PATH" |
| PySide6 | 6.8+, below 7 | Only dependency. `requirements.txt` |
| OS | Windows 10 / 11, macOS, Linux | Tested on Windows only |

- No database, server, account or internet after install
- Agent tools: Python standard library only
- Linux, error `Could not load the Qt platform plugin "xcb"`:

  ```
  sudo apt install libxcb-cursor0 libxkbcommon-x11-0
  ```

## Install and run

```
git clone https://github.com/UxandiCreative/UxandIDesign.git
cd UxandIDesign
python -m venv .venv
.venv\Scripts\activate             # Windows
source .venv/bin/activate          # macOS / Linux
python -m pip install -r requirements.txt
python main.py
```

- No git: Code > Download ZIP
- `python` not found: `python3`
- venv optional. Activate before each run
- Opens maximized. F11: full screen

## AI agents (MCP)

| App | Mode | Agent |
|---|---|---|
| Open | live | Works in the window. Each command one Ctrl+Z step |
| Closed | file | Edits project files, saves each change |

```
python uxandi_agent.py mcp                MCP server
python uxandi_agent.py call get_status    one tool, command line
```

- Setup files: `.mcp.json` (Claude Code), `.vscode/mcp.json` (VS Code), `.cursor/mcp.json` (Cursor). Approve server `uxandi`
- Other clients, command line: [AGENTS.md](AGENTS.md)
- Tools, recipes: [TOOLS.md](TOOLS.md)
- MCP resources: export schema, tool reference. Prompts: design screen, design flow, review, hand-off

## Window

| Area | Holds |
|---|---|
| Header | Project name, Open / New / Save / Save as, tools (Select V, Rectangle R, Circle C, Line L, Draw D), undo / redo, zoom, Export JSON (▾: copy only, open folder, import) |
| Left tabs | Brief (project brief, page notes), Canvas (size, presets, My screen = this monitor, dot spacing 1–400 px, margins), Create, Snapping, View |
| Right tabs | Shape (name, position, size), Design (fill, border, corners, images, templates), Transform (rotate, flip, order), Details (all facts on the selection), Shapes (list, drag to reorder) |
| Canvas | Group pills bottom-left. Page strip bottom: click opens, drag reorders, `+` adds, right-click renames / copies / removes |

## Mouse and keys

| Input | Action |
|---|---|
| Drag shape | Move. Snaps to edges, centres, canvas, equal gaps |
| Handles | Square: resize. Round: rotate. Pink corner: radius |
| Right / middle / Space drag | Pan |
| Wheel | Zoom to cursor |
| Shift | Keep proportions, lock axis, 15° turns, 45° lines |
| Alt | Resize from centre. Alt-drag copies |
| Ctrl while dragging | No snapping |
| Arrows / Shift+arrows | Nudge 1 / 10 px. Dot snapping: 1 / 5 dots |
| Number box arrows, wheel, ↑ / ↓ | Step the value. Hold to repeat |
| Slider ‹ › | Step 1%. Hold to repeat |
| Double-click, F2 | Name shape |
| Ctrl+D, Ctrl+C / V / X, Del | Duplicate, copy / paste / cut, delete |
| Ctrl+G / Ctrl+Shift+G | Group / remove from group |
| Ctrl+] / [ (Shift: front / back) | Layer order |
| Shift+H / Shift+V | Flip |
| Ctrl+Z / Ctrl+Y | Undo / redo |
| Ctrl+0 / Ctrl+1 | Fit / 100% |
| Ctrl+PgUp / PgDn | Previous / next page |

## Export

| Kind | Menu | For | Content |
|---|---|---|---|
| Compact (default) | Export JSON | LLM builder | Reading guide, brief, pages (size, device, margins, dot grid, notes, groups), elements (name, notes, type, box, rotation, parent, group, colours + opacity, border, radius, image fit / zoom / offset / opacity). Empty, default, derivable values left out. About 5x smaller. `how_to_read` lists every default |
| Full | ▾ > Export full JSON | Code that parses it | Same facts, every field written out, plus centre, canvas %, layer, children, nesting tree |

```
exports/<project>/
  <project>.compact.ui.json           newest compact export
  <project>.ui.json                   newest full export
  history/<project>_<date_time>.json  every export
  images/                             pictures used in shapes
```

- Export holds data only. Instructions come from your notes
- Copied to clipboard on export
- Import: ▾ > Import an export
- Format: JSON Schema, [schema/ui.compact.schema.json](schema/ui.compact.schema.json), [schema/ui.schema.json](schema/ui.schema.json)
- Each export names its schema in `$schema`
- Validate: `python uxandi_agent.py validate <file>`
- [schema/](schema/) also covers project files, Design templates, agent tools (`tools.json`)

## Files

Created on first use. Git-ignored.

| Path | Holds |
|---|---|
| `projects/*.uxandi` | Projects |
| `exports/` | Exports |
| `assets/images/` | Pictures in shapes |
| `templates/design/` | Design templates |
| `data/session.json` | Last session, reopened on launch |
| `data/bridge.json` | App open only: port + token for agents |

`UXANDI_HOME=<folder>`: moves `projects/`, `exports/`, `templates/`, `data/`.

## Tests

| Script | Covers |
|---|---|
| `tools/check_app.py` | App, headless. Screenshots to `tools/_check/` |
| `tools/check_agent.py` | Agent tools in file mode, live app, MCP. Schema and `TOOLS.md` sync, export validation, every `TOOLS.md` recipe |
