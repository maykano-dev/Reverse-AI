# Interactive surfaces

ReverseAI can create task-native interfaces inside the conversation. A surface is
validated data, not arbitrary HTML. The browser renders allowlisted blocks; custom
HTML is the only escape hatch and runs in an opaque-origin iframe with no network.

## Why

A decision, comparison, graph, diff, approval, or form is often clearer than a
paragraph. The agent should be able to build the interface the task needs and then
continue from the user's interaction.

## Surface model

```json
{
  "id": "sf_...",
  "kind": "question | form | dashboard | review | approval | progress | workspace | custom",
  "title": "Which path should I take?",
  "description": "The evidence supports two strategies.",
  "blocks": [
    {
      "kind": "choice",
      "label": "Choose a strategy",
      "options": [
        {"value": "patch", "label": "Patch the existing function",
         "description": "Smallest change", "recommended": true, "risk": "low"},
        {"value": "rebuild", "label": "Rebuild the module",
         "description": "Larger change", "risk": "high"}
      ],
      "allow_other": true
    }
  ],
  "actions": [
    {"id": "continue", "label": "Continue", "kind": "submit"},
    {"id": "cancel", "label": "Cancel", "kind": "cancel"}
  ]
}
```

Question, form, and approval surfaces wait by default: the turn ends with
`awaiting_input` and the next turn is the user's structured response. Set
`"wait": false` for a dashboard or review surface that should not pause.

Every choice block has an **Other - type your own** path by default. A form can
collect free text, numbers, selects, checkboxes, and files. The surface can also
include a table, bar/line/pie chart, node/edge graph, before/after diff, code,
progress bar, approval card, file drop, or a sandboxed custom view.

## Flow

```
agent -> create_surface -> SSE "surface" event -> browser renders
                                                   |
                                            user interacts
                                                   |
                          POST .../surfaces/<id>/respond
                                                   |
                        event recorded + agent continues the turn
```

The event is structured. The next turn receives a clear message containing the
surface id, action, selected values, and free-form "Other" text. The record is
persisted on the Job (`surfaces`) and the event is stored under
`<store>/surface_events/`.

## Endpoints

```
GET  /jobs/<id>/surfaces
POST /jobs/<id>/surfaces/<surface>/events
POST /jobs/<id>/surfaces/<surface>/respond
```

`/events` records the interaction without starting a model turn. `/respond` does
the same and starts a continuation in the same conversation. Both validate the
surface and action id, and both go through normal authentication and path rules.

## Safety

- The model proposes; the server validates every block and bound.
- Custom HTML runs in `<iframe sandbox="allow-scripts">` without
  `allow-same-origin`, with a CSP that blocks network, frames, and external assets.
- Approval buttons are not authority. The actual tool/approval gate still decides.
- No secrets are placed in surface data.
- Surfaces are attached to a specific job; events are job-scoped.
- The text answer remains a fallback if the browser cannot render the surface.

## Tests

```bash
python3 -m unittest tests.test_surfaces tests.test_surface_ui -v
```

`test_surfaces` covers validation, the agent tool, job persistence, the event
endpoint, and conversation continuation. `test_surface_ui` covers the renderer
vocabulary, the "Other" path, and the sandboxed custom view.
