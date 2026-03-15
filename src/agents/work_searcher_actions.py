import shutil
from datetime import datetime
from pathlib import Path

from odf import teletype, text
from odf.opendocument import OpenDocumentSpreadsheet, OpenDocumentText, load
from odf.table import Table, TableCell, TableRow

from agents.types import ParsedJob, RankingOutput, ScoringInput
from config.types import Document, FileOrContent
from files.utils import ODF_EXTENSIONS, convert_to_pdf
from logger import logger

_PROMPTS_DIR = Path(__file__).parent.parent.parent / "prompts"
SCORING_SYSTEM_PROMPT = (_PROMPTS_DIR / "scoring_system_prompt.md").read_text(
    encoding="utf-8"
)
_SCORING_USER_MESSAGE_TEMPLATE = (
    _PROMPTS_DIR / "scoring_user_message_template.md"
).read_text(encoding="utf-8")


def build_scoring_user_message(scoring_input: ScoringInput) -> str:
    """Formats a ScoringInput into a single user message string.

    Args:
        scoring_input (ScoringInput): The structured LLM input for one job.

    Returns:
        str: A formatted prompt string combining all scoring input fields.
    """
    document_categories_text = "\n".join(
        f"- {dc.category}: {dc.description}" for dc in scoring_input.document_categories
    )
    return _SCORING_USER_MESSAGE_TEMPLATE.format(
        job_description=scoring_input.job_description,
        document_categories=document_categories_text,
        profile=scoring_input.profile,
        preferences=scoring_input.preferences,
    )


def dest_name(doc_field: FileOrContent, fallback_stem: str) -> str:
    """Returns the destination filename for a document field.

    Args:
        doc_field (FileOrContent): The document source.
        fallback_stem (str): Name stem to use when no source file path exists.

    Returns:
        str: The destination filename.
    """
    if doc_field.file is not None:
        return Path(doc_field.file).name
    return f"{fallback_stem}.odt"


def copy_or_write(doc_field: FileOrContent, dest_path: Path) -> None:
    """Copies a source file or writes raw content to the destination path.

    Args:
        doc_field (FileOrContent): The document source.
        dest_path (Path): Destination file path.
    """
    if doc_field.file is not None:
        shutil.copy2(doc_field.file, dest_path)
    else:
        doc = OpenDocumentText()
        p = text.P(text=doc_field.content)
        doc.text.addElement(p)
        doc.save(str(dest_path))


def extract_cover_last_paragraph(cover_content: str) -> str | None:
    """Extracts the last non-empty paragraph from plain-text cover letter content.

    Args:
        cover_content (str): Plain-text content of the cover letter.

    Returns:
        str | None: The last non-empty paragraph, or None if the content is blank.
    """
    return next((p for p in reversed(cover_content.split("\n")) if p.strip()), None)


def write_job_output(
    job_dir: Path,
    doc: Document,
    rewritten_closing: str | None,
) -> None:
    """Writes resume and cover letter files into a job output directory.

    Creates the directory, copies or writes the resume and cover letter for
    the given document category, then replaces the cover letter's last paragraph
    with the pre-computed rewrite (if provided). Converts both documents to PDF.

    Args:
        job_dir (Path): Target directory for the job output files.
        doc (Document): Document category bundle containing resume and cover letter.
        rewritten_closing (str | None): Pre-computed replacement for the cover
            letter's last paragraph. Skipped when None.
    """
    job_dir.mkdir(parents=True, exist_ok=True)

    resume_dest = job_dir / dest_name(doc.resume, "resume")
    try:
        copy_or_write(doc.resume, resume_dest)
    except Exception as e:
        logger.error(f"Failed to copy or write resume to '{resume_dest}': {e}")
    try:
        convert_to_pdf(resume_dest)
    except Exception as e:
        logger.error(f"Failed to convert resume to PDF for '{resume_dest}': {e}")

    cover_dest = job_dir / dest_name(doc.cover_letter, "cover_letter")
    try:
        copy_or_write(doc.cover_letter, cover_dest)
    except Exception as e:
        logger.error(f"Failed to copy or write cover letter to '{cover_dest}': {e}")
    if rewritten_closing is not None:
        write_last_paragraph(cover_dest, rewritten_closing)
    try:
        convert_to_pdf(cover_dest)
    except Exception as e:
        logger.error(f"Failed to convert cover letter to PDF for '{cover_dest}': {e}")


def write_summary_ods(
    out_dir: Path,
    parsed_jobs: list[ParsedJob],
    rankings: list[RankingOutput],
) -> None:
    """Writes a summary ODS spreadsheet with one row per ranked job.

    Columns: job_title (A), company (B), job_url (C), candidate_rank (D),
    candidate_explanation (E), offering_rank (F), offering_explanation (G),
    related_category (H), final_rank (I, formula: =0.5*(D{row}+F{row})),
    status (J).
    The file is named '{DATETIME}_summary.ods' and placed directly in out_dir.

    Args:
        out_dir (Path): Directory to write the ODS file to.
        parsed_jobs (list[ParsedJob]): Ordered list of parsed job records.
        rankings (list[RankingOutput]): Ordered list of ranking results
            matching parsed_jobs.
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    doc = OpenDocumentSpreadsheet()
    table = Table(name="Summary")

    headers = [
        "job_title",
        "company",
        "job_url",
        "candidate_rank",
        "candidate_explanation",
        "offering_rank",
        "offering_explanation",
        "related_category",
        "final_rank",
        "status",
    ]
    header_row = TableRow()
    for h in headers:
        cell = TableCell(valuetype="string", stringvalue=h)
        cell.addElement(text.P(text=h))
        header_row.addElement(cell)
    table.addElement(header_row)

    for row_idx, (parsed_job, ranking) in enumerate(
        zip(parsed_jobs, rankings), start=2
    ):
        data_row = TableRow()

        for val in [parsed_job.job_title, parsed_job.company, parsed_job.job_url]:
            cell = TableCell(valuetype="string", stringvalue=str(val))
            cell.addElement(text.P(text=str(val)))
            data_row.addElement(cell)

        data_row.addElement(
            TableCell(valuetype="float", value=str(ranking.candidate_rank.rank))
        )

        cell = TableCell(
            valuetype="string", stringvalue=ranking.candidate_rank.explanation
        )
        cell.addElement(text.P(text=ranking.candidate_rank.explanation))
        data_row.addElement(cell)

        data_row.addElement(
            TableCell(valuetype="float", value=str(ranking.offering_rank.rank))
        )

        cell = TableCell(
            valuetype="string", stringvalue=ranking.offering_rank.explanation
        )
        cell.addElement(text.P(text=ranking.offering_rank.explanation))
        data_row.addElement(cell)

        cell = TableCell(valuetype="string", stringvalue=ranking.related_category)
        cell.addElement(text.P(text=ranking.related_category))
        data_row.addElement(cell)

        final_rank = 0.5 * (ranking.candidate_rank.rank + ranking.offering_rank.rank)
        data_row.addElement(
            TableCell(
                valuetype="float",
                formula=f"of:=0.5*(D{row_idx}+F{row_idx})",
                value=str(final_rank),
            )
        )

        cell = TableCell(valuetype="string", stringvalue=ranking.status)
        cell.addElement(text.P(text=ranking.status))
        data_row.addElement(cell)

        table.addElement(data_row)

    doc.spreadsheet.addElement(table)
    summary_path = out_dir / f"{timestamp}_summary.ods"
    if summary_path.exists():
        logger.warning(f"Summary file '{summary_path}' already exists — overwriting.")
    doc.save(str(summary_path))


def write_last_paragraph(cover_path: Path, new_text: str) -> None:
    """Replaces the last non-empty paragraph of a cover letter file with new_text.

    For ODT files, edits the document in-place using odfpy. For plain text
    files, replaces the last non-empty line in-place.

    Args:
        cover_path (Path): Path to the cover letter file to edit.
        new_text (str): Replacement text for the last paragraph.
    """
    if cover_path.suffix.lower() in ODF_EXTENSIONS:
        doc = load(str(cover_path))
        paragraphs = doc.getElementsByType(text.P)
        last_p = next(
            (p for p in reversed(paragraphs) if teletype.extractText(p).strip()),
            None,
        )
        if last_p is None:
            return
        for child in list(last_p.childNodes):
            last_p.removeChild(child)
        last_p.addText(new_text)
        doc.save(str(cover_path))
    else:
        lines = cover_path.read_text(encoding="utf-8").split("\n")
        last_idx = next(
            (i for i in reversed(range(len(lines))) if lines[i].strip()),
            None,
        )
        if last_idx is None:
            return
        lines[last_idx] = new_text
        cover_path.write_text("\n".join(lines), encoding="utf-8")
