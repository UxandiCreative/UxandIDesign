# Uxandi agent tools: reference and recipes

For agents and for people wiring agents up. Client setup: [AGENTS.md](AGENTS.md).

- 29 tools. MCP: `python uxandi_agent.py mcp`. Command line: `python uxandi_agent.py call <tool> '<json>'`
- [schema/tools.json](schema/tools.json): every tool's description, input schema, hints (= MCP `tools/list`)
- Export format, JSON Schema 2020-12: [schema/ui.schema.json](schema/ui.schema.json), [schema/ui.compact.schema.json](schema/ui.compact.schema.json)
- Project files (`.uxandi`): [schema/project.schema.json](schema/project.schema.json). Style templates: [schema/design-template.schema.json](schema/design-template.schema.json)
- [Tool reference](#tool-reference-29-tools) at the end: generated from the code

## Behaviour

| Topic | Rule |
|---|---|
| Modes | App open: commands run in the window, one Ctrl+Z step each. App closed: commands edit and save the project files. `get_status` reports the mode |
| Shape reference | Id or exact name. Names unique per page. Ambiguous name: error asks for the id |
| Page reference | Number (1 = first), name or id. Left out: page on screen |
| Frame (`"in"`) | `"canvas"` (default), `"safe_area"` (inside margins), or a rectangle (child in parent) |
| Position | px from frame start, `"N%"`, `"start"` / `"center"` / `"end"` + offset (`"end-16"`, `"center+8"`). Missing `x` / `y`: centred |
| Size | px or `"N%"` |
| Nesting | Parent: smallest rectangle beneath the shape that holds it completely. Rectangles covered by a filled box in between are skipped (dialog on scrim: parent is the scrim) |
| Carry | Moving a container (`move`, `arrange`, `grid`, `align`, `distribute`) moves its children. `carry: false` stops it |
| Page rules | `keep_inside` margins, dot snapping: shapes moved / shrunk like in the app, reported under `"adjusted"` with the reason |
| Batch | Many commands, one undo step, all or nothing. Failed step named in the error. Not batchable: files, templates, history, select, screenshot |
| Errors | One sentence with the fix, e.g. `No shape 'Hedaer' on page 'Home'. Shapes: Header, Logo, ...`. MCP: `isError: true`. CLI: `{"error": "..."}`, exit 1 |
| Device pixels | Phone presets about 3x points, iPad 2x, desktop 1x (4K 2x). 44 pt touch target = about 132 px on a phone |

## Goal to tool

| Goal | Tools |
|---|---|
| What is open, what is on screen | `get_status`, `get_page` |
| New project, screen at device size | `new_project`, `add_page` + `preset` (`list_presets`) |
| Product and screen descriptions | `set_project` `brief`, `update_page` `notes` |
| Screen regions | `create_shapes` (many per call, children via `"in"`) |
| Row, column, toolbar, form | `arrange` (`gap`, `padding`, `sizes` like `[240, "1fr"]`) |
| Card grid, gallery, tiles | `grid` (`columns`, `gap`, `aspect` or `row_height`) |
| Repeated card, list row, table row, tab | one item, then `duplicate_shapes` (`count`, `offset`) |
| Same nav bar / tab bar on other screens | `duplicate_shapes` + `to`, or `add_page` + `copy_of` |
| Other state or device version of a screen | `add_page` `copy_of`, `update_page` `preset`, re-`arrange` |
| Line up, space evenly | `align`, `distribute` |
| Same look for same element kind | `save_template`, `"template"` on shapes, `list_templates` |
| Mirror an icon or arrow | `update_shapes` + `flip_h` / `flip_v` |
| Mark or annotate (circle an area, an arrow, a correction) | `create_shapes` `kind: "path"` + `points` + `notes` |
| Find mistakes | `check_layout` (page `"all"`), `screenshot` |
| Point the user at shapes | `select` (live mode) |
| Hand off to the builder | `export_json` (compact by default. `compact: false`: full form) |
| Load an export | `import_export` |
| Undo an agent step | `history` |

## Recipes

- Each block: one complete call, sendable as is
- Run in order: one project, desktop app + phone screen
- `tools/check_agent.py` runs every block
- Children named after their container (`"Row 1 title"`), copies follow (`"Row 2 title"`)
- All sizes and gaps: multiples of the page `dot_spacing`

### Desktop app shell: sidebar, top bar, content

```json
{"tool": "batch", "args": {"calls": [
  {"tool": "add_page", "args": {"name": "Dashboard", "preset": "1440 x 900", "margins": 0, "dot_spacing": 8,
    "notes": "Signed-in home. Sidebar navigation, a top bar, and the user's projects as cards."}},
  {"tool": "create_shapes", "args": {"shapes": [
    {"name": "Sidebar", "fill": "#F3F4F6", "stroke": null,
     "notes": "Left navigation, fixed. Logo at the top, then Home (selected), Projects, Orders, Settings."},
    {"name": "Main", "fill": null, "stroke": null, "notes": "Everything right of the sidebar."}]}},
  {"tool": "arrange", "args": {"shapes": ["Sidebar", "Main"], "sizes": [240, "1fr"]}},
  {"tool": "create_shapes", "args": {"shapes": [
    {"name": "Top bar", "in": "Main", "x": 0, "y": 0, "w": "100%", "h": 64, "stroke": null,
     "notes": "Page title 'Projects' on the left; search field and account menu on the right."},
    {"name": "Content", "in": "Main", "x": 0, "y": 64, "w": "100%", "h": 836, "fill": null, "stroke": null,
     "notes": "Scrolls under the top bar."}]}}]}}
```

### Card grid: build one card, copy it, grid the copies

```json
{"tool": "batch", "args": {"calls": [
  {"tool": "create_shapes", "args": {"shapes": [
    {"name": "Project card 1", "in": "Content", "w": 368, "h": 240, "radius": 16, "fill": "#FFFFFF", "stroke": "#E5E7EB",
     "stroke_width": 1, "notes": "One project. Click opens it. Hover: shadow. Data: project name, cover, last edited."},
    {"name": "Project card 1 cover", "in": "Project card 1", "x": 0, "y": 0, "w": "100%", "h": 144, "radius": 16,
     "notes": "Cover image, cropped to fill."},
    {"name": "Project card 1 name", "in": "Project card 1", "x": 16, "y": 160, "w": 336, "h": 32,
     "notes": "Project name, one line, ellipsis. 16 px semibold."},
    {"name": "Project card 1 edited", "in": "Project card 1", "x": 16, "y": 200, "w": 336, "h": 24,
     "notes": "'Edited 2 days ago', 13 px, muted."}]}},
  {"tool": "duplicate_shapes", "args": {"shapes": ["Project card 1"], "count": 5}},
  {"tool": "grid", "args": {"shapes": ["Project card 1", "Project card 2", "Project card 3",
                                        "Project card 4", "Project card 5", "Project card 6"],
    "into": "Content", "columns": 3, "gap": 24, "padding": 24, "row_height": 240}}]}}
```

`grid` moves each card with its cover, name and date.

### Style kit: one look for one kind of element

```json
{"tool": "save_template", "args": {"name": "Primary button", "fill": "#1F6FEB", "stroke": null, "radius": 8, "overwrite": true}}
```

```json
{"tool": "create_shapes", "args": {"page": "Dashboard", "shapes": [
  {"name": "New project button", "in": "Top bar", "x": "end-24", "y": "center", "w": 160, "h": 40, "template": "Primary button",
   "notes": "Label 'New project'. Opens the New project dialog."}]}}
```

Same template available in the Design tab. `list_templates`: saved ones.

### Dialog over a screen, as its own state

```json
{"tool": "batch", "args": {"calls": [
  {"tool": "add_page", "args": {"copy_of": "Dashboard", "name": "Dashboard - delete dialog",
    "notes": "The Dashboard while the Delete project dialog is open."}},
  {"tool": "create_shapes", "args": {"shapes": [
    {"name": "Scrim", "x": 0, "y": 0, "w": "100%", "h": "100%", "fill": "#66000000", "stroke": null,
     "notes": "Dims the page. Click closes the dialog."},
    {"name": "Delete dialog", "w": 480, "h": 240, "radius": 16, "fill": "#FFFFFF", "stroke": null,
     "notes": "Modal, centred. Esc closes it. Focus starts on Cancel."},
    {"name": "Delete dialog title", "in": "Delete dialog", "x": 24, "y": 24, "w": 432, "h": 32,
     "notes": "'Delete this project?', 20 px semibold."},
    {"name": "Delete dialog body", "in": "Delete dialog", "x": 24, "y": 64, "w": 432, "h": 64,
     "notes": "'This removes the project and its files for everyone. It cannot be undone.'"},
    {"name": "Delete dialog actions", "in": "Delete dialog", "x": 24, "y": "end-24", "w": 432, "h": 40,
     "fill": null, "stroke": null, "notes": "The two buttons, right-aligned."},
    {"name": "Cancel button", "in": "Delete dialog actions", "notes": "Label 'Cancel'. Closes the dialog."},
    {"name": "Delete button", "in": "Delete dialog actions", "template": "Primary button", "fill": "#D92D20",
     "notes": "Label 'Delete'. Deletes, closes the dialog, shows a toast 'Project deleted'."}]}},
  {"tool": "arrange", "args": {"shapes": ["Cancel button", "Delete button"], "into": "Delete dialog actions",
    "sizes": [104, 104], "gap": 8, "justify": "end"}}]}}
```

Scrim drawn above the cards: not their parent. Dialog parent: the scrim.

### Data table, with the same sidebar on a new page

```json
{"tool": "batch", "args": {"calls": [
  {"tool": "add_page", "args": {"name": "Orders", "preset": "1440 x 900", "margins": 0, "dot_spacing": 8,
    "notes": "All orders, newest first. Opened from Orders in the sidebar."}},
  {"tool": "duplicate_shapes", "args": {"page": "Dashboard", "shapes": ["Sidebar"], "to": "Orders"}},
  {"tool": "create_shapes", "args": {"shapes": [
    {"name": "Orders table", "x": 264, "y": 24, "w": 1152, "h": 400, "fill": null, "stroke": "#E5E7EB", "stroke_width": 1,
     "notes": "Sortable by every column. 20 rows per page."},
    {"name": "Table header", "in": "Orders table", "x": 0, "y": 0, "w": "100%", "h": 48, "fill": "#F9FAFB", "stroke": null,
     "notes": "Column titles: Customer, Date, Status, Total. Click a title to sort."},
    {"name": "Row 1", "in": "Orders table", "x": 0, "y": 48, "w": "100%", "h": 56, "fill": null, "stroke": null,
     "notes": "One order. Click opens it."},
    {"name": "Row 1 customer", "in": "Row 1", "notes": "Customer name and email, two lines."},
    {"name": "Row 1 date", "in": "Row 1", "notes": "Order date, '12 Mar 2026'."},
    {"name": "Row 1 status", "in": "Row 1", "notes": "Badge: Paid (green), Pending (amber) or Refunded (grey)."},
    {"name": "Row 1 total", "in": "Row 1", "notes": "Amount with currency, right-aligned."}]}},
  {"tool": "arrange", "args": {"shapes": ["Row 1 customer", "Row 1 date", "Row 1 status", "Row 1 total"],
    "into": "Row 1", "sizes": ["2fr", "1fr", "1fr", 160], "padding": [8, 16], "gap": 16}},
  {"tool": "duplicate_shapes", "args": {"shapes": ["Row 1"], "count": 5, "offset": [0, 56]}}]}}
```

- `duplicate_shapes` + `to`: sidebar with all contents onto the new page
- Copies of `Row 1`: `Row 2` to `Row 6`, cells named after them

### Form, laid out as a column

```json
{"tool": "batch", "args": {"calls": [
  {"tool": "add_page", "args": {"name": "Sign up", "preset": "1440 x 900", "margins": 40, "dot_spacing": 8,
    "notes": "Create an account. Reached from 'Sign up' on the landing page; success opens Dashboard."}},
  {"tool": "create_shapes", "args": {"shapes": [
    {"name": "Sign up form", "w": 480, "h": 472, "radius": 16, "fill": "#FFFFFF", "stroke": "#E5E7EB", "stroke_width": 1,
     "notes": "Centred card. Submits with Enter."},
    {"name": "Form title", "in": "Sign up form", "notes": "'Create your account', 24 px semibold."},
    {"name": "Email label", "in": "Sign up form", "notes": "'Email'."},
    {"name": "Email input", "in": "Sign up form", "notes": "Placeholder 'you@example.com'. Error: red border, Email error shows."},
    {"name": "Email error", "in": "Sign up form", "notes": "Hidden until the email is invalid: 'Enter a valid email address.'"},
    {"name": "Password label", "in": "Sign up form", "notes": "'Password'."},
    {"name": "Password input", "in": "Sign up form", "notes": "Masked, with a show / hide eye button inside on the right."},
    {"name": "Password hint", "in": "Sign up form", "notes": "'At least 12 characters.' Turns red when too short."},
    {"name": "Create account button", "in": "Sign up form", "template": "Primary button",
     "notes": "Label 'Create account'. Disabled until both fields are valid; shows a spinner while sending."},
    {"name": "Sign in link", "in": "Sign up form", "notes": "'Already have an account? Sign in', opens Sign in."}]}},
  {"tool": "arrange", "args": {"shapes": ["Form title", "Email label", "Email input", "Email error", "Password label",
                                          "Password input", "Password hint", "Create account button", "Sign in link"],
    "into": "Sign up form", "direction": "column", "sizes": [40, 24, 48, 24, 24, 48, 24, 48, 24], "gap": 16, "padding": 32}}]}}
```

### Phone screen: status bar, nav bar, list, tab bar

```json
{"tool": "batch", "args": {"calls": [
  {"tool": "add_page", "args": {"name": "Orders (phone)", "preset": "iPhone 16 Pro", "margins": 0, "dot_spacing": 12,
    "notes": "The Orders list on a phone. 3x canvas: 1206 x 2622 px is 402 x 874 pt."}},
  {"tool": "create_shapes", "args": {"shapes": [
    {"name": "Status bar", "x": 0, "y": 0, "w": "100%", "h": 168, "fill": null, "stroke": null,
     "notes": "System status bar and Dynamic Island: keep clear."},
    {"name": "Nav bar", "x": 0, "y": 168, "w": "100%", "h": 132, "stroke": null, "notes": "Title 'Orders'; filter button on the right."},
    {"name": "Feed", "x": 0, "y": 300, "w": "100%", "h": 2064, "fill": null, "stroke": null, "notes": "Scrolls. Pull to refresh."},
    {"name": "Order row 1", "in": "Feed", "x": 48, "y": 24, "w": 1104, "h": 216, "radius": 24, "stroke": null,
     "notes": "One order. Tap opens it."},
    {"name": "Order row 1 thumbnail", "in": "Order row 1", "x": 24, "y": "center", "w": 168, "h": 168, "radius": 16,
     "notes": "Product photo."},
    {"name": "Order row 1 title", "in": "Order row 1", "x": 216, "y": 36, "w": 600, "h": 60,
     "notes": "Product name, one line, ellipsis."},
    {"name": "Order row 1 price", "in": "Order row 1", "x": "end-24", "y": 36, "w": 216, "h": 60,
     "notes": "Total, right-aligned."},
    {"name": "Tab bar", "x": 0, "y": "end", "w": "100%", "h": 252, "stroke": null,
     "notes": "Four tabs above the home indicator."},
    {"name": "Tab Home", "in": "Tab bar", "notes": "Icon and label 'Home'."},
    {"name": "Tab Orders", "in": "Tab bar", "notes": "Selected. Icon and label 'Orders'."},
    {"name": "Tab Saved", "in": "Tab bar", "notes": "Icon and label 'Saved'."},
    {"name": "Tab Profile", "in": "Tab bar", "notes": "Icon and label 'Profile'."}]}},
  {"tool": "duplicate_shapes", "args": {"shapes": ["Order row 1"], "count": 5, "offset": [0, 240]}},
  {"tool": "arrange", "args": {"shapes": ["Tab Home", "Tab Orders", "Tab Saved", "Tab Profile"], "into": "Tab bar",
    "padding": [12, 24, 108, 24], "gap": 12}}]}}
```

### Check, look, hand off

```json
{"tool": "check_layout", "args": {"page": "all"}}
```

```json
{"tool": "screenshot", "args": {"page": "Dashboard", "max_size": 1280}}
```

```json
{"tool": "export_json", "args": {}}
```

- Fix everything `check_layout` reports, look at each page, then hand over
- Check a file: `python uxandi_agent.py validate exports/<project>/<project>.compact.ui.json`

## The export

| Form | Path | For |
|---|---|---|
| Compact (default) | `exports/<project>/<project>.compact.ui.json` | LLM builder. Defaults and derivable values left out, about 5x smaller |
| Full (`compact: false`) | `exports/<project>/<project>.ui.json` | Code that parses it. Every field written out, plus centres, canvas %, children, `layout_tree` |

Both carry `$schema` and a plain-language `how_to_read` list.

| Field | Holds |
|---|---|
| `project.brief` | Product, audience, style, rules |
| `pages[]` | One per screen. `canvas`: size, device, preset. `notes`: purpose. `margins`, dot grid: layout rules |
| `pages[].elements[]` | Back to front. `name`, `notes`, box (`bounds`, compact: `box`), `parent`, `style`, optional `contents` (picture) |
| `layout_tree` | Full form only. Nesting as a tree |

Validate: `python uxandi_agent.py validate <file>`, or any JSON Schema 2020-12 validator with [schema/](schema/).

## MCP extras

| Kind | Items |
|---|---|
| Resources | `uxandi://guide`, `uxandi://reference/tools` (this page), `uxandi://schema/<file>` per file in `schema/` |
| Prompts | `design_screen` (screen, device), `design_flow` (flow, device), `review_layout` (page), `prepare_handoff` |

## Versions

- `get_status`: `api_version`
- Exports: `format` `uxandi-export`, `version` 1
- Additive change: same version. Breaking change: new version, new schema
- Generated: tool reference below, `schema/`. After changing a tool: `python uxandi_agent.py schema`
- `python tools/check_agent.py` fails when they are stale, validates exports, runs every recipe

<!-- tool-reference:start (generated by `python uxandi_agent.py schema`; edit uxandi/agent.py instead) -->

## Tool reference (29 tools)

### Read

#### `get_status` (read-only)

Start here. The project (name, brief, file, unsaved changes), every page (size, device, shape count), the page on screen, the user's selection, dot snapping, and whether the app is open (live) or closed (file mode).

No arguments.

#### `get_page` (read-only)

One page in full: canvas size, margins and safe area, notes, groups, every shape in stacking order (back first) with box [x, y, w, h], style, notes and parent, plus an indented outline of the nesting. The fields use the same names create_shapes / update_shapes take. full: true returns the export's exhaustive form instead.

| Argument | Type | Description |
|---|---|---|
| `page` | integer or string | Page number (1 = first), name or id. Leave out for the page on screen. |
| `full` | boolean |  |

#### `screenshot` (read-only)

A PNG of a page (shape names drawn on it by default) so you can see the layout. of: "window" shows the whole app window as the user sees it (live mode only).

| Argument | Type | Description |
|---|---|---|
| `page` | integer or string | Page number (1 = first), name or id. Leave out for the page on screen. |
| `max_size` | integer | Longest side in px (default 1280). |
| `labels` | boolean |  |
| `margins` | boolean |  |
| `of` | `"page"` \\| `"window"` |  |

#### `check_layout` (read-only)

Find problems: shapes off or past the canvas, past the margins, partly overlapping siblings, edges 1-2 px off from a neighbour or the parent, tiny or invisible shapes, duplicate / generic names, missing notes, empty brief or page notes. Run it before export_json. page: "all" checks every page.

| Argument | Type | Description |
|---|---|---|
| `page` | integer or string | Page number (1 = first), name or id. Leave out for the page on screen. |
| `limit` | integer |  |

#### `list_presets` (read-only)

Device canvas sizes (Desktop, iPad, Phone) for add_page / update_page preset.

No arguments.

#### `list_projects` (read-only)

Saved projects (projects/*.uxandi), newest first.

No arguments.

### Build

#### `create_shapes`

Make one or many shapes on a page (one undo step). kind: rect (default), square, ellipse, circle (an ellipse that keeps w = h), line or path (a freehand stroke through points: [[x, y], ...], for marks and annotations; never a container). Ellipses are containers like rects. There is no text element: a label, heading or button is a rect whose name and notes say what it is and shows. Place children with "in": parent so x / y / w / h are measured inside it, e.g. {"name": "Logo", "in": "Header", "x": 24, "y": "center", "w": 120, "h": 40}. Missing x / y centre the shape in its frame. New shapes use the app's current new-shape style unless you set fill / stroke. Shapes are made in list order, so a later one can be "in" an earlier one.

| Argument | Type | Description |
|---|---|---|
| `page` | integer or string | Page number (1 = first), name or id. Leave out for the page on screen. |
| `shapes` (required) | array of object | Shape objects: the fields in the table below. |

Shape fields (create_shapes and update_shapes):

| Field | Type | Description |
|---|---|---|
| `kind` | `"rect"` \\| `"square"` \\| `"ellipse"` \\| `"circle"` \\| `"line"` \\| `"path"` |  |
| `name` | string | What it is, unique on the page: "Header", "Sign in button". |
| `notes` | string | Everything the building agent must know: purpose, text it shows, behaviour, states, data. |
| `in` | string | Frame that x / y / w / h are measured in: "canvas" (default), "safe_area", or a rectangle (place a child inside its parent). |
| `x` | number or string | Pixels from the frame's left / top, "N%" of the frame, or "start" / "center" / "end" with optional "+N" / "-N" (e.g. "end-24"). |
| `y` | number or string | Pixels from the frame's left / top, "N%" of the frame, or "start" / "center" / "end" with optional "+N" / "-N" (e.g. "end-24"). |
| `w` | number or string | Pixels, or "N%" of the frame. |
| `h` | number or string | Pixels, or "N%" of the frame. |
| `box` | array of number | [x, y, w, h] in one field (absolute unless "in" is given). |
| `rotation` | number | Degrees clockwise about the centre. |
| `radius` | number | Corner radius in px. |
| `fill` | string or null | Hex "#RRGGBB" (or "#AARRGGBB", alpha first); null for none. |
| `fill_opacity` | number | 0..1 |
| `stroke` | string or null | Border / line colour, hex; null for no border. |
| `stroke_opacity` | number | 0..1 |
| `stroke_width` | number | Border thickness (inside the box) or line thickness, px. 0 = no border. |
| `lock_ratio` | boolean | Resizing in the app keeps proportions. |
| `points` | array of number or array of number | Line: [x1, y1, x2, y2]. Path (freehand drawing): [[x, y], [x, y], ...] in the frame "in". |
| `x1` | number or string | Pixels from the frame's left / top, "N%" of the frame, or "start" / "center" / "end" with optional "+N" / "-N" (e.g. "end-24"). |
| `y1` | number or string | Pixels from the frame's left / top, "N%" of the frame, or "start" / "center" / "end" with optional "+N" / "-N" (e.g. "end-24"). |
| `x2` | number or string | Pixels from the frame's left / top, "N%" of the frame, or "start" / "center" / "end" with optional "+N" / "-N" (e.g. "end-24"). |
| `y2` | number or string | Pixels from the frame's left / top, "N%" of the frame, or "start" / "center" / "end" with optional "+N" / "-N" (e.g. "end-24"). |
| `line_style` | `"solid"` \\| `"dash"` \\| `"dot"` |  |
| `cap` | `"round"` \\| `"flat"` \\| `"square"` |  |
| `image` | object or null | Picture inside a rectangle: {"file": path, "fit": fill\|fit\|stretch\|original, "zoom", "dx", "dy", "opacity"}; null removes it. |
| `group` | string or null | Put it in this named group (made if new); null takes it out. |
| `order` | `"front"` \\| `"back"` \\| `"forward"` \\| `"backward"` | Stacking order change. |
| `template` | string | Style it with a saved design template (list_templates): fill, border, corners (lines: colour, thickness, dash, ends). Style fields given beside it win. |
| `flip_h` | boolean | Mirrored left-right (e.g. a back arrow made from a forward one). |
| `flip_v` | boolean | Mirrored top-bottom. |

#### `update_shapes`

Change shapes: any field create_shapes takes (geometry, style, name, notes, image, group, order), plus move: [dx, dy] and center: [x, y]. Rectangles carry the shapes inside them when they move (carry: false to stop that). Only the fields you give change.

| Argument | Type | Description |
|---|---|---|
| `page` | integer or string | Page number (1 = first), name or id. Leave out for the page on screen. |
| `changes` (required) | array of object | Change objects: "shape" (id or name) plus any shape field below, "move", "center", "carry". |

#### `delete_shapes` (destructive)

Delete shapes. with_children: true also deletes every shape inside them.

| Argument | Type | Description |
|---|---|---|
| `page` | integer or string | Page number (1 = first), name or id. Leave out for the page on screen. |
| `shapes` (required) | array of string | Shape ids or names. |
| `with_children` | boolean |  |

#### `duplicate_shapes`

Copy shapes, each with everything inside it (with_children: false copies the shape alone). Build one card, row or nav bar, then make the rest from it: count copies, each offset [dx, dy] from the one before (default: one dot step down-right; [0, 0] on another page). to: another page, e.g. the same tab bar on every screen. Copies get the next free name ("Card 1" -> "Card 2"); children named after their container follow it ("Card 1 price" -> "Card 2 price"), or give names, one per copy. Then place them with grid / arrange and rewrite their notes.

| Argument | Type | Description |
|---|---|---|
| `page` | integer or string | Page number (1 = first), name or id. Leave out for the page on screen. |
| `shapes` (required) | array of string | Shape ids or names. |
| `count` | integer |  |
| `offset` | array of number |  |
| `to` | integer or string | Page to put the copies on (default: the same page). |
| `names` | array of string | Names for the copies: copy 1 of each shape in order, then copy 2, ... |
| `with_children` | boolean |  |

#### `set_group`

Make or change a named group of shapes (a shape is in one group at most). An empty shapes list removes the group (the shapes stay).

| Argument | Type | Description |
|---|---|---|
| `page` | integer or string | Page number (1 = first), name or id. Leave out for the page on screen. |
| `name` (required) | string |  |
| `shapes` (required) | array of string | Shape ids or names. |

### Layout

#### `arrange`

Flex-style layout: put shapes in a row or column inside a container (or the canvas / safe area), with gap and padding. sizes, one per shape along the direction: px, "N%", "Nfr" (share of the space left; default all "1fr") or "auto" (keep size). align across: stretch (default), start, center, end (cross_size sets their size). justify (when nothing is fr): start, center, end, space-between, space-around. Example: header row {"shapes": ["Logo", "Nav", "Account"], "into": "Header", "padding": [12, 24], "gap": 16, "sizes": [120, "1fr", 160]}. Contents of arranged rectangles move with them.

| Argument | Type | Description |
|---|---|---|
| `page` | integer or string | Page number (1 = first), name or id. Leave out for the page on screen. |
| `shapes` (required) | array of string | Shape ids or names. |
| `into` | string | "canvas" (default), "safe_area" (inside the margins) or a rectangle's id / name. |
| `direction` | `"row"` \\| `"column"` |  |
| `gap` | number |  |
| `padding` | number or array of number | px, [vertical, horizontal] or [top, right, bottom, left] |
| `sizes` | array of number or string |  |
| `align` | `"stretch"` \\| `"start"` \\| `"center"` \\| `"end"` |  |
| `cross_size` | number or string | Pixels, or "N%" of the frame. |
| `justify` | `"start"` \\| `"center"` \\| `"end"` \\| `"space-between"` \\| `"space-around"` |  |
| `carry` | boolean | Shapes inside a moved rectangle move with it (default true). |

#### `grid`

Put shapes in a grid inside a container, row by row: columns, gap (px or [x, y]), padding, and row height (row_height px / "N%", or aspect = width / height of each cell; default: rows share the height). Good for card grids, galleries, tiles.

| Argument | Type | Description |
|---|---|---|
| `page` | integer or string | Page number (1 = first), name or id. Leave out for the page on screen. |
| `shapes` (required) | array of string | Shape ids or names. |
| `into` | string | "canvas" (default), "safe_area" (inside the margins) or a rectangle's id / name. |
| `columns` (required) | integer |  |
| `gap` | number or array of number |  |
| `padding` | number or array of number |  |
| `row_height` | number or string | Pixels, or "N%" of the frame. |
| `aspect` | number |  |
| `carry` | boolean | Shapes inside a moved rectangle move with it (default true). |

#### `align`

Line shapes up by an edge or centre: left, right, top, bottom, center_x, center_y. to: "together" (default: their combined box), "canvas", "safe_area" or a shape. E.g. centre a dialog: {"shapes": ["Dialog"], "edge": "center_x", "to": "canvas"}.

| Argument | Type | Description |
|---|---|---|
| `page` | integer or string | Page number (1 = first), name or id. Leave out for the page on screen. |
| `shapes` (required) | array of string | Shape ids or names. |
| `edge` (required) | `"left"` \\| `"right"` \\| `"top"` \\| `"bottom"` \\| `"center_x"` \\| `"center_y"` |  |
| `to` | string | "canvas" (default), "safe_area" (inside the margins) or a rectangle's id / name. |
| `carry` | boolean | Shapes inside a moved rectangle move with it (default true). |

#### `distribute`

Space shapes evenly along x or y (keeping the first and last where they are), or with an exact gap from the first.

| Argument | Type | Description |
|---|---|---|
| `page` | integer or string | Page number (1 = first), name or id. Leave out for the page on screen. |
| `shapes` (required) | array of string | Shape ids or names. |
| `axis` | `"x"` \\| `"y"` |  |
| `gap` | number |  |
| `carry` | boolean | Shapes inside a moved rectangle move with it (default true). |

### Design templates

#### `list_templates` (read-only)

The saved design templates (the Design tab's styles: fill, border, corners, line dash). Use one on a shape with "template": "<name>" in create_shapes / update_shapes, so the same kind of element looks the same everywhere.

No arguments.

#### `save_template`

Save a design template the user can also pick in the Design tab: from: a shape to copy its style, and / or the fields fill, stroke, stroke_width, radius, line_style, cap. Good for a small style kit: "Primary button", "Card", "Divider". overwrite: true replaces one of that name.

| Argument | Type | Description |
|---|---|---|
| `name` (required) | string |  |
| `from` | string | Shape id or exact name. |
| `page` | integer or string | Page number (1 = first), name or id. Leave out for the page on screen. |
| `fill` | string or null | Hex "#RRGGBB" (or "#AARRGGBB", alpha first); null for none. |
| `stroke` | string or null | Hex "#RRGGBB" (or "#AARRGGBB", alpha first); null for none. |
| `stroke_width` | number |  |
| `radius` | number |  |
| `line_style` | `"solid"` \\| `"dash"` \\| `"dot"` |  |
| `cap` | `"round"` \\| `"flat"` \\| `"square"` |  |
| `overwrite` | boolean |  |

### Pages and project

#### `add_page`

Add a page (a screen). Size from preset (list_presets: e.g. "iPhone 16 Pro", "Full HD 1920 x 1080") or width + height; orientation portrait / landscape. copy_of copies a page with its shapes. It opens on screen unless show: false. Also takes the update_page settings.

| Argument | Type | Description |
|---|---|---|
| `name` | string |  |
| `notes` | string |  |
| `preset` | string |  |
| `width` | integer |  |
| `height` | integer |  |
| `orientation` | `"portrait"` \\| `"landscape"` |  |
| `copy_of` | integer or string | Page number (1 = first), name or id. Leave out for the page on screen. |
| `after` | integer or string | Page number (1 = first), name or id. Leave out for the page on screen. |
| `show` | boolean |  |
| `background` | string or null | Hex "#RRGGBB" (or "#AARRGGBB", alpha first); null for none. |
| `margins` | number or array of number |  |
| `keep_inside` | boolean |  |
| `show_margins` | boolean |  |
| `dots` | boolean |  |
| `dot_spacing` | integer | Dot grid spacing, px: 1 (finest) to 400. Dot snapping and arrow keys move in this step. |

#### `update_page`

Change a page: name, notes (what this screen is), size (preset / width / height / orientation), background, margins (px or [top, right, bottom, left]), keep_inside (shapes kept inside the margins), show_margins, dots, dot_spacing, position (move it to that page number). Shapes keep their pixel positions when the size changes.

| Argument | Type | Description |
|---|---|---|
| `page` | integer or string | Page number (1 = first), name or id. Leave out for the page on screen. |
| `name` | string |  |
| `notes` | string |  |
| `preset` | string |  |
| `width` | integer |  |
| `height` | integer |  |
| `orientation` | `"portrait"` \\| `"landscape"` |  |
| `background` | string or null | Hex "#RRGGBB" (or "#AARRGGBB", alpha first); null for none. |
| `margins` | number or array of number |  |
| `keep_inside` | boolean |  |
| `show_margins` | boolean |  |
| `dots` | boolean |  |
| `dot_spacing` | integer | Dot grid spacing, px: 1 (finest) to 400. Dot snapping and arrow keys move in this step. |
| `position` | integer |  |

#### `delete_page` (destructive)

Delete a page and its shapes.

| Argument | Type | Description |
|---|---|---|
| `page` (required) | integer or string | Page number (1 = first), name or id. Leave out for the page on screen. |

#### `set_project`

Set the project name and the brief: what the product is, who it is for, style and rules for the building agent. append_brief adds a paragraph instead of replacing.

| Argument | Type | Description |
|---|---|---|
| `name` | string |  |
| `brief` | string |  |
| `append_brief` | string |  |

### Files

#### `open_project` (destructive)

Open a saved project by name (list_projects) or .uxandi path. Refuses when the open one has unsaved changes unless discard: true (or save_project first).

| Argument | Type | Description |
|---|---|---|
| `project` (required) | string |  |
| `discard` | boolean |  |

#### `new_project` (destructive)

Start a new project with one page. With a name it is saved at once as projects/<name>.uxandi. Optional preset / width / height / orientation for the first page, and brief.

| Argument | Type | Description |
|---|---|---|
| `name` | string |  |
| `brief` | string |  |
| `preset` | string |  |
| `width` | integer |  |
| `height` | integer |  |
| `orientation` | `"portrait"` \\| `"landscape"` |  |
| `discard` | boolean |  |

#### `save_project`

Save the project (projects/<name>.uxandi). name saves it under a new name (overwrite: true replaces an existing file). In file mode every change is saved already.

| Argument | Type | Description |
|---|---|---|
| `name` | string |  |
| `overwrite` | boolean |  |

#### `export_json`

Write the agent brief: exports/<project>/<project>.compact.ui.json (plus a dated copy in history/). Returns the path and how many elements still lack notes. The default compact form leaves out empty, default and derivable values (about 5x smaller, made for an LLM builder; how_to_read lists every default). compact: false writes the full form <project>.ui.json instead, every field written out (for code that parses it). include_json: true also returns the JSON. Formats: schema/ui.compact.schema.json, full: schema/ui.schema.json.

| Argument | Type | Description |
|---|---|---|
| `compact` | boolean | true (default): compact form. false: full form, every field written out. |
| `include_json` | boolean |  |

#### `import_export` (destructive)

Load a .ui.json export (full or compact) as a project and save it as projects/<name>.uxandi: round-trip a brief, or start from one another tool or agent wrote. file: a path, or a project name with a folder in exports/. name saves it under another name; overwrite: true replaces a project of that name. Refuses when the open project has unsaved changes unless discard: true.

| Argument | Type | Description |
|---|---|---|
| `file` (required) | string |  |
| `name` | string |  |
| `overwrite` | boolean |  |
| `discard` | boolean |  |

### Session

#### `select`

Show a page on the user's screen and select shapes there (to point something out). No shapes: just show the page.

| Argument | Type | Description |
|---|---|---|
| `page` | integer or string | Page number (1 = first), name or id. Leave out for the page on screen. |
| `shapes` | array of string | Shape ids or names. |

#### `history`

Undo or redo (action), steps times. Every command an agent sends is one step, like an edit by hand.

| Argument | Type | Description |
|---|---|---|
| `action` | `"undo"` \\| `"redo"` |  |
| `steps` | integer |  |

#### `batch`

Run many commands in order as ONE step: one undo, and all or nothing (if one fails, none of them is kept). calls: [{"tool": "create_shapes", "args": {...}}, {"tool": "arrange", "args": {...}}, ...]. Any build, page or project command can go in a batch; files, templates, history, select and screenshot cannot.

| Argument | Type | Description |
|---|---|---|
| `calls` (required) | array of object |  |

<!-- tool-reference:end -->
