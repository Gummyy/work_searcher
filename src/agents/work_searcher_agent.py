import time
from pathlib import Path

import pandas as pd
from langchain_ollama import ChatOllama
from langgraph.graph import END, StateGraph

from agents.types import (
    JobRow,
    ParsedJob,
    PipelineState,
    ScoringInput,
    build_ranking_output,
)
from agents.work_searcher_actions import (
    SCORING_SYSTEM_PROMPT,
    build_scoring_user_message,
    copy_or_write,
    dest_name,
    rewrite_last_paragraph,
    write_summary_ods,
)
from apis.jobspy import fetch_jobs
from apis.scraping.base_scraper import BaseScraper
from apis.scraping.indeed_scraper import IndeedScraper
from apis.scraping.linkedin_scraper import LinkedinScraper
from files.File import convert_to_pdf
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
                ("system", SCORING_SYSTEM_PROMPT),
                ("human", build_scoring_user_message(scoring_input)),
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

            resume_dest = job_dir / dest_name(doc.resume, "resume")
            copy_or_write(doc.resume, resume_dest)
            convert_to_pdf(resume_dest)

            cover_dest = job_dir / dest_name(doc.cover_letter, "cover_letter")
            copy_or_write(doc.cover_letter, cover_dest)
            rewrite_last_paragraph(cover_dest, parsed_job.job_description, model_name)
            convert_to_pdf(cover_dest)

            logger.info(
                f"Output written for '{parsed_job.company}__{parsed_job.job_title}'."
            )

        write_summary_ods(out_dir, state["parsed_jobs"], state["rankings"])
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
