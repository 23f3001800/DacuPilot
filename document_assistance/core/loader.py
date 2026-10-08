from dataclasses import dataclass
import os
from pathlib import Path
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile


@dataclass(frozen=True)
class KnowledgeSection:
    source: str
    section: str
    text: str

    @property
    def citation(self) -> str:
        return f"{self.source} — {self.section}"


WORD_NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
}


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

    root = ElementTree.fromstring(document_xml)
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
