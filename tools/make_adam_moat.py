"""Build vmi/data/adam_moat.md (verbatim moat extracts) from the owner's own copy of the course master document.
usage: python tools/make_adam_moat.py path/to/VMI_VERBATIM_MASTER_DOCUMENT.md
The output stays on this PC (it is in .gitignore): it is the owner's paid course material."""
import sys
from pathlib import Path

PARTS = [(2141, 2186, "STEP 3: THE ECONOMIC MOAT (lesson text)"),
         (1359, 1369, "PILLAR 5: WEAK COMPETITION, 'the most important one' (great business models lesson)"),
         (2351, 2354, "WORKED EXAMPLE: ALPHABET (wide moat, 9/10)"),
         (2439, 2456, "WORKED EXAMPLE: MICROSOFT"),
         (2562, 2572, "WORKED EXAMPLE: AMAZON"),
         (3214, 3222, "HOW A MOAT ERODES (and how it does not)")]    # line numbers of the 2026-11 near-verbatim master document

if __name__ == "__main__":
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.home() / "Downloads" / "MasterDocs" / "VMI_VERBATIM_MASTER_DOCUMENT.md"
    lines = src.read_text(encoding="utf-8").split("\n")
    out = ["Adam Khoo's own words from the course (verbatim extracts of the master document). Apply them as he does."]
    for a, b, title in PARTS:
        out.append(f"### {title}\n" + "\n".join(ln for ln in lines[a - 1:b] if ln.strip()))
    dest = Path(__file__).resolve().parents[1] / "vmi" / "data" / "adam_moat.md"
    dest.write_text("\n\n".join(out), encoding="utf-8")
    print(f"wrote {dest} ({dest.stat().st_size} bytes)")
