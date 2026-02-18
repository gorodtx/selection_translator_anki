from __future__ import annotations

DEFAULT_MODEL_NAME = "Translator"
DEFAULT_MODEL_FIELDS = [
    "word",
    "translation",
    "example_en",
    "definitions_en",
]

DEFAULT_FRONT_TEMPLATE = """
<div class="mc-card mc-front">
  <div class="mc-topline">Translator</div>
  <div class="mc-word">{{word}}</div>

  {{#example_en}}
    <div class="mc-block">
      <div class="mc-label">Examples</div>
      <div class="mc-examples">{{example_en}}</div>
    </div>
  {{/example_en}}
</div>
""".strip()

DEFAULT_BACK_TEMPLATE = """
<div class="mc-card mc-back">
  <div class="mc-topline">Translator</div>
  <div class="mc-word">{{word}}</div>

  <div class="mc-block">
    <div class="mc-label">Translation</div>
    <div class="mc-translation">{{translation}}</div>
  </div>

  {{#definitions_en}}
    <div class="mc-block">
      <div class="mc-label">Definitions</div>
      <div class="mc-definitions">{{definitions_en}}</div>
    </div>
  {{/definitions_en}}

  {{#example_en}}
    <div class="mc-block">
      <div class="mc-label">Examples</div>
      <div class="mc-examples">{{example_en}}</div>
    </div>
  {{/example_en}}
</div>
""".strip()

DEFAULT_MODEL_CSS = """
.nightMode.card,
.nightMode .card,
.card {
  --bg: #000000;
  --surface: #0b0b0b;
  --line: #232323;
  --text: #ececec;
  --muted: #a7a7a7;
  --accent: #cfcfcf;
  --highlight: transparent;
  margin: 0;
  padding: 18px 14px;
  font-family: "SF Pro Text", "Segoe UI", "Noto Sans", sans-serif;
  font-size: 21px;
  line-height: 1.45;
  color: var(--text);
  background: #000;
}

.mc-card {
  border: 1px solid var(--line);
  border-radius: 16px;
  background: var(--surface);
  padding: 16px;
  text-align: left;
  box-shadow: 0 8px 26px rgba(0, 0, 0, 0.45);
}

.mc-topline {
  font-size: 11px;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: var(--muted);
  font-weight: 700;
}

.mc-word {
  margin-top: 6px;
  margin-bottom: 10px;
  font-size: 36px;
  line-height: 1.15;
  font-weight: 800;
  color: #ffffff;
  text-wrap: balance;
}

.mc-block {
  margin-top: 12px;
  border: 1px solid var(--line);
  border-radius: 12px;
  padding: 10px 12px;
  background: #050505;
}

.mc-label {
  margin-bottom: 6px;
  font-size: 11px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--muted);
  font-weight: 700;
}

.mc-translation {
  font-size: 26px;
  line-height: 1.25;
  font-weight: 650;
  color: #f1f1f1;
}

.mc-examples {
  font-size: 18px;
  line-height: 1.45;
  text-align: left;
  white-space: normal;
}

.mc-definitions {
  font-size: 17px;
  line-height: 1.45;
  color: #d8d8d8;
}

.mc-definitions i {
  color: #d8d8d8;
}

.hl,
mark {
  background: transparent;
  color: inherit;
  font-weight: 800;
  border-radius: 0;
  padding: 0;
}

.mc-translation br,
.mc-examples br,
.mc-definitions br {
  content: "";
  display: block;
  margin-top: 0.22em;
}
""".strip()
