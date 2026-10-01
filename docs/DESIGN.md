# Design & Visual Rules

## Brand palette (Cloudera)
| Token | Hex | Use |
|-------|-----|-----|
| Navy (dk) | `#100045` / `#120046` | headings, primary text |
| Orange (accent1) | `#FF550C` | primary accent, CTAs, takeaway highlight, bottom bar |
| Blue/violet (accent2) | `#5555F9` | secondary accent, sub-labels, links |
| Slate | `#5A5A72` | body/muted text |
| White | `#FFFFFF` | surfaces |

## Typography
- Decks / brand assets: **Plus Jakarta Sans** (headings + body), theme font **Arial**.
- App (frontend): Tailwind default sans stack; keep headings navy, accents orange.

## Slide deck (executive collateral)
`docs/aml-overview.pptx` is built on the **Cloudera "Agentic AI Bigger Picture (v5)"**
template so new slides drop straight into that deck: 16:9, brand squares top-right,
orange bottom bar + CLOUDERA logo, navy titles, orange "takeaway" line. Diagrams are
light-theme mermaid (`docs/diagrams/*.mmd` → `*.png`), regenerable via:
```bash
npx -p @mermaid-js/mermaid-cli mmdc -c /tmp/mmd-light.json -i docs/diagrams/aml-loop.mmd \
    -o docs/diagrams/aml-loop.png -b white -s 3 -w 1700
```
Everything else in the deck is native editable PowerPoint; only the diagrams are images.

## UI principles
- The application shell follows the `semantic-guardrails-cai/ui/sample` reference:
  white sidebar and top bar, pale workspace, navy headings, purple navigation and
  controls, and orange Cloudera branding. AML risk bands retain their own colors.
- Semantic context has three sections: brief account interpretation, one graph
  of declared Ossie dataset relationships, and optional source YAML. Selecting
  a node reveals its ontology meaning, essential fields, key function, physical
  source and linked datasets. A dashed implementation link shows how PDF/OCR
  evidence is indexed in LanceDB and retrieved into a case. Solid arrows are
  model joins, not a detected account network.
- Two dashboards, one visual language; risk expressed by band color (CRITICAL/HIGH/
  MEDIUM) alongside the recorded priority score.
- Fail-soft states are first-class: empty queue, no-LLM, CSV-fallback all render a
  clear message rather than an error.
- The frontend never talks to anything but `/api/*`.
