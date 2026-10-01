from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from zoneinfo import ZoneInfo

from reportlab.lib.colors import Color, HexColor, white
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas


TEAL = HexColor("#0F766E")
NAVY = HexColor("#102A43")
BLUE = HexColor("#3B82F6")
PALE_BLUE = Color(0.23, 0.51, 0.96, alpha=0.10)
MUTED = HexColor("#64748B")
LIGHT = HexColor("#F8FAFC")
RED = HexColor("#DC2626")
FONT_AWESOME_PATH = Path(__file__).resolve().parent / "static" / "fonts" / "fa-regular-400.ttf"
if FONT_AWESOME_PATH.is_file():
    pdfmetrics.registerFont(TTFont("FontAwesomeRegular", str(FONT_AWESOME_PATH)))


def _incident_datetime(raw_value):
    try:
        parsed = datetime.fromisoformat(str(raw_value))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(ZoneInfo("Asia/Kolkata"))
    except (TypeError, ValueError):
        return datetime.now(ZoneInfo("Asia/Kolkata"))


def _draw_grid(pdf, width, height):
    pdf.saveState()
    pdf.setStrokeColor(PALE_BLUE)
    pdf.setLineWidth(0.35)
    spacing = 18
    x = 0
    while x <= width:
        pdf.line(x, 0, x, height)
        x += spacing
    y = 0
    while y <= height:
        pdf.line(0, y, width, y)
        y += spacing
    pdf.restoreState()


def _draw_logo(pdf, x, y):
    pdf.setFillColor(TEAL)
    pdf.roundRect(x, y, 38, 38, 10, fill=1, stroke=0)
    pdf.setFillColor(white)
    if FONT_AWESOME_PATH.is_file():
        pdf.setFont("FontAwesomeRegular", 22)
        pdf.drawCentredString(x + 19, y + 10, "\uf15c")
    else:
        # Portable fallback if the bundled icon font is unavailable.
        pdf.setStrokeColor(white)
        pdf.setLineWidth(1.8)
        pdf.roundRect(x + 11, y + 7, 17, 25, 2, fill=0, stroke=1)


def _value_card(pdf, x, y, width, label, value, accent=TEAL):
    pdf.setFillColor(white)
    pdf.setStrokeColor(HexColor("#DCE7F5"))
    pdf.roundRect(x, y, width, 48, 8, fill=1, stroke=1)
    pdf.setFillColor(accent)
    pdf.roundRect(x, y, 4, 48, 2, fill=1, stroke=0)
    pdf.setFillColor(MUTED)
    pdf.setFont("Helvetica", 8)
    pdf.drawString(x + 14, y + 32, label.upper())
    pdf.setFillColor(NAVY)
    pdf.setFont("Helvetica-Bold", 11)
    display = str(value or "Not available")
    while stringWidth(display, "Helvetica-Bold", 11) > width - 26 and len(display) > 5:
        display = display[:-4] + "..."
    pdf.drawString(x + 14, y + 14, display)


def _draw_evidence_images(pdf, x, y, width, height, snapshots):
    """Draw up to 4 incident screenshots side by side with capture-time
    captions, so a report shows how the incident progressed rather than a
    single frame. Falls back to a placeholder when none are available.
    """
    valid = [item for item in snapshots if Path(item.get("path", "")).is_file()][:4]
    if not valid:
        pdf.setFillColor(MUTED)
        pdf.setFont("Helvetica", 11)
        pdf.drawCentredString(x + width / 2, y + height / 2, "Screenshot unavailable")
        return

    caption_h = 14
    photo_h = height - caption_h
    gap = 10
    col_w = (width - gap * (len(valid) - 1)) / len(valid)
    for index, snap in enumerate(valid):
        col_x = x + index * (col_w + gap)
        image = ImageReader(snap["path"])
        iw, ih = image.getSize()
        scale = min(col_w / iw, photo_h / ih)
        draw_w, draw_h = iw * scale, ih * scale
        pdf.drawImage(
            image, col_x + (col_w - draw_w) / 2, y + caption_h + (photo_h - draw_h) / 2,
            width=draw_w, height=draw_h, preserveAspectRatio=True, mask="auto",
        )
        pdf.setFillColor(MUTED)
        pdf.setFont("Helvetica", 7)
        caption = _incident_datetime(snap.get("created_at")).strftime("%I:%M:%S %p")
        pdf.drawCentredString(col_x + col_w / 2, y + 3, caption)


def build_incident_report(incident, output=None):
    """Build a polished one-page incident PDF and return its bytes."""
    stream = output or BytesIO()
    pdf = canvas.Canvas(stream, pagesize=A4, pageCompression=1)
    page_width, page_height = A4
    pdf.setTitle(f"Rakshak AI Incident Report {incident['id']}")
    pdf.setAuthor("Rakshak AI")

    pdf.setFillColor(white)
    pdf.rect(0, 0, page_width, page_height, fill=1, stroke=0)
    _draw_grid(pdf, page_width, page_height)

    # Header
    pdf.setFillColor(Color(1, 1, 1, alpha=0.94))
    pdf.setStrokeColor(HexColor("#CFE0F5"))
    pdf.roundRect(34, page_height - 104, page_width - 68, 70, 14, fill=1, stroke=1)
    _draw_logo(pdf, 50, page_height - 88)
    pdf.setFillColor(NAVY)
    pdf.setFont("Helvetica-Bold", 20)
    pdf.drawString(102, page_height - 62, "RAKSHAK AI")
    pdf.setFillColor(MUTED)
    pdf.setFont("Helvetica", 9)
    pdf.drawString(102, page_height - 79, "AI-Powered Campus Safety and Incident Intelligence")
    pdf.setFillColor(RED)
    pdf.setFont("Helvetica-Bold", 11)
    pdf.drawRightString(page_width - 50, page_height - 60, "CRITICAL INCIDENT REPORT")
    pdf.setFillColor(MUTED)
    pdf.setFont("Helvetica", 8)
    pdf.drawRightString(page_width - 50, page_height - 78, f"Report ID: RK-{incident['id']:06d}")

    occurred = _incident_datetime(incident.get("detected_at"))
    card_y = page_height - 178
    gap = 10
    card_width = (page_width - 68 - gap) / 2
    _value_card(pdf, 34, card_y, card_width, "Incident date", occurred.strftime("%d %B %Y"))
    _value_card(pdf, 34 + card_width + gap, card_y, card_width, "Incident time", occurred.strftime("%I:%M:%S %p IST"))
    _value_card(pdf, 34, card_y - 60, card_width, "Camera/source", incident.get("camera"))
    _value_card(
        pdf, 34 + card_width + gap, card_y - 60, card_width,
        "Detection confidence", f"{float(incident.get('confidence') or 0):.1f}%", RED,
    )

    snapshot = incident.get("snapshot") or {}
    names = snapshot.get("student_names") or incident.get("student_names") or "Unknown person"
    label = snapshot.get("incident_label") or incident.get("label") or "Violence detected"
    raw_heights = snapshot.get("person_heights") or incident.get("person_heights") or "Estimated ~172 cm"
    # Ensure display is cleanly in centimeters only (strip any legacy imperial parenthesis if present)
    import re
    heights = re.sub(r"\s*\([^)]*\)", "", str(raw_heights)).strip()

    section_y = card_y - 94
    pdf.setFillColor(NAVY)
    pdf.setFont("Helvetica-Bold", 12)
    pdf.drawString(40, section_y, "INCIDENT SUMMARY")
    pdf.setStrokeColor(BLUE)
    pdf.setLineWidth(2)
    pdf.line(40, section_y - 7, 124, section_y - 7)

    pdf.setFillColor(Color(1, 1, 1, alpha=0.95))
    pdf.setStrokeColor(HexColor("#DCE7F5"))
    pdf.roundRect(34, section_y - 86, page_width - 68, 67, 10, fill=1, stroke=1)
    
    col1_x = 48
    col2_x = 210
    col3_x = 385
    
    pdf.setFillColor(MUTED)
    pdf.setFont("Helvetica", 7.5)
    pdf.drawString(col1_x, section_y - 40, "DETECTED THREAT")
    pdf.drawString(col2_x, section_y - 40, "INVOLVED STUDENT(S)")
    pdf.drawString(col3_x, section_y - 40, "ESTIMATED HEIGHT(S)")
    
    # Value 1: Threat
    pdf.setFillColor(RED)
    pdf.setFont("Helvetica-Bold", 10.5)
    threat_display = str(label).title()
    while stringWidth(threat_display, "Helvetica-Bold", 10.5) > 150 and len(threat_display) > 5:
        threat_display = threat_display[:-4] + "..."
    pdf.drawString(col1_x, section_y - 59, threat_display)
    
    # Value 2: Names
    pdf.setFillColor(NAVY)
    pdf.setFont("Helvetica-Bold", 10.5)
    names_display = str(names)
    while stringWidth(names_display, "Helvetica-Bold", 10.5) > 165 and len(names_display) > 5:
        names_display = names_display[:-4] + "..."
    pdf.drawString(col2_x, section_y - 59, names_display)
    
    # Value 3: Heights
    pdf.setFillColor(TEAL)
    pdf.setFont("Helvetica-Bold", 10)
    heights_display = str(heights)
    while stringWidth(heights_display, "Helvetica-Bold", 10) > (page_width - col3_x - 45) and len(heights_display) > 5:
        heights_display = heights_display[:-4] + "..."
    pdf.drawString(col3_x, section_y - 59, heights_display)

    snapshots = incident.get("snapshots") or ([snapshot] if snapshot else [])
    evidence_title_y = section_y - 116
    pdf.setFillColor(NAVY)
    pdf.setFont("Helvetica-Bold", 12)
    evidence_title = "VISUAL EVIDENCE"
    if len(snapshots) > 1:
        evidence_title += f" ({len(snapshots)} SCREENSHOTS)"
    pdf.drawString(40, evidence_title_y, evidence_title)
    pdf.setStrokeColor(BLUE)
    pdf.line(40, evidence_title_y - 7, 160, evidence_title_y - 7)

    image_x, image_y = 58, 105
    image_w, image_h = page_width - 116, evidence_title_y - 132
    pdf.setFillColor(HexColor("#EAF2FD"))
    pdf.setStrokeColor(HexColor("#B8D1F0"))
    pdf.roundRect(image_x - 8, image_y - 8, image_w + 16, image_h + 16, 12, fill=1, stroke=1)
    _draw_evidence_images(pdf, image_x, image_y, image_w, image_h, snapshots)

    pdf.setFillColor(MUTED)
    pdf.setFont("Helvetica", 8)
    pdf.drawString(40, 72, "Automatically generated from Rakshak AI critical-event records.")
    pdf.setStrokeColor(HexColor("#CFE0F5"))
    pdf.line(40, 88, page_width - 40, 88)
    pdf.setFillColor(TEAL)
    pdf.setFont("Helvetica-Bold", 8)
    pdf.drawCentredString(page_width / 2, 50, "RAKSHAK AI - INCIDENT RESPONSE DOCUMENT")

    pdf.showPage()
    pdf.save()
    if output is None:
        return stream.getvalue()
    return output
