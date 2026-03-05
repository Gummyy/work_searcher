import os
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
from langchain_ollama import ChatOllama
from langgraph.graph import END, StateGraph
from odf import teletype, text
from odf.opendocument import OpenDocumentSpreadsheet, OpenDocumentText, load
from odf.table import Table, TableRow, TableCell

from agents.types import (
    JobRow,
    ParsedJob,
    PipelineState,
    RankingOutput,
    ScoringInput,
    build_ranking_output,
)
from apis.jobspy import fetch_jobs
from apis.scraping.base_scraper import BaseScraper
from apis.scraping.indeed_scraper import IndeedScraper
from apis.scraping.linkedin_scraper import LinkedinScraper
from config.types import FileOrContent
from files.File import ODF_EXTENSIONS
from logger import logger

_MAX_FETCH_RETRIES: int = 3
_FETCH_RETRY_BASE_SLEEP: float = 10.0

_MAX_SCRAPE_RETRIES: int = 3
_SCRAPE_RETRY_BASE_SLEEP: float = 10.0

_MAX_LLM_RETRIES: int = 3

_SCRAPER_MAP: dict[str, type[BaseScraper]] = {
    "indeed": IndeedScraper,
    "linkedin": LinkedinScraper,
}

# Maps URL hostname substrings to the corresponding _SCRAPER_MAP key.
_URL_SITE_MAP: dict[str, str] = {
    "indeed.com": "indeed",
    "linkedin.com": "linkedin",
}

_PROMPTS_DIR = Path(__file__).parent.parent.parent / "prompts"
_SCORING_SYSTEM_PROMPT = (_PROMPTS_DIR / "scoring_system_prompt.md").read_text(
    encoding="utf-8"
)
_SCORING_USER_MESSAGE_TEMPLATE = (
    _PROMPTS_DIR / "scoring_user_message_template.md"
).read_text(encoding="utf-8")


def _build_scoring_user_message(scoring_input: ScoringInput) -> str:
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


def build_pipeline_graph(model_name: str = "llama3") -> StateGraph:
    """Builds and compiles the full pipeline LangGraph agent.

    The entry point is determined from the initial state:
    - parsed_jobs non-empty → score_all_node (file-based input, no scraping needed)
    - job_rows non-empty   → scrape_node    (URL-based input, scraping needed)
    - both empty           → fetch_jobs_node (API-based input)

    Args:
        model_name (str): Ollama model identifier passed to the ranking and
            cover-letter rewrite LLM calls. Defaults to "llama3".

    Returns:
        StateGraph: The compiled LangGraph application ready to invoke.
    """

    def _route(state: PipelineState) -> str:
        if state["parsed_jobs"]:
            return "score_all"
        if state["job_rows"]:
            return "scrape"
        return "fetch_jobs"

    def fetch_jobs_node(state: PipelineState) -> PipelineState:
        """Fetches job listings from all configured APIs via jobspy.

        Retries up to _MAX_FETCH_RETRIES times on failure, with linear backoff
        of _FETCH_RETRY_BASE_SLEEP * attempt seconds.

        Args:
            state (PipelineState): Current graph state.

        Returns:
            PipelineState: Updated state with 'job_rows' populated.

        Raises:
            RuntimeError: If all fetch attempts are exhausted.
        """
        for attempt in range(1, _MAX_FETCH_RETRIES + 1):
            try:
                frames = [fetch_jobs(api_call) for api_call in state["api_calls"]]
                df = pd.concat(frames, ignore_index=True).drop_duplicates(
                    subset="job_url"
                )
                job_rows = [
                    JobRow(site=str(row["site"]), job_url=str(row["job_url"]))
                    for row in df[["site", "job_url"]].to_dict(orient="records")
                ]
                logger.info(f"Fetched {len(job_rows)} job listings.")
                return {**state, "job_rows": job_rows}
            except Exception as e:
                if attempt == _MAX_FETCH_RETRIES:
                    logger.error(
                        f"Job fetch failed after {_MAX_FETCH_RETRIES} attempts: {e}"
                    )
                    raise RuntimeError("Job fetch exhausted all retries.") from e
                sleep_time = _FETCH_RETRY_BASE_SLEEP * attempt
                logger.warning(
                    f"Fetch attempt {attempt}/{_MAX_FETCH_RETRIES} failed: {e} — retrying in {sleep_time:.0f}s."
                )
                time.sleep(sleep_time)
        return state  # unreachable, satisfies type checker

    def scrape_node(state: PipelineState) -> PipelineState:
        """Scrapes each job URL and produces a ParsedJob for each.

        Rows whose site has no registered scraper are skipped with a warning.
        Each scrape is retried up to _MAX_SCRAPE_RETRIES times with linear
        backoff; rows that exhaust retries are skipped with an error log.

        Args:
            state (PipelineState): Current graph state with job_rows populated.

        Returns:
            PipelineState: Updated state with 'parsed_jobs' populated.
        """
        parsed_jobs: list[ParsedJob] = []

        for i, job_row in enumerate(state["job_rows"], start=1):
            scraper_cls = _SCRAPER_MAP.get(job_row.site.lower())
            if scraper_cls is None:
                logger.warning(
                    f"No scraper registered for site '{job_row.site}' — skipping job {i}."
                )
                continue

            for attempt in range(1, _MAX_SCRAPE_RETRIES + 1):
                try:
                    with scraper_cls(job_row.job_url) as scraper:
                        parsed_jobs.append(scraper.scrape())
                    logger.info(
                        f"Scraped job {i}/{len(state['job_rows'])} ({job_row.site})."
                    )
                    break
                except Exception as e:
                    if attempt == _MAX_SCRAPE_RETRIES:
                        logger.error(
                            f"Scrape exhausted for job {i}/{len(state['job_rows'])} ({job_row.site}) — skipping: {e}"
                        )
                    else:
                        sleep_time = _SCRAPE_RETRY_BASE_SLEEP * attempt
                        logger.warning(
                            f"Scrape attempt {attempt}/{_MAX_SCRAPE_RETRIES} failed for job {i}: {e} — retrying in {sleep_time:.0f}s."
                        )
                        time.sleep(sleep_time)

        logger.info(
            f"Scraping complete: {len(parsed_jobs)}/{len(state['job_rows'])} jobs ready for scoring."
        )
        return {**state, "parsed_jobs": parsed_jobs}

    def score_all_node(state: PipelineState) -> PipelineState:
        """Scores every ParsedJob using the job offering ranker.

        Each LLM call is retried up to _MAX_LLM_RETRIES times on failure.
        Jobs whose scoring is exhausted are skipped with an error log.

        Args:
            state (PipelineState): Current graph state with parsed_jobs populated.

        Returns:
            PipelineState: Updated state with 'rankings' populated.
        """
        llm = ChatOllama(model=model_name)
        rankings = []
        for i, parsed_job in enumerate(state["parsed_jobs"], start=1):
            scoring_input = ScoringInput(
                job_description=parsed_job.job_description,
                profile=state["profile"],
                preferences=state["preferences"],
                document_categories=state["document_categories"],
            )
            structured_llm = llm.with_structured_output(
                build_ranking_output(scoring_input)
            )
            messages = [
                ("system", _SCORING_SYSTEM_PROMPT),
                ("human", _build_scoring_user_message(scoring_input)),
            ]
            for attempt in range(1, _MAX_LLM_RETRIES + 1):
                try:
                    rankings.append(structured_llm.invoke(messages))
                    logger.info(f"Scored job {i}/{len(state['parsed_jobs'])}.")
                    break
                except Exception as e:
                    if attempt == _MAX_LLM_RETRIES:
                        logger.error(
                            f"LLM scoring exhausted for job {i}/{len(state['parsed_jobs'])} — skipping: {e}"
                        )
                    else:
                        logger.warning(
                            f"LLM attempt {attempt}/{_MAX_LLM_RETRIES} failed for job {i}: {e} — retrying."
                        )
        return {**state, "rankings": rankings}

    def write_output_node(state: PipelineState) -> PipelineState:
        """Writes per-job output folders and a summary CSV to out_dir.

        For each (ParsedJob, RankingOutput) pair: creates a
        '{company}__{job_title}' subdirectory, copies or writes the resume
        and cover letter for the matched document category, then rewrites the
        cover letter's last paragraph via LLM. Finally writes a
        '{DATETIME}_summary.csv' file aggregating all rankings.

        Args:
            state (PipelineState): Current graph state with parsed_jobs and
                rankings populated.

        Returns:
            PipelineState: State unchanged (side-effect node).
        """
        out_dir = state["out_dir"]
        doc_map = {doc.category: doc for doc in state["document_categories"]}

        for parsed_job, ranking in zip(state["parsed_jobs"], state["rankings"]):
            job_dir = out_dir / f"{parsed_job.company}__{parsed_job.job_title}"
            job_dir.mkdir(parents=True, exist_ok=True)

            doc = doc_map.get(ranking.related_category)
            if doc is None:
                logger.warning(
                    f"No document found for category '{ranking.related_category}' "
                    f"— skipping output for '{parsed_job.job_title}'."
                )
                continue

            resume_dest = job_dir / _dest_name(doc.resume, "resume")
            _copy_or_write(doc.resume, resume_dest)
            _convert_to_pdf(resume_dest)

            cover_dest = job_dir / _dest_name(doc.cover_letter, "cover_letter")
            _copy_or_write(doc.cover_letter, cover_dest)
            _rewrite_last_paragraph(cover_dest, parsed_job.job_description, model_name)
            _convert_to_pdf(cover_dest)

            logger.info(
                f"Output written for '{parsed_job.company}__{parsed_job.job_title}'."
            )

        _write_summary_ods(out_dir, state["parsed_jobs"], state["rankings"])
        return state

    graph = StateGraph(PipelineState)
    graph.add_node("fetch_jobs", fetch_jobs_node)
    graph.add_node("scrape", scrape_node)
    graph.add_node("score_all", score_all_node)
    graph.add_node("write_output", write_output_node)
    graph.set_conditional_entry_point(
        _route,
        {
            "fetch_jobs": "fetch_jobs",
            "scrape": "scrape",
            "score_all": "score_all",
        },
    )
    graph.add_edge("fetch_jobs", "scrape")
    graph.add_edge("scrape", "score_all")
    graph.add_edge("score_all", "write_output")
    graph.add_edge("write_output", END)
    return graph.compile()


def _dest_name(doc_field: FileOrContent, fallback_stem: str) -> str:
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


def _copy_or_write(doc_field: FileOrContent, dest_path: Path) -> None:
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


def _rewrite_last_paragraph(
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


def _convert_to_pdf(file_path: Path) -> None:
    """Converts a file to PDF using LibreOffice in headless mode.

    Reads the LibreOffice executable path from the LIBREOFFICE_PATH environment
    variable. If the variable is not set, a warning is logged and the conversion
    is skipped. Set LIBREOFFICE_PATH in a .env file or your shell environment:
      - Windows example: C:\\Program Files\\LibreOffice\\program\\soffice.exe
      - Unix example:    libreoffice

    Args:
        file_path (Path): Path to the file to convert. The resulting PDF is
            placed in the same directory.

    Raises:
        subprocess.CalledProcessError: If LibreOffice exits with a non-zero
            return code.
    """
    libreoffice_path = os.environ.get("LIBREOFFICE_PATH")
    if not libreoffice_path:
        logger.warning(
            "LIBREOFFICE_PATH is not set — skipping PDF conversion for '%s'.",
            file_path.name,
        )
        return
    try:
        subprocess.run(
            [
                libreoffice_path,
                "--headless",
                "--convert-to",
                "pdf",
                "--outdir",
                str(file_path.parent),
                str(file_path),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        logger.info("Converted '%s' to PDF.", file_path.name)
    except subprocess.CalledProcessError as e:
        logger.error("PDF conversion failed for '%s': %s", file_path.name, e.stderr)


def _write_summary_ods(
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
