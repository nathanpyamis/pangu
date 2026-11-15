"""
Pure ReportLab drawing for every Pangu Pati ID card. No Django imports, so it
can be tested on its own. pip-only, works the same on Windows and Linux.

Three card kinds share one CR80 layout and differ in their tag, labels and
accent colour:

    MEMBER     membership card           tag MEMBER     green
    CANDIDATE  endorsed candidate card   tag CANDIDATE  gold
    STAFF      field officer card        tag OFFICER    dark green

Each card is a dict:
    kind ("MEMBER" | "CANDIDATE" | "STAFF"), name, number,
    line1_label, line1, line2_label, line2,
    issued (str), valid_until (str, optional),
    verify_url (str), photo (bytes | None)
plus, per call to build_pdf: party_name, logo (bytes | None).
"""
import io

from reportlab.graphics import renderPDF
from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Drawing
from reportlab.lib.colors import HexColor, white
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader, simpleSplit
from reportlab.pdfgen import canvas

# Pangu brand tokens (from the party logo)
INK = HexColor("#111111")
GREEN_D = HexColor("#0F5A2A")
GREEN = HexColor("#1F7A34")
LIME = HexColor("#9AB52A")
GOLD = HexColor("#E8B422")
NIGHT = HexColor("#06140B")
MUTED = HexColor("#555555")
PHOTO_BG = HexColor("#E6E6E6")
CUT = HexColor("#9A9A9A")
GRADIENT = ((GREEN_D, GREEN, LIME, GOLD), (0, 0.4, 0.7, 1))

KINDS = {
    "MEMBER":    {"title": "OFFICIAL MEMBERSHIP CARD", "tag": "MEMBER",    "tag_bg": GREEN, "tag_fg": white,
                  "number_label": "Membership No."},
    "CANDIDATE": {"title": "ENDORSED CANDIDATE · 2027", "tag": "CANDIDATE", "tag_bg": GOLD,  "tag_fg": INK,
                  "number_label": "Candidate No."},
    "STAFF":     {"title": "AUTHORISED PARTY OFFICER", "tag": "OFFICER",   "tag_bg": NIGHT, "tag_fg": GOLD,
                  "number_label": "Staff No."},
}

CARD_W, CARD_H = 85.6, 54.0          # CR80, mm
A4_W, A4_H = 210.0, 297.0

# per_page -> (cols, rows, col_gap_mm, row_gap_mm)
BATCH_LAYOUTS = {
    10: (2, 5, 0.0, 0.0),   # edge-to-edge: one cut line between cards
    8:  (2, 4, 6.0, 8.0),   # gutters: easier to hand-cut and laminate
}

FONT = "Helvetica"
FONT_B = "Helvetica-Bold"
FONT_MONO = "Courier-Bold"


def batch_positions(per_page):
    """Card top-left corners in mm, measured from the TOP-left of the A4 page."""
    cols, rows, cgap, rgap = BATCH_LAYOUTS[per_page]
    block_w = cols * CARD_W + (cols - 1) * cgap
    block_h = rows * CARD_H + (rows - 1) * rgap
    left0, top0 = (A4_W - block_w) / 2, (A4_H - block_h) / 2
    return [
        (left0 + col * (CARD_W + cgap), top0 + row * (CARD_H + rgap))
        for row in range(rows) for col in range(cols)
    ]


def _fit_font(c, text, font, size, max_w_mm, min_size):
    while size > min_size and c.stringWidth(text, font, size) > max_w_mm * mm:
        size -= 0.25
    return size


def _draw_qr(c, data, x, y, size):
    w = QrCodeWidget(data, barLevel="M")
    x1, y1, x2, y2 = w.getBounds()
    bw, bh = x2 - x1, y2 - y1
    d = Drawing(size, size, transform=[size / bw, 0, 0, size / bh, 0, 0])
    d.add(w)
    renderPDF.draw(d, c, x, y)


def _gradient_rect(c, x, y, w, h):
    c.saveState()
    p = c.beginPath()
    p.rect(x, y, w, h)
    c.clipPath(p, stroke=0, fill=0)
    c.linearGradient(x, y, x + w, y, GRADIENT[0], GRADIENT[1], extend=True)
    c.restoreState()


def _image(data):
    try:
        return ImageReader(io.BytesIO(data)) if data else None
    except Exception:
        return None


def draw_card(c, card, ox, oy, party_name="PANGU PATI", logo=None, cut_marks=False):
    """Draw one card with its bottom-left corner at (ox, oy) in mm."""
    kind = KINDS.get(card.get("kind", "MEMBER"), KINDS["MEMBER"])

    def X(v): return (ox + v) * mm
    def Y(top_mm): return (oy + CARD_H - top_mm) * mm   # "from top" -> PDF y

    c.saveState()
    p = c.beginPath()
    p.rect(ox * mm, oy * mm, CARD_W * mm, CARD_H * mm)
    c.clipPath(p, stroke=0, fill=0)

    c.setFillColor(white)
    c.rect(ox * mm, oy * mm, CARD_W * mm, CARD_H * mm, stroke=0, fill=1)

    # Header band: Pangu green-to-gold gradient, logo on a white disc
    band_h = 11.0
    _gradient_rect(c, X(0), Y(band_h), CARD_W * mm, band_h * mm)
    text_x = 3
    if logo is not None:
        c.setFillColor(white)
        c.circle(X(7.3), Y(band_h / 2), 4.6 * mm, stroke=0, fill=1)
        c.drawImage(logo, X(3.6), Y(band_h / 2 + 3.7), 7.4 * mm, 7.4 * mm,
                    preserveAspectRatio=True, mask="auto")
        text_x = 13.2
    c.setFillColor(white)
    c.setFont(FONT_B, 7.6)
    c.drawString(X(text_x), Y(4.9), party_name.upper())
    c.setFont(FONT_B, 4.6)
    c.drawString(X(text_x), Y(8.4), kind["title"])

    # Kind tag (sits on the gold end of the band)
    tag_w = 17 if kind["tag"] == "CANDIDATE" else 14
    c.setFillColor(kind["tag_bg"])
    c.roundRect(X(CARD_W - 3 - tag_w), Y(7.9), tag_w * mm, 4.8 * mm, 0.8 * mm, stroke=0, fill=1)
    c.setFillColor(kind["tag_fg"])
    c.setFont(FONT_B, 5.4)
    c.drawCentredString(X(CARD_W - 3 - tag_w / 2), Y(6.3), kind["tag"])

    # Photo 20 x 25 mm
    px, ptop, pw, ph = 3, 13.5, 20, 25
    c.setFillColor(PHOTO_BG)
    c.rect(X(px), Y(ptop + ph), pw * mm, ph * mm, stroke=0, fill=1)
    img = _image(card.get("photo"))
    if img is not None:
        iw, ih = img.getSize()
        scale = max(pw / iw, ph / ih)          # cover-fit
        dw, dh = iw * scale, ih * scale
        c.saveState()
        box = c.beginPath()
        box.rect(X(px), Y(ptop + ph), pw * mm, ph * mm)
        c.clipPath(box, stroke=0, fill=0)
        c.drawImage(img, X(px + (pw - dw) / 2), Y(ptop + ph) + ((ph - dh) / 2) * mm, dw * mm, dh * mm)
        c.restoreState()
    else:
        c.setFillColor(MUTED)
        c.setFont(FONT, 5)
        c.drawCentredString(X(px + pw / 2), Y(ptop + ph / 2), "NO PHOTO")
    c.setStrokeColor(GREEN_D)
    c.setLineWidth(0.3 * mm)
    c.rect(X(px), Y(ptop + ph), pw * mm, ph * mm, stroke=1, fill=0)

    # Details column
    dx, dw_mm = 25.5, 35.5
    name = (card.get("name") or "").upper()
    lines = simpleSplit(name, FONT_B, 8, dw_mm * mm)[:2]
    c.setFillColor(INK)
    yy = 16.2
    for line in lines:
        size = _fit_font(c, line, FONT_B, 8, dw_mm, 6)
        c.setFont(FONT_B, size)
        c.drawString(X(dx), Y(yy), line)
        yy += 3.2

    def field(label, value, top, font=FONT_B, size=6.2, color=INK):
        value = value or ""
        c.setFillColor(MUTED)
        c.setFont(FONT, 4.5)
        c.drawString(X(dx), Y(top), label.upper())
        c.setFillColor(color)
        size = _fit_font(c, value, font, size, dw_mm, 4.5)
        c.setFont(font, size)
        c.drawString(X(dx), Y(top + 2.6), value)

    field(kind["number_label"], card.get("number"), 23.4, FONT_MONO, 6.8, GREEN_D)
    field(card.get("line1_label", ""), card.get("line1"), 29.2)
    field(card.get("line2_label", ""), card.get("line2"), 35.0)

    # QR 20 mm
    qsize = 20
    qx = CARD_W - 2.5 - qsize
    _draw_qr(c, card["verify_url"], X(qx), Y(13.5 + qsize), qsize * mm)
    c.setFillColor(MUTED)
    c.setFont(FONT, 4)
    c.drawCentredString(X(qx + qsize / 2), Y(36), "Scan to verify")

    # Issued / valid-until + bottom gradient stripe
    c.setFont(FONT, 4.8)
    c.setFillColor(MUTED)
    footer = f"Issued {card.get('issued', '')}"
    if card.get("valid_until"):
        footer += f"   ·   Valid until {card['valid_until']}"
    c.drawString(X(3), Y(CARD_H - 5.4), footer)
    _gradient_rect(c, X(0), Y(CARD_H), CARD_W * mm, 3 * mm)

    c.restoreState()

    if cut_marks:
        c.saveState()
        c.setStrokeColor(CUT)
        c.setLineWidth(0.2 * mm)
        c.setDash(2, 2)
        c.rect(ox * mm, oy * mm, CARD_W * mm, CARD_H * mm, stroke=1, fill=0)
        c.restoreState()


def build_pdf(cards, layout="single", per_page=10, title="Pangu Pati ID cards",
              party_name="Pangu Pati", logo_bytes=None):
    logo = _image(logo_bytes)
    buf = io.BytesIO()
    if layout == "single":
        c = canvas.Canvas(buf, pagesize=(CARD_W * mm, CARD_H * mm))
        c.setTitle(title)
        for card in cards:
            draw_card(c, card, 0, 0, party_name, logo)
            c.showPage()
    else:
        c = canvas.Canvas(buf, pagesize=A4)
        c.setTitle(title)
        positions = batch_positions(per_page)
        pages = [cards[i:i + per_page] for i in range(0, len(cards), per_page)]
        for n, chunk in enumerate(pages, 1):
            for card, (left, top) in zip(chunk, positions):
                draw_card(c, card, left, A4_H - top - CARD_H, party_name, logo, cut_marks=True)
            c.setFillColor(HexColor("#888888"))
            c.setFont(FONT, 6)
            c.drawCentredString(A4_W / 2 * mm, 5 * mm,
                                f"{party_name} ID cards - sheet {n} of {len(pages)} - "
                                "print at 100% (Actual size) and cut along dashed lines")
            c.showPage()
    c.save()
    return buf.getvalue()
