import shutil
from datetime import datetime
from pathlib import Path

from langchain_ollama import ChatOllama
from odf import teletype, text
from odf.opendocument import OpenDocumentSpreadsheet, OpenDocumentText, load
from odf.table import Table, TableCell, TableRow

from agents.types import ParsedJob, RankingOutput, ScoringInput
from config.types import FileOrContent
from files.File import ODF_EXTENSIONS

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


def write_summary_ods(
    out_dir: Path, parsed_jobs: list[ParsedJob], rankings: list[RankingOutput]
) -> None:
    """Writes a summary ODS spreadsheet with one row per ranked job.

    Columns: job_title (A), company (B), job_url (C), candidate_rank (D),
    candidate_explanation (E), offering_rank (F), offering_explanation (G),
    related_category (H), final_rank (I, formula: =0.5*(D{row}+F{row})).
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

        table.addElement(data_row)

    doc.spreadsheet.addElement(table)
    doc.save(str(out_dir / f"{timestamp}_summary.ods"))


def rewrite_last_paragraph(
    cover_path: Path, job_description: str, model_name: str
) -> None:
    """Rewrites the last non-empty paragraph of a cover letter file using an LLM.

    For ODT files, edits the document in-place using odfpy. For plain text
    files, replaces the last non-empty line in-place.

    Args:
        cover_path (Path): Path to the cover letter file to edit.
        job_description (str): Job description passed as context to the LLM.
        model_name (str): Ollama model identifier to use for the rewrite.
    """
    llm = ChatOllama(model=model_name)

    if cover_path.suffix.lower() in ODF_EXTENSIONS:
        doc = load(str(cover_path))
        paragraphs = doc.getElementsByType(text.P)
        last_p = next(
            (p for p in reversed(paragraphs) if teletype.extractText(p).strip()),
            None,
        )
        if last_p is None:
            return
        new_text = _call_rewrite_llm(llm, job_description, teletype.extractText(last_p))
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
        lines[last_idx] = _call_rewrite_llm(llm, job_description, lines[last_idx])
        cover_path.write_text("\n".join(lines), encoding="utf-8")


def _call_rewrite_llm(
    llm: ChatOllama, job_description: str, last_paragraph: str
) -> str:
    """Calls the LLM to rewrite a cover letter closing paragraph.

    Args:
        llm (ChatOllama): The LLM instance to use.
        job_description (str): The job description for context.
        last_paragraph (str): The current closing paragraph to rewrite.

    Returns:
        str: The rewritten paragraph text.
    """
    # TODO: move to a dedicated prompt file in prompts/ when content is finalised.
    message = (
        f"Job description:\n{job_description}\n\n"
        f"Current closing paragraph:\n{last_paragraph}\n\n"
        "Rewrite this closing paragraph to express genuine and specific interest "
        "in this company and role. Keep it concise and professional. "
        "Return only the rewritten paragraph text, without any preamble."
    )
    return llm.invoke([("human", message)]).content
