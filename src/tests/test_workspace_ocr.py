"""Scan OCR reads actual pixels and retains original PDF coordinates."""
import io
from pathlib import Path
import subprocess
import pytest
from reportlab.pdfgen.canvas import Canvas
from workspace.ocr import available
from workspace.documents import parse_pdf


@pytest.mark.skipif(not available(),reason="Local OCR executables unavailable")
def test_real_scanned_page_recovers_text_and_positions(tmp_path):
    original=tmp_path/"text.pdf";c=Canvas(str(original))
    c.setFont("Helvetica",18);c.drawString(50,740,"Neural network predicts porosity from well logs.")
    c.drawString(50,690,"The dataset contains 120 samples.");c.save()
    subprocess.run(["pdftoppm","-singlefile","-png","-r","150",str(original),str(tmp_path/"image")],capture_output=True,check=True,timeout=10)
    scan=io.BytesIO();c=Canvas(scan);c.drawImage(str(tmp_path/"image.png"),0,0,width=595.27,height=841.89);c.save()
    parsed=parse_pdf(scan.getvalue());page=parsed["pages"][0]
    assert parsed["ocr_pages"]==1 and page["status"]=="ocr"
    assert "120 samples" in page["text"] and "porosity" in page["text"]
    assert page["spans"] and all(0<=s["bbox"][0]<s["bbox"][2]<=page["width"] for s in page["spans"])
    assert parsed["warnings"] and page["ocr_confidence"]>20
