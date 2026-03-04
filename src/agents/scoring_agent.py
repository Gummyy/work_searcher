import time

import pandas as pd
from langgraph.graph import END, StateGraph

from agents.single_job_agent import build_single_job_graph
from agents.types import JobRow, PipelineState, ScoringInput
from apis.jobspy import fetch_jobs
from apis.scraping.base_scraper import BaseScraper
from apis.scraping.indeed_scraper import IndeedScraper
from apis.scraping.linkedin_scraper import LinkedinScraper
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

    Nodes run in order: fetch_jobs_node → scrape_node → score_all_node.
    jobspy fetches job URLs, the scraper builds LLM-ready descriptions,
    and the single-job agent scores each one.

    Args:
        model_name (str): Ollama model identifier to pass to the single-job
            agent. Defaults to "llama3".

    Returns:
        StateGraph: The compiled LangGraph application ready to invoke.
    """
    single_job_graph = build_single_job_graph(model_name)

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
        """Scrapes each job URL and produces an LLM-ready description string.

        Rows whose site has no registered scraper are skipped with a warning.
        Each scrape is retried up to _MAX_SCRAPE_RETRIES times with linear
        backoff; rows that exhaust retries are skipped with an error log.

        Args:
            state (PipelineState): Current graph state with job_rows populated.

        Returns:
            PipelineState: Updated state with 'job_descriptions' populated.
        """
        job_descriptions: list[str] = []

        for i, job_row in enumerate(state["job_rows"], start=1):
            scraper_cls = _SCRAPER_MAP.get(job_row.site.lower())
            if scraper_cls is None:
                logger.warning(
                    f"No scraper registered for site '{job_row.site}' — skipping job {i}."
                )
                continue

            for attempt in range(1, _MAX_SCRAPE_RETRIES + 1):
                try:
                    with scraper_cls() as scraper:
                        job_descriptions.append(
                            scraper.get_llm_parsed_description(job_row.job_url)
                        )
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
            f"Scraping complete: {len(job_descriptions)}/{len(state['job_rows'])} jobs ready for scoring."
        )
        return {**state, "job_descriptions": job_descriptions}

    def score_all_node(state: PipelineState) -> PipelineState:
        """Scores every job description using the single-job agent.

        Builds ScoringInput just-in-time from the constant state fields and
        each job description. Each LLM call is retried up to _MAX_LLM_RETRIES
        times on failure. Jobs whose scoring is exhausted are skipped with an
        error log.

        Args:
            state (PipelineState): Current graph state with job_descriptions populated.

        Returns:
            PipelineState: Updated state with 'rankings' populated.
        """
        rankings = []
        for i, job_description in enumerate(state["job_descriptions"], start=1):
            scoring_input = ScoringInput(
                job_description=job_description,
                profile=state["profile"],
                preferences=state["preferences"],
                document_categories=state["document_categories"],
            )
            for attempt in range(1, _MAX_LLM_RETRIES + 1):
                try:
                    result = single_job_graph.invoke(
                        {"scoring_input": scoring_input, "ranking": None}
                    )["ranking"]
                    rankings.append(result)
                    logger.info(f"Scored job {i}/{len(state['job_descriptions'])}.")
                    break
                except Exception as e:
                    if attempt == _MAX_LLM_RETRIES:
                        logger.error(
                            f"LLM scoring exhausted for job {i}/{len(state['job_descriptions'])} — skipping: {e}"
                        )
                    else:
                        logger.warning(
                            f"LLM attempt {attempt}/{_MAX_LLM_RETRIES} failed for job {i}: {e} — retrying."
                        )
        return {**state, "rankings": rankings}

    graph = StateGraph(PipelineState)
    graph.add_node("fetch_jobs", fetch_jobs_node)
    graph.add_node("scrape", scrape_node)
    graph.add_node("score_all", score_all_node)
    graph.set_entry_point("fetch_jobs")
    graph.add_edge("fetch_jobs", "scrape")
    graph.add_edge("scrape", "score_all")
    graph.add_edge("score_all", END)
    return graph.compile()
