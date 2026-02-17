from __future__ import annotations

DEFAULT_MODEL_NAME = "Translator"
DEFAULT_MODEL_FIELDS = [
    "word",
    "translation",
    "example_en",
    "definitions_en",
]

DEFAULT_FRONT_TEMPLATE = """
<div class="eng">{{word}}</div>

{{#example_en}}
  <div class="ex ex-en">{{example_en}}</div>
{{/example_en}}
""".strip()

DEFAULT_BACK_TEMPLATE = """
{{FrontSide}}

<hr id="answer">

<div class="ru">{{translation}}</div>

{{#definitions_en}}
  <div class="defs-block">{{definitions_en}}</div>
{{/definitions_en}}
""".strip()

DEFAULT_MODEL_CSS = """
.card {
  font-family: Arial, sans-serif;
  font-size: 22px;
  line-height: 1.35;
  text-align: center;
  color: #111;
  background: #fff;
}

.eng {
  font-size: 34px;
  font-weight: 700;
  margin-bottom: 10px;
}

.ru {
  font-size: 28px;
  font-weight: 600;
  margin-bottom: 12px;
  line-height: 1.35;
  text-align: left;
}

.ex {
  margin-top: 10px;
  padding: 10px 12px;
  border-left: 4px solid #ccc;
  background: rgba(0, 0, 0, 0.04);
  font-size: 20px;
  text-align: center;
  border-left: none;
  border-top: 4px solid #ccc;
  display: inline-block;
  max-width: 90%;
}

.defs-block {
  margin-top: 12px;
  padding: 10px 12px;
  font-size: 18px;
  line-height: 1.4;
  text-align: left;
  border-left: 3px solid #8a8f9a;
  background: rgba(255, 255, 255, 0.03);
}

.hl,
mark {
  background: #fff4a8;
  color: inherit;
  border-radius: 3px;
  padding: 0 0.08em;
}

#answer {
  margin: 18px 0;
  text-align: center;
}
""".strip()
