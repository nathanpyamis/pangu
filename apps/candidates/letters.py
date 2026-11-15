"""Endorsement letter PDF (ReportLab, A4). No system libraries needed."""
import io
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.platypus import Paragraph
from reportlab.lib.styles import ParagraphStyle

GREEN = colors.HexColor("#1F7A34")
GREEN_D = colors.HexColor("#0F5A2A")
GOLD = colors.HexColor("#E8B422")
RED = GREEN  # headings use the party green
INK = colors.HexColor("#111111")

body_style = ParagraphStyle("body", fontName="Helvetica", fontSize=11, leading=16,
                            textColor=INK)


def _para(c, text, x, y, width, style=body_style):
    p = Paragraph(text, style)
    _, h = p.wrap(width, 400 * mm)
    p.drawOn(c, x, y - h)
    return y - h


def endorsement_letter(app, party, signatory_name="", signatory_title="",
                       logo_path=None):
    """
    app    – CandidateApplication (status APPROVED, letter_number set)
    party  – PartyProfile (name, short_name, address, phone, email)
    Returns PDF bytes.
    """
    buf = io.BytesIO()
    from reportlab.pdfgen import canvas
    c = canvas.Canvas(buf, pagesize=A4)
    W, H = A4
    left, right = 22 * mm, W - 22 * mm
    width = right - left

    c.setTitle(f"Endorsement – {app.full_name}")
    c.setAuthor(party.name)

    # Letterhead: green-to-yellow horizontal gradient band (Pangu colours).
    band_h = 38 * mm
    c.saveState()
    p = c.beginPath()
    p.rect(0, H - band_h, W, band_h)
    c.clipPath(p, stroke=0, fill=0)
    c.linearGradient(0, H, W, H,
                     (GREEN_D, GREEN, colors.HexColor("#9AB52A"), GOLD),
                     (0, 0.4, 0.7, 1), extend=True)
    c.restoreState()
    c.setFillColor(GREEN_D)
    c.rect(0, H - band_h - 2 * mm, W, 2 * mm, stroke=0, fill=1)

    x_text = left
    if logo_path and Path(logo_path).exists():
        c.setFillColor(colors.white)
        c.roundRect(left, H - 34 * mm, 28 * mm, 28 * mm, 3 * mm, stroke=0, fill=1)
        c.drawImage(ImageReader(str(logo_path)), left + 1.5 * mm, H - 32.5 * mm, 25 * mm, 25 * mm,
                    preserveAspectRatio=True, mask="auto")
        x_text = left + 30 * mm
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 20)
    c.drawString(x_text, H - 18 * mm, party.name.upper())
    c.setFont("Helvetica-Bold", 9.5)
    c.setFillColor(colors.white)
    c.drawString(x_text, H - 24 * mm, (party.tagline or "")[:90])
    c.setFillColor(colors.white)
    contact = " · ".join(v for v in (party.address, party.phone, party.email) if v)
    c.drawString(x_text, H - 30 * mm, contact[:110])

    # Reference block
    y = H - 54 * mm
    c.setFillColor(INK)
    c.setFont("Helvetica", 10)
    decided = app.decided_at.strftime("%d %B %Y") if app.decided_at else ""
    c.drawString(left, y, f"Our ref: {app.letter_number}")
    c.drawRightString(right, y, decided)
    c.drawString(left, y - 5 * mm, f"Application: {app.reference}")

    y -= 18 * mm
    c.setFont("Helvetica-Bold", 11)
    c.drawString(left, y, app.full_name)
    c.setFont("Helvetica", 11)
    c.drawString(left, y - 5.5 * mm, f"{app.village}, {app.home_province}")

    y -= 20 * mm
    c.setFont("Helvetica-Bold", 14)
    c.setFillColor(RED)
    c.drawString(left, y, "LETTER OF PARTY ENDORSEMENT")
    c.setFillColor(INK)
    y -= 4 * mm
    c.setStrokeColor(GOLD)
    c.setLineWidth(1.2)
    c.line(left, y, left + 70 * mm, y)

    seat = app.electorate.name
    paras = [
        f"Dear {app.preferred_name or app.full_name.split()[0]},",
        f"Following review of your application by the provincial and national "
        f"executive, I am pleased to confirm that <b>{party.name}</b> endorses you as its "
        f"official candidate for <b>{seat}</b> in the 2027 National General Election.",
        "This endorsement is conditional on your successful nomination with the PNG "
        "Electoral Commission, continued compliance with the party constitution and "
        "code of conduct, and the obligations of the Organic Law on the Integrity of "
        "Political Parties and Candidates.",
        "Please present this letter, together with the party's nomination "
        "documentation, when you lodge your nomination. Contact the party secretariat "
        "if any detail in this letter is incorrect.",
        "Congratulations, and we look forward to working with you.",
    ]
    y -= 10 * mm
    for t in paras:
        y = _para(c, t, left, y, width) - 4 * mm

    # Signature
    y -= 18 * mm
    c.setStrokeColor(INK)
    c.setLineWidth(0.6)
    c.line(left, y, left + 70 * mm, y)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(left, y - 5.5 * mm, signatory_name or "______________________")
    c.setFont("Helvetica", 10)
    c.drawString(left, y - 10.5 * mm, signatory_title or "For the National Executive")

    # Footer
    c.setFont("Helvetica", 8)
    c.setFillColor(colors.HexColor("#666666"))
    c.drawString(left, 14 * mm,
                 f"Verify this letter with the party secretariat quoting {app.letter_number}.")
    c.saveState()
    p = c.beginPath()
    p.rect(0, 0, W, 6 * mm)
    c.clipPath(p, stroke=0, fill=0)
    c.linearGradient(0, 0, W, 0, (GREEN_D, GREEN, colors.HexColor("#9AB52A"), GOLD),
                     (0, 0.4, 0.7, 1), extend=True)
    c.restoreState()

    c.showPage()
    c.save()
    return buf.getvalue()
