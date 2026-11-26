# Uxandi for AI agents

29 tools. MCP server and command line. Server `uxandi_agent.py`: Python standard library only.

- [TOOLS.md](TOOLS.md): every tool, arguments, behaviour, runnable recipes
- [schema/](schema/): JSON Schemas for export, compact export, project file, Design templates. `tools.json`: every tool's input schema

## Modes

Picked automatically.

| | App open (`python main.py`) | App closed |
|---|---|---|
| Mode | live | file |
| Commands run | In the open window | On the project files |
| User sees | Every change live. Status bar: `Agent: ...` | Result on next app start |
| Undo | One Ctrl+Z step per command | `history` tool, while the server runs |
| Saving | As by hand: Save or `save_project` | Every change, at once |

File mode: project open last in the app, or the one from `open_project`.

## Connect

Command for every client: `python uxandi_agent.py mcp`

- `python` not found: `python3`
- venv: `.venv\Scripts\python.exe` (Windows), `.venv/bin/python` (macOS / Linux)
- App open: any Python 3.9+. File mode: PySide6 too

| Client | Setup |
|---|---|
| Claude Code | `.mcp.json` included. Open folder with `claude`, approve `uxandi`. By hand: `claude mcp add uxandi -- python uxandi_agent.py mcp` |
| VS Code (Copilot agent mode), Cursor | `.vscode/mcp.json`, `.cursor/mcp.json` included. Enable `uxandi` |
| Claude Desktop | Settings > Developer > Edit Config. Add block below. Restart |
| OpenAI Codex CLI | `~/.codex/config.toml`, block below |
| Other MCP clients | stdio, command `python`, args `["/path/to/UxandIDesign/uxandi_agent.py", "mcp"]` |

`claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "uxandi": {
      "command": "python",
      "args": ["C:/path/to/UxandIDesign/uxandi_agent.py", "mcp"]
    }
  }
}
```

`~/.codex/config.toml`:

```toml
[mcp_servers.uxandi]
command = "python"
args = ["/path/to/UxandIDesign/uxandi_agent.py", "mcp"]
```

### Command line, no MCP

```
python uxandi_agent.py guide                     usage guide
python uxandi_agent.py tools                     tools + arguments
python uxandi_agent.py call get_status
python uxandi_agent.py call get_page '{"page": 1}'
python uxandi_agent.py call create_shapes @shapes.json
python uxandi_agent.py call screenshot '{"page": 1}' --out page.png
python uxandi_agent.py validate exports/Shop/Shop.compact.ui.json   check file against schema
python uxandi_agent.py schema                    regenerate schema/ + TOOLS.md reference
```

- Output: JSON
- Failure: `{"error": "..."}` with the fix, exit code 1

## Tools

| Group | Tools |
|---|---|
| Read | `get_status` (start here), `get_page`, `screenshot`, `check_layout`, `list_presets`, `list_projects` |
| Build | `create_shapes`, `update_shapes`, `delete_shapes`, `duplicate_shapes` (with children, to other pages), `set_group` |
| Layout | `arrange` (flex-like rows / columns), `grid`, `align`, `distribute` |
| Design templates | `list_templates`, `save_template`. Shapes take one via `"template"` |
| Pages and project | `add_page`, `update_page`, `delete_page`, `set_project` (name, brief) |
| Files | `open_project`, `new_project`, `save_project`, `export_json`, `import_export` |
| Session | `select` (point at shapes), `history` (undo / redo), `batch` (many commands, one step) |

- Full details: each tool's description, `python uxandi_agent.py tools`, [TOOLS.md](TOOLS.md)
- MCP resources: `uxandi://guide`, `uxandi://reference/tools`, `uxandi://schema/<file>`
- MCP prompts: `design_screen`, `design_flow`, `review_layout`, `prepare_handoff`

## Build rules

1. Containers only. No text element. Heading, label, button: rectangle. Avatar, round button, dot: `"kind": "circle"` (or `"ellipse"`). Freehand mark: `"kind": "path"` + `points`, never a container. `name`: what it is. `notes`: what it shows and does. Builder reads only names, notes, boxes, styles
2. Real screen sizes: device preset per page (`list_presets`). Project `brief`, page `notes`
3. Outside in: regions first, then children via `"in": "<parent>"`. `x` / `y` / `w` / `h` then relative to the parent. Positions: px, `"N%"`, `"start"` / `"center"` / `"end"` + offset (`"end-16"`)
4. Layout tools, no arithmetic
   - `arrange`: `gap`, `padding`, `sizes` like `[240, "1fr", "2fr"]`
   - `grid`: `columns`, `aspect`
   - `align`, `distribute`
   - Moving a container carries its contents
5. Build one, copy the rest: one card / row with children, `duplicate_shapes`, then `grid` / `arrange`. Child names after the container (`"Card 1 title"`), copies follow (`"Card 2 title"`). `to`: same nav bar on other pages
6. Same element, same look: `list_templates`, `"template"` on shapes, or `save_template` a kit
7. Batch multi-step builds: one undo step, all or nothing
8. Check, look, fix
   - `check_layout`: overlaps, past margins, 1-2 px near-misses, duplicate / generic names, missing notes
   - `screenshot`: page with shape names drawn on it
9. Export: `export_json` writes `exports/<project>/<project>.compact.ui.json`, compact form for an LLM builder. `{"compact": false}`: full form `<project>.ui.json`, every field written out. Format: [schema/ui.compact.schema.json](schema/ui.compact.schema.json), [schema/ui.schema.json](schema/ui.schema.json)
10. Live mode: user watching. `get_page` before changing shapes they may have moved. `select` to point

Example, phone header with three children in one step:

```json
{"tool": "batch", "args": {"calls": [
  {"tool": "create_shapes", "args": {"shapes": [
    {"name": "Header", "in": "safe_area", "x": 0, "y": 0, "w": "100%", "h": 96, "notes": "Top bar, stays on scroll."},
    {"name": "Back button", "in": "Header", "notes": "Chevron, goes to the previous screen."},
    {"name": "Screen title", "in": "Header", "notes": "Shows the product name, one line, centred."},
    {"name": "Share button", "in": "Header", "notes": "Opens the share sheet."}]}},
  {"tool": "arrange", "args": {"shapes": ["Back button", "Screen title", "Share button"], "into": "Header",
    "padding": [0, 16], "gap": 12, "sizes": [48, "1fr", 48], "align": "center", "cross_size": 48}}]}}
```

## Live bridge

- Listens on `127.0.0.1` only, never the network
- Port + random token in `data/bridge.json`. Git-ignored, removed on close
- `uxandi_agent.py` reads it to find the open app
- `UXANDI_BRIDGE=0`: bridge off
- `UXANDI_HOME=<folder>`: projects, exports, templates, data elsewhere

Protocol, one JSON line each way:

```
request   {"token": "...", "tool": "...", "args": {...}}
reply     {"ok": true, "result": {...}}  or  {"ok": false, "error": "..."}
```

## Tests

```
python tools/check_agent.py
```

- File mode, live bridge (offscreen app), MCP over stdio
- `schema/` and `TOOLS.md` reference in sync with the code
- Exports valid against the schemas
- Every `TOOLS.md` recipe
- Temporary folder only. Never touches your projects

After changing a tool: `python uxandi_agent.py schema`.
