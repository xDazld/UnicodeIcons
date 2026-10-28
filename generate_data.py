#!/usr/bin/env python3
"""Generate the Glyphify catalog from Unicode, UTN #36, and X11 Compose data."""

from __future__ import annotations

import json
import re
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
UNICODE_BASE = "https://www.unicode.org/Public/UCD/latest/ucd/"
SOURCES = {
    "UnicodeData.txt": UNICODE_BASE + "UnicodeData.txt",
    "Blocks.txt": UNICODE_BASE + "Blocks.txt",
    "Categories.txt": "https://www.unicode.org/notes/tn36/Categories.txt",
    "emoji-data.txt": UNICODE_BASE + "emoji/emoji-data.txt",
}
COMPOSE_PATH = Path("/usr/share/X11/locale/en_US.UTF-8/Compose")

EXCLUDED_NAMES = (
    "COMBINING",
    "VARIATION SELECTOR",
    "MODIFIER",
    "ZERO WIDTH",
    "JOINER",
    "CANCEL TAG",
    "TAG ",
    "KEYCAP",
    "CONTROL",
)

SOURCE_RANGES = (
    (0x2190, 0x21FF),
    (0x27F0, 0x27FF),
    (0x2900, 0x297F),
    (0x2B00, 0x2BFF),
    (0x20A0, 0x20CF),
    (0x2100, 0x214F),
    (0x2150, 0x218F),
    (0x2200, 0x22FF),
    (0x2300, 0x23FF),
    (0x2460, 0x24FF),
    (0x2500, 0x259F),
    (0x25A0, 0x25FF),
    (0x2600, 0x26FF),
    (0x2700, 0x27BF),
    (0x27C0, 0x27EF),
    (0x2980, 0x29FF),
    (0x2A00, 0x2AFF),
    (0x1D100, 0x1D1FF),
    (0x2669, 0x266F),
    (0x1F000, 0x1FAFF),
    (0x1FB00, 0x1FBFF),
    (0x1CC00, 0x1CEBF),
    (0x13000, 0x1342F),
)

def fetch(name: str) -> str:
    request = urllib.request.Request(SOURCES[name], headers={"User-Agent": "Glyphify data generator"})
    with urllib.request.urlopen(request) as response:
        return response.read().decode("utf-8")


def parse_unicode_data(text: str) -> dict[int, str]:
    entries: dict[int, str] = {}
    pending: tuple[int, str] | None = None
    for line in text.splitlines():
        fields = line.split(";")
        codepoint, name = int(fields[0], 16), fields[1]
        if name.endswith(", First"):
            pending = (codepoint, name[:-7])
        elif name.endswith(", Last") and pending:
            start, base_name = pending
            for value in range(start, codepoint + 1):
                entries[value] = base_name
            pending = None
        else:
            entries[codepoint] = name
    return entries


def parse_blocks(text: str) -> list[tuple[int, int, str]]:
    blocks = []
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if not line or ";" not in line:
            continue
        span, name = (part.strip() for part in line.split(";", 1))
        start, end = (int(value, 16) for value in span.split(".."))
        blocks.append((start, end, name))
    return blocks


def parse_categories(text: str) -> dict[int, list[str]]:
    categories = {}
    for line in text.splitlines():
        fields = line.split("\t")
        if len(fields) >= 7:
            categories[int(fields[0], 16)] = fields
    return categories


def parse_emoji_presentation(text: str) -> set[int]:
    codepoints = set()
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if not line or ";" not in line:
            continue
        span, property_name = (part.strip() for part in line.split(";", 1))
        if property_name != "Emoji_Presentation":
            continue
        start, _, end = span.partition("..")
        first = int(start, 16)
        last = int(end, 16) if end else first
        codepoints.update(range(first, last + 1))
    return codepoints


def block_for(codepoint: int, blocks: list[tuple[int, int, str]]) -> str:
    return next((name for start, end, name in blocks if start <= codepoint <= end), "Unassigned")


def family_for(block: str) -> str:
    aliases = {
        "Supplemental Arrows-A": "Arrows",
        "Supplemental Arrows-B": "Arrows",
        "Supplemental Arrows-C": "Arrows",
        "Supplemental Mathematical Operators": "Mathematical Operators",
        "Supplemental Symbols and Pictographs": "Symbols and Pictographs",
        "Symbols and Pictographs Extended-A": "Symbols and Pictographs",
        "Symbols for Legacy Computing Supplement": "Symbols for Legacy Computing",
        "Enclosed Alphanumeric Supplement": "Enclosed Alphanumerics",
    }
    if block in aliases:
        return aliases[block]
    return re.sub(r"-[A-C]$| Extended$", "", block)


def semantic_for(fields: list[str] | None, block: str) -> str:
    """Return the most specific UTN #36 category available for a character."""
    if not fields:
        return "Uncategorized"
    for value in fields[3:6]:
        if value:
            return {
                "Currency": "Currency Symbols",
            }.get(value, value)
    return {
        "Currency": "Currency Symbols",
    }.get(fields[2], fields[2]) or "Uncategorized"


def plural_candidates(label: str) -> list[str]:
    if label.endswith("y") and len(label) > 1:
        return [f"{label[:-1]}ies"]
    if label.endswith(("s", "x", "ch", "sh")):
        return [f"{label}es"]
    return [f"{label}s"]


def normalize_semantic_labels(catalog: list[list[object]]) -> None:
    labels = {str(item[2]) for item in catalog} | {str(item[5]) for item in catalog}
    aliases = {}
    for label in labels:
        candidates = []
        if not label.endswith(" Symbols"):
            candidates.append(f"{label} Symbols")
        candidates.extend(plural_candidates(label))
        target = next((candidate for candidate in candidates if candidate in labels), None)
        if target:
            aliases[label] = target
    for item in catalog:
        label = aliases.get(str(item[2]), str(item[2]))
        item[2] = label
        item[6] = label


def parse_compose() -> dict[str, list[str]]:
    if not COMPOSE_PATH.is_file():
        return {}
    outputs: dict[str, list[str]] = {}
    for line in COMPOSE_PATH.read_text(errors="replace").splitlines():
        if not line.lstrip().startswith("<Multi_key>") or ":" not in line:
            continue
        left, right = line.split(":", 1)
        match = re.search(r'"((?:\\.|[^"\\])*)"', right)
        if not match:
            continue
        try:
            value = json.loads(f'"{match.group(1)}"')
        except json.JSONDecodeError:
            continue
        keys = re.findall(r"<([^>]+)>", left)
        if len(keys) < 2:
            continue
        label = "Compose + " + " + ".join(key.replace("_", " ") for key in keys[1:])
        if label not in outputs.setdefault(value, []):
            outputs[value].append(label)
    return outputs


def build_catalog() -> tuple[list[list[object]], list[list[str]]]:
    unicode_data = parse_unicode_data(fetch("UnicodeData.txt"))
    blocks = parse_blocks(fetch("Blocks.txt"))
    categories = parse_categories(fetch("Categories.txt"))
    emoji_presentation = parse_emoji_presentation(fetch("emoji-data.txt"))
    compose = parse_compose()
    catalog: list[list[object]] = []
    seen: set[str] = set()

    for start, end in SOURCE_RANGES:
        for codepoint in range(start, end + 1):
            name = unicode_data.get(codepoint)
            if not name or name.startswith("<") or any(token in name for token in EXCLUDED_NAMES):
                continue
            character = chr(codepoint)
            code = f"U+{codepoint:04X}"
            if code in seen:
                continue
            block = block_for(codepoint, blocks)
            semantic = semantic_for(categories.get(codepoint), block)
            catalog.append([
                character,
                name.lower().replace("-", "-"),
                semantic,
                code,
                block,
                family_for(block),
                semantic,
                compose.get(character, []),
                block == "Egyptian Hieroglyphs",
                codepoint in emoji_presentation,
            ])
            seen.add(code)

    normalize_semantic_labels(catalog)
    catalog.sort(key=lambda item: (str(item[5]), str(item[1]), str(item[3])))
    visible_catalog = [item for item in catalog if not item[8] and not item[9]]
    all_representative = str(visible_catalog[0][0])
    semantic_options = [["all", all_representative, "Colorable glyphs", "all", "all"]]
    semantic_labels = []
    semantic_representatives = {}
    semantic_blocks = {}
    for item in visible_catalog:
        label = str(item[2])
        if label == "Uncategorized":
            continue
        if label not in semantic_labels:
            semantic_labels.append(label)
            semantic_representatives[label] = str(item[0])
            semantic_blocks[label] = set()
        semantic_blocks[label].add(str(item[4]))
    for label in semantic_labels:
        if semantic_blocks[label] == {"Egyptian Hieroglyphs"}:
            continue
        semantic_options.append([
            f"meaning:{label}",
            semantic_representatives[label],
            label,
            "semantic",
            label,
        ])

    families = []
    family_representatives = {}
    for item in visible_catalog:
        family = str(item[5])
        if family not in families:
            families.append(family)
            family_representatives[family] = str(item[0])

    options = semantic_options[:]
    for family in families:
        if family == "Arrows":
            option_index = next((index for index, option in enumerate(options) if option[2] == "Arrows"), None)
            if option_index is not None:
                options[option_index] = ["union:Arrows", family_representatives[family], "Arrows", "union", ["Arrows", "Arrows"]]
        elif family == "Symbols":
            option_index = next((index for index, option in enumerate(options) if option[2] == "Symbols"), None)
            if option_index is not None:
                options[option_index] = ["union:Symbols", family_representatives[family], "Symbols", "union", ["Symbols", "Symbols"]]
        elif family not in {option[2] for option in options}:
            options.append([f"block:{family}", family_representatives[family], family, "block", family])
    return catalog, options


RUNTIME = r'''const glyphs = __GLYPHS__;
const sidebarOptions = __OPTIONS__;
const grid = document.querySelector("#glyph-grid");
const searchInput = document.querySelector("#search");
const count = document.querySelector("#result-count");
const title = document.querySelector("#collection-title");
const empty = document.querySelector("#empty-state");
const toast = document.querySelector("#toast");
const dialog = document.querySelector("#glyph-dialog");
const dialogGlyph = document.querySelector("#dialog-glyph");
const dialogName = document.querySelector("#dialog-name");
const dialogMeta = document.querySelector("#dialog-meta");
const sortSelect = document.querySelector("#sort-select");
let activeCategory = "all";
const favorites = new Set();
const renderProbe = document.createElement("canvas");
renderProbe.width = 64;
renderProbe.height = 64;
const renderContext = renderProbe.getContext("2d", { willReadFrequently: true });
renderContext.font = "48px serif";
renderContext.textAlign = "center";
renderContext.textBaseline = "middle";
const missingGlyphBitmap = (() => {
  renderContext.clearRect(0, 0, renderProbe.width, renderProbe.height);
  renderContext.fillText("\u{10FFFF}", renderProbe.width / 2, renderProbe.height / 2);
  return new Uint32Array(renderContext.getImageData(0, 0, renderProbe.width, renderProbe.height).data.buffer);
})();
function canRenderGlyph(glyph) {
  renderContext.clearRect(0, 0, renderProbe.width, renderProbe.height);
  renderContext.fillText(glyph, renderProbe.width / 2, renderProbe.height / 2);
  const bitmap = new Uint32Array(renderContext.getImageData(0, 0, renderProbe.width, renderProbe.height).data.buffer);
  return bitmap.some((pixel, index) => pixel !== missingGlyphBitmap[index]);
}
const renderableGlyphs = glyphs.filter((item) => canRenderGlyph(item[0]) && !item[8] && !item[9]);
function categoryMatches(item, option) {
  const [, , category, , , blockFamily] = item;
  const [, , , kind, value] = option;
  if (kind === "all") return true;
  if (kind === "union") return category === value[0] || blockFamily === value[1];
  if (kind === "semantic") return category === value;
  return blockFamily === value;
}
function categoryIcon(option) {
  return renderableGlyphs.find((item) => categoryMatches(item, option))[0];
}
const visibleSidebarOptions = sidebarOptions.filter((option) => option[2] !== "Uncategorized" && renderableGlyphs.some((item) => categoryMatches(item, option)));
function renderCategories() {
  document.querySelector("#category-list").innerHTML = visibleSidebarOptions.map((option) => `<button class="category-button ${option[0] === activeCategory ? "active" : ""}" data-category="${option[0]}" type="button"><span class="category-icon">${categoryIcon(option)}</span><span>${option[2]}</span></button>`).join("");
  document.querySelectorAll(".category-button").forEach((button) => button.addEventListener("click", () => { activeCategory = button.dataset.category; renderCategories(); renderGlyphs(); }));
}
function visibleGlyphs() {
  const query = searchInput.value.trim().toLowerCase();
  const active = visibleSidebarOptions.find(([id]) => id === activeCategory);
  return renderableGlyphs.filter((item) => {
    const [, name, category, code, block, blockFamily, , composeSequences] = item;
    const matchesActiveCategory = activeCategory === "all" ? true : categoryMatches(item, active);
    const composeText = composeSequences.join(" ").toLowerCase();
    return matchesActiveCategory && (!query || name.includes(query) || category.toLowerCase().includes(query) || block.toLowerCase().includes(query) || blockFamily.toLowerCase().includes(query) || code.toLowerCase().includes(query) || composeText.includes(query));
  });
}
function renderGlyphCard(item) {
  const [glyph, name, , code, , , , composeSequences] = item; const key = `${glyph}-${code}`;
  const composeMarkup = composeSequences.length ? `<div class="compose-hints"><span>Compose</span>${composeSequences.map((sequence) => `<div>${sequence.replace("Compose + ", "")}</div>`).join("")}</div>` : "";
  return `<article class="glyph-card ${favorites.has(key) ? "favorite" : ""}" data-index="${glyphs.indexOf(item)}" title="${code}"><button class="favorite-button" type="button" aria-label="Favorite ${name}">${favorites.has(key) ? "♥" : "♡"}</button><div class="glyph">${glyph}</div><div class="glyph-name">${name}</div>${composeMarkup}</article>`;
}
function renderGlyphs() {
  const items = visibleGlyphs().sort((a, b) => {
    if (sortSelect.value === "code") return a[3].localeCompare(b[3], undefined, { numeric: true });
    if (sortSelect.value === "glyph") return a[0].localeCompare(b[0]);
    return a[1].localeCompare(b[1]);
  }); const option = visibleSidebarOptions.find(([id]) => id === activeCategory);
  title.firstChild.textContent = `${option[2]} `; count.textContent = items.length.toLocaleString(); empty.hidden = items.length > 0;
  grid.innerHTML = items.map(renderGlyphCard).join("");
  grid.querySelectorAll(".glyph-card").forEach((card) => {
    card.addEventListener("click", (event) => { if (!event.target.closest(".favorite-button")) { const item = glyphs[Number(card.dataset.index)]; copyGlyph(item[0], item[1], item[3]); } });
    card.querySelector(".favorite-button").addEventListener("click", () => { const item = glyphs[Number(card.dataset.index)]; const key = `${item[0]}-${item[3]}`; favorites.has(key) ? favorites.delete(key) : favorites.add(key); renderGlyphs(); });
  });
}
function openDetails(item) {
  const [glyph, name, category, code, block, family, , composeSequences] = item;
  dialogGlyph.textContent = glyph;
  dialogName.textContent = name;
  dialogMeta.textContent = `${code} · ${block} · ${category}${family !== block ? ` · ${family}` : ""}${composeSequences.length ? ` · ${composeSequences.join(", ")}` : ""}`;
  dialog.dataset.glyph = glyph;
  dialog.dataset.code = code;
  dialog.showModal();
}
async function copyGlyph(glyph, name, code) { try { await navigator.clipboard.writeText(glyph); toast.textContent = `${glyph}  ${name} · ${code} copied`; } catch { toast.textContent = `${glyph}  ${name} · ${code}`; } toast.classList.add("show"); clearTimeout(copyGlyph.timeout); copyGlyph.timeout = setTimeout(() => toast.classList.remove("show"), 1800); }
document.querySelector("#copy-character").addEventListener("click", () => copyGlyph(dialog.dataset.glyph, dialogName.textContent, dialog.dataset.code));
document.querySelector("#copy-code").addEventListener("click", () => copyText(dialog.dataset.code));
async function copyText(value) { try { await navigator.clipboard.writeText(value); toast.textContent = `${value} copied`; } catch { toast.textContent = value; } toast.classList.add("show"); clearTimeout(copyText.timeout); copyText.timeout = setTimeout(() => toast.classList.remove("show"), 1800); }
document.querySelector("#dialog-close").addEventListener("click", () => dialog.close());
dialog.addEventListener("click", (event) => { if (event.target === dialog) dialog.close(); });
document.addEventListener("keydown", (event) => { if (event.key === "Escape" && dialog.open) dialog.close(); });
searchInput.addEventListener("input", renderGlyphs);
sortSelect.addEventListener("change", renderGlyphs);
document.querySelector("#random-button").addEventListener("click", () => { const items = visibleGlyphs(); if (items.length) { const item = items[Math.floor(Math.random() * items.length)]; copyGlyph(item[0], item[1], item[3]); } });
document.addEventListener("keydown", (event) => { if (event.key === "/" && document.activeElement !== searchInput) { event.preventDefault(); searchInput.focus(); } });
document.querySelector(".eyebrow").innerHTML = `<span class="pulse"></span> ${renderableGlyphs.length.toLocaleString()} colorable glyphs grouped by meaning and Unicode family`;
renderCategories(); renderGlyphs();
'''


def main() -> None:
    catalog, options = build_catalog()
    output = RUNTIME.replace("__GLYPHS__", json.dumps(catalog, ensure_ascii=False, separators=(",", ":")))
    output = output.replace("__OPTIONS__", json.dumps(options, ensure_ascii=False, separators=(",", ":")))
    (ROOT / "script.js").write_text(
        "/* Generated by generate_data.py from UnicodeData.txt, Blocks.txt, UTN #36 Categories.txt, and X11 Compose. */\n"
        + output,
        encoding="utf-8",
    )
    included = sum(not bool(item[8]) and not bool(item[9]) for item in catalog)
    print(f"Generated script.js: {len(catalog)} catalog entries ({included} colorable glyphs), {len(options) - 1} filters.")


if __name__ == "__main__":
    main()
