"""One-off generator for `cid_gallup_2027_march.pdf` (test fixture).

Run with:  uv run python pipeline/parsers/fixtures/build_cid_gallup_fixture.py

reportlab is intentionally NOT a project dependency — install it with
`uv pip install reportlab` if you need to regenerate the fixture. The
committed PDF is what tests consume; this script exists only as
documentation for how the binary was produced.
"""

from __future__ import annotations

from pathlib import Path

from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

OUTPUT = Path(__file__).parent / "cid_gallup_2027_march.pdf"


def build() -> Path:
    c = canvas.Canvas(str(OUTPUT), pagesize=letter)
    c.setFont("Helvetica-Bold", 14)
    c.drawString(72, 740, "CID Gallup")
    c.setFont("Helvetica", 11)
    c.drawString(72, 720, "Encuesta de intención de voto presidencial - Guatemala 2027")

    body = [
        ("", 700),
        ("Metodología: Encuesta nacional cara a cara, muestreo estratificado", 685),
        ("multi-etápico con cuotas por sexo y edad. Cobertura urbana y rural en", 670),
        ("los 22 departamentos. Margen de error +/- 2.8% al 95% de confianza.", 655),
        ("", 640),
        ("Trabajo de campo: 12 al 16 de marzo de 2027", 625),
        ("Tamaño de la muestra: n = 1,200 personas", 610),
        ("", 595),
        ("Intención de voto presidencial (%):", 580),
        ("", 565),
    ]
    for line, y in body:
        c.drawString(72, y, line)

    # Candidate rows — two-column-ish layout with multiple spaces between name and share
    # so the regex anchors on the wide gap.
    rows = [
        ("Bernardo Arévalo de León", 36.5, 2.8),
        ("Sandra Torres", 22.1, 2.8),
        ("Zury Ríos", 12.7, 2.8),
        ("Edmond Mulet", 9.4, 2.8),
        ("Manuel Conde", 6.2, 2.8),
        ("Otros", 8.0, None),
        ("No sabe / No responde", 5.1, None),
    ]
    y = 545
    for name, share, moe in rows:
        moe_text = f"  ± {moe:.1f}%" if moe is not None else ""
        c.drawString(72, y, f"{name}   {share:.1f}%{moe_text}")
        y -= 18

    c.setFont("Helvetica-Oblique", 9)
    c.drawString(72, y - 24, "Fuente: CID Gallup. Para uso de Prensa Libre. Marzo 2027.")
    c.showPage()
    c.save()
    return OUTPUT


if __name__ == "__main__":
    out = build()
    print(f"Wrote {out} ({out.stat().st_size} bytes)")
