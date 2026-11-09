import io
import pytest
from PIL import Image
from reportlab.pdfgen.canvas import Canvas
from reportlab.lib.utils import ImageReader
from pypdf import PdfReader, PdfWriter
from workspace.store import WorkspaceStore, WorkspaceError
from workspace.documents import ObjectStore, attach_pdf, parse_pdf, MAX_UPLOAD
from workspace import charts, writing, research_tools, review


def test_real_table_figure_equation_context_and_encrypted_or_scan_status(tmp_path):
    store = WorkspaceStore("sqlite:///" + str(tmp_path / "source.db")); p = store.create_project("alice", "Source analysis")
    paper = store.add_paper(p["id"], "alice", {"title": "Controlled PDF structures"})
    out = io.BytesIO(); c = Canvas(out)
    for x in (50, 150, 250): c.line(x, 660, x, 750)
    for y in (660, 690, 720, 750): c.line(50, y, 250, y)
    for y, values in ((733, ("Model", "RMSE")), (703, ("Neural", "0.08")), (673, ("Baseline", "0.12"))):
        c.drawString(60, y, values[0]); c.drawString(160, y, values[1])
    c.drawString(50, 635, "Table 1. RMSE comparison from controlled data.")
    image = Image.new("RGB", (50, 50), "#ef6f5c")
    c.drawImage(ImageReader(image), 50, 450, width=160, height=90)
    c.drawString(50, 430, "Figure 1. Controlled schematic; no numerical values shown.")
    c.drawString(50, 390, "RMSE = sqrt(mean squared error)"); c.save()
    document = attach_pdf(store, ObjectStore(tmp_path), p["id"], "alice", paper["id"], "structures.pdf", out.getvalue())
    page = document["data"]["pages"][0]
    assert page["tables"] and page["figures"] and page["equations"]
    report = charts.element_analysis(store, p["id"], "alice", document["id"], 1, "table", page["tables"][0]["id"])
    assert report["columns"][1]["minimum"] == .08 and report["columns"][1]["maximum"] == .12
    for kind, eid in (("figure", page["figures"][0]["id"]), ("equation", page["equations"][0])):
        result = charts.element_analysis(store, p["id"], "alice", document["id"], 1, kind, eid)
        assert result["context"] and all(q["quote"] in page["text"] for q in result["context"])
        assert "未对图像进行 OCR" in result["note"]
        source = result["context"][0]
        evidence = store.add_evidence(p["id"], "alice", {**source, "field": "source_context"})
        assert store.verify_evidence(p["id"], "alice", evidence["id"])["valid"]
    with pytest.raises(WorkspaceError): charts.element_analysis(store, p["id"], "mallory", document["id"], 1, "figure", page["figures"][0]["id"])
    writer = PdfWriter(); writer.append(PdfReader(io.BytesIO(out.getvalue()))); writer.encrypt("controlled-password")
    protected = io.BytesIO(); writer.write(protected)
    with pytest.raises(WorkspaceError, match="加密"): parse_pdf(protected.getvalue())
    scan = io.BytesIO(); canvas = Canvas(scan); canvas.drawImage(ImageReader(image), 50, 600); canvas.save()
    assert parse_pdf(scan.getvalue())["status"] == "scan_no_text"
    with pytest.raises(WorkspaceError): parse_pdf(b"not a pdf")
    with pytest.raises(WorkspaceError) as too_large: parse_pdf(b"%PDF-" + b" " * MAX_UPLOAD)
    assert too_large.value.status == 413


def test_configured_venue_checks_actual_docx_pdf_layout_and_review_scope(tmp_path):
    store = WorkspaceStore("sqlite:///" + str(tmp_path / "venue.db")); p = store.create_project("alice", "Controlled venue")
    paper = store.add_paper(p["id"], "alice", {"title": "Controlled source", "authors": ["Test Author"], "year": 2025,
        "abstract": "We propose a neural network. The dataset contains 120 samples. Results show RMSE of 0.08. However, evaluation is limited to one field."})
    research_tools.extract_matrix(store, p["id"], "alice")
    template = writing.set_template(store, p["id"], "alice", {"name": "Controlled venue specification", "sections": ["Abstract", "Methods", "Results"],
        "citation_style": "author_year", "paper_size": "Letter", "margin_mm": 20, "font": "Georgia", "font_size": 12,
        "abstract_limit": 3, "abstract_unit": "words", "keyword_limit": 2, "source_url": "https://example.org/controlled-specification"}, p["revision"])
    draft = writing.generate_manuscript(store, p["id"], "alice", template["id"])
    saved = writing.save_manuscript(store, p["id"], "alice", {**draft["data"], "abstract": "Four controlled abstract words", "keywords": ["a", "b", "c"]}, draft["id"], draft["revision"])
    assert saved["validation"]["abstract_over_limit"] and saved["validation"]["keywords_over_limit"]
    blob, _ = writing.export_manuscript(store, p["id"], "alice", saved["id"], "docx")
    from docx import Document
    doc = Document(io.BytesIO(blob))
    assert abs(doc.sections[0].page_width.mm - 215.9) < .1
    assert abs(doc.sections[0].left_margin.mm - 20) < .1
    assert doc.styles["Normal"].font.name == "Georgia" and doc.styles["Normal"].font.size.pt == 12
    pdf, _ = writing.export_manuscript(store, p["id"], "alice", saved["id"], "pdf")
    reader = PdfReader(io.BytesIO(pdf)); assert float(reader.pages[0].mediabox.width) == 612
    assert "120 samples" in " ".join(page.extract_text() for page in reader.pages)
    inspection = review.save_review(store, p["id"], "alice", critical=True)
    assert inspection["data"]["mode"] == "source_and_coverage_checks"
    assert any(f["kind"] == "source_scope" for f in inspection["data"]["findings"])
    assert all("不能据此判定论文缺失" in f["message"] for f in inspection["data"]["findings"] if f["kind"] == "reproducibility_context")
    assert inspection["data"]["outputs"][0]["validation"]["abstract_over_limit"]
