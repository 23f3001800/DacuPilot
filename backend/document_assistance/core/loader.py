from dataclasses import dataclass
from io import BytesIO
import os
from pathlib import Path
import re
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile


@dataclass(frozen=True)
class KnowledgeSection:
    source: str
    section: str
    text: str
    page: str = ""

    @property
    def citation(self) -> str:
        return f"{self.source} — {self.section}"


def detect_section_heading(text: str) -> str | None:
    """Detect structured section headers from page text."""
    for line in text.splitlines():
        line = line.strip()
        m = re.match(r"^(?:[0-9]+[\.\)]\s+)?([A-Za-z][A-Za-z0-9\s&/,-]{3,50})$", line)
        if m:
            heading = m.group(1).strip()
            if not heading.startswith(("Page ", "Effective", "DocuPilot Application", "Nimbus Orchard")):
                return heading
    return None


WORD_NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
}
MAX_DOCX_XML_BYTES = 10 * 1024 * 1024
MAX_EXTRACTED_TEXT_BYTES = 10 * 1024 * 1024
MAX_PDF_PAGES = 100
MAX_SOURCE_BYTES = 20 * 1024 * 1024


def _section_for_text(text: str, current: str) -> str:
    headings = (
        ("Attached is an excel sheet", "Excel data agent requirements"),
        ("Using your own documents", "Document support assistant requirements"),
        ("You are provided with a set of 10", "Document intelligence requirements"),
        ("Required extraction targets", "Required extraction targets"),
        ("Deliverables:", "Deliverables"),
        ("Evaluation criteria:", "Evaluation criteria"),
    )
    for prefix, section in headings:
        if text.startswith(prefix):
            return section
    return current


def load_docx_sections(path: str | Path) -> list[KnowledgeSection]:
    """Read paragraphs from a DOCX and group them by assignment section."""
    document_path = Path(path)
    if not document_path.is_file():
        raise FileNotFoundError(f"Knowledge document not found: {document_path}")

    try:
        with ZipFile(document_path) as archive:
            document_xml = archive.read("word/document.xml")
    except (BadZipFile, KeyError) as error:
        raise ValueError(f"Invalid DOCX knowledge document: {document_path}") from error

    try:
        root = ElementTree.fromstring(document_xml)
    except ElementTree.ParseError as error:
        raise ValueError(f"Invalid DOCX knowledge document: {document_path}") from error
    paragraphs = []
    for paragraph in root.findall(".//w:body/w:p", WORD_NS):
        text = "".join(
            node.text or "" for node in paragraph.findall(".//w:t", WORD_NS)
        ).strip()
        if text:
            paragraphs.append(text)

    source = document_path.name
    sections: list[KnowledgeSection] = []
    current_section = "Assignment overview"
    for text in paragraphs:
        current_section = _section_for_text(text, current_section)
        if sections and sections[-1].section == current_section:
            previous = sections[-1]
            sections[-1] = KnowledgeSection(
                source=source,
                section=current_section,
                text=f"{previous.text}\n{text}",
            )
        else:
            sections.append(
                KnowledgeSection(
                    source=source,
                    section=current_section,
                    text=text,
                )
            )

    return sections


def extract_uploaded_document(
    filename: str,
    content: bytes,
) -> list[tuple[str, str]]:
    """Extract text from a supported user document without executing its content."""
    if not content:
        raise ValueError("The uploaded document is empty.")
    if len(content) > MAX_SOURCE_BYTES:
        raise ValueError("The document exceeds the 20 MB limit.")

    suffix = Path(filename).suffix.lower()
    if suffix == ".txt":
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError as error:
            raise ValueError("Text documents must use UTF-8 encoding.") from error
        return [("Page 1", text)]

    if suffix == ".docx":
        try:
            with ZipFile(BytesIO(content)) as archive:
                info = archive.getinfo("word/document.xml")
                if info.file_size > MAX_DOCX_XML_BYTES:
                    raise ValueError(
                        "The uploaded DOCX document contains too much text."
                    )
                with archive.open(info) as document_file:
                    document_xml = document_file.read(MAX_DOCX_XML_BYTES + 1)
        except (BadZipFile, KeyError) as error:
            raise ValueError("The uploaded DOCX document is invalid.") from error
        if len(document_xml) > MAX_DOCX_XML_BYTES:
            raise ValueError("The uploaded DOCX document contains too much text.")
        try:
            root = ElementTree.fromstring(document_xml)
        except ElementTree.ParseError as error:
            raise ValueError("The uploaded DOCX document is invalid.") from error
        paragraphs = [
            "".join(node.text or "" for node in paragraph.findall(".//w:t", WORD_NS))
            .strip()
            for paragraph in root.findall(".//w:body/w:p", WORD_NS)
        ]
        text = "\n".join(paragraph for paragraph in paragraphs if paragraph)
        return [("Document body", text)]

    if suffix == ".pdf":
        try:
            import pymupdf
        except ImportError as error:
            raise RuntimeError("PDF uploads require the PyMuPDF package.") from error
        try:
            with pymupdf.open(stream=content, filetype="pdf") as pdf:
                if not pdf.page_count:
                    raise ValueError("The uploaded PDF has no pages.")
                if pdf.page_count > MAX_PDF_PAGES:
                    raise ValueError(
                        f"The uploaded PDF exceeds the {MAX_PDF_PAGES}-page limit."
                    )
                pages = []
                extracted_bytes = 0
                for index, page in enumerate(pdf):
                    text = page.get_text()
                    extracted_bytes += len(text.encode("utf-8"))
                    if extracted_bytes > MAX_EXTRACTED_TEXT_BYTES:
                        raise ValueError(
                            "The uploaded PDF contains too much extractable text."
                        )
                    pages.append((f"Page {index + 1}", text))
                return pages
        except ValueError:
            raise
        except Exception as error:
            raise ValueError("The uploaded PDF could not be read.") from error

    raise ValueError("Upload a PDF, DOCX, or UTF-8 text document.")


def load_knowledge_base(directory: str | Path) -> list[KnowledgeSection]:
    """Load approved DOCX, PDF, and UTF-8 TXT sources from the application KB."""
    root = Path(directory)
    if not root.is_dir():
        raise FileNotFoundError(f"Application knowledge directory not found: {root}")

    sections: list[KnowledgeSection] = []
    supported_suffixes = {".docx", ".pdf", ".txt"}
    for document_path in sorted(root.rglob("*")):
        if not document_path.is_file():
            continue
        if document_path.suffix.lower() not in supported_suffixes:
            continue
        if document_path.stat().st_size > MAX_SOURCE_BYTES:
            raise ValueError(
                f"Application knowledge source {document_path.name} exceeds 20 MB."
            )
        source = document_path.relative_to(root).as_posix()
        if document_path.suffix.lower() == ".docx":
            source_sections = load_docx_sections(document_path)
            sections.extend(
                KnowledgeSection(
                    source=source,
                    section=section.section,
                    text=section.text,
                )
                for section in source_sections
            )
            continue

        extracted = extract_uploaded_document(
            source,
            document_path.read_bytes(),
        )
        if not any(text.strip() for _, text in extracted):
            raise ValueError(
                f"No extractable text found in application knowledge source {source}."
            )
        for label, text in extracted:
            if not text.strip():
                continue
            detected = detect_section_heading(text) if source.lower().endswith(".pdf") else None
            section_title = f"{detected}, {label}" if detected else label
            sections.append(
                KnowledgeSection(
                    source=source,
                    section=section_title,
                    text=text,
                    page=label,
                )
            )

    if not sections:
        raise ValueError(
            f"No readable PDF, DOCX, or TXT sources found in {root}."
        )
    return sections


def split_text(text: str, chunk_size: int = 1200, overlap: int = 180) -> list[str]:
    """Split source text into bounded, overlapping chunks for retrieval."""
    normalized = re.sub(r"\s+", " ", text).strip()
    if not normalized:
        return []
    if chunk_size <= overlap:
        raise ValueError("Chunk size must be greater than its overlap.")

    chunks = []
    start = 0
    while start < len(normalized):
        end = min(start + chunk_size, len(normalized))
        if end < len(normalized):
            boundary = normalized.rfind(" ", start + chunk_size // 2, end)
            if boundary > start:
                end = boundary
        chunks.append(normalized[start:end].strip())
        if end == len(normalized):
            break
        start = end - overlap
    return chunks


def ingest_pdf_to_vector_db(pdf_path: str | Path):
    """Build the existing local PDF vector store on demand."""
    document_path = Path(pdf_path)
    if not document_path.is_file():
        raise FileNotFoundError(f"Target PDF file not found at: {document_path}")

    try:
        from langchain_community.document_loaders import PyPDFLoader
        from langchain_community.embeddings import HuggingFaceEmbeddings
        from langchain_community.vectorstores import Chroma
        from langchain_text_splitters import RecursiveCharacterTextSplitter
    except ImportError as error:
        raise RuntimeError(
            "PDF vector ingestion requires langchain-community, "
            "langchain-text-splitters, chromadb, and sentence-transformers."
        ) from error

    raw_pages = PyPDFLoader(os.fspath(document_path)).load()
    chunks = RecursiveCharacterTextSplitter(
        chunk_size=500,
        chunk_overlap=100,
    ).split_documents(raw_pages)
    embeddings = HuggingFaceEmbeddings(
        model_name="sentence-transformers/all-MiniLM-L6-v2"
    )
    return Chroma.from_documents(documents=chunks, embedding=embeddings)
