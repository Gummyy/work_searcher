import shutil
import time
from pathlib import Path

from langchain_ollama import ChatOllama
from langgraph.graph import END, StateGraph
from langgraph.types import Send

from agents.types import (
    CoverRewriteJob,
    CoverRewriteResult,
    JobRow,
    ParsedJob,
    PipelineState,
    RankingOutput,
    ScoredOffering,
    ScoringInput,
    ScoringJob,
    build_ranking_output,
)
from agents.work_searcher_actions import (
    SCORING_SYSTEM_PROMPT,
    build_scoring_user_message,
    extract_cover_last_paragraph,
    write_job_output,
    write_summary_ods,
)
from apis.scraping.base_scraper import BaseScraper
from apis.scraping.indeed_scraper import IndeedScraper
from apis.scraping.linkedin_scraper import LinkedinScraper
from logger import logger

_MAX_FETCH_RETRIES: int = 3
_FETCH_RETRY_BASE_SLEEP: float = 10.0

_MAX_SCRAPE_RETRIES: int = 3
_SCRAPE_RETRY_BASE_SLEEP: float = 10.0

_MAX_LLM_RETRIES: int = 3
_COVER_REWRITE_SIMULTANEOUS_JOBS: int = 3
_SCORING_SIMULTANEOUS_JOBS: int = 3

_SCRAPER_MAP: dict[str, type[BaseScraper]] = {
    "indeed": IndeedScraper,
    "linkedin": LinkedinScraper,
}


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


def build_pipeline_graph(model_name: str = "llama3") -> StateGraph:
    """Builds and compiles the full pipeline LangGraph agent.

    The entry point is determined from the initial state:
    - parsed_jobs non-empty → score_all_node        (file-based input, no scraping needed)
    - job_rows non-empty   → scrape_node            (URL-based input, scraping needed)
    - both empty           → one Send per api_call  (API-based input, parallel fetch)

    Args:
        model_name (str): Ollama model identifier passed to the ranking and
            cover-letter rewrite LLM calls. Defaults to "llama3".

    Returns:
        StateGraph: The compiled LangGraph application ready to invoke.
    """

    def _route_rewrites(state: PipelineState) -> list[Send]:
        """Routes to parallel cover-rewrite batches or directly to write_files.

        When cancelled or no job requires writing, routes directly to write_files.
        Otherwise, groups jobs with status 'created' or 'updated' into batches
        of _COVER_REWRITE_BATCH_SIZE and sends each batch to rewrite_cover_batch.

        Args:
            state (PipelineState): Current graph state after collect_confirmations.

        Returns:
            list[Send]: One Send per batch, or one Send directly to write_files.
        """
        if state.get("cancelled", False):
            return [Send("write_files", {})]

        doc_map = {doc.category: doc for doc in state["document_categories"]}
        jobs_to_rewrite: list[CoverRewriteJob] = [
            CoverRewriteJob(
                job_idx=i,
                job_description=parsed_job.job_description,
                cover_content=doc_map[ranking.related_category].cover_letter.content,
            )
            for i, (parsed_job, ranking) in enumerate(
                zip(state["parsed_jobs"], state["rankings"])
            )
            if ranking.status in ("created", "updated")
        ]

        if not jobs_to_rewrite:
            return [Send("write_files", {})]

        batches = [
            [
                job_to_rewrite
                for j, job_to_rewrite in enumerate(jobs_to_rewrite)
                if j % _COVER_REWRITE_SIMULTANEOUS_JOBS == i
            ]
            for i in range(_COVER_REWRITE_SIMULTANEOUS_JOBS)
        ]
        return [
            Send("rewrite_cover_batch", {"cover_rewrite_batch": batch})
            for batch in batches
        ]

    def _route_scoring(state: PipelineState) -> list[Send]:
        """Routes each parsed job to a dedicated score_batch_of_offerings node.

        Args:
            state (PipelineState): Current graph state with parsed_jobs populated.

        Returns:
            list[Send]: One Send per parsed job, dispatching to score_batch_of_offerings.
        """
        return [
            Send(
                "score_batch_of_offerings",
                {
                    "scoring_jobs": [
                        ScoringJob(job_idx=j, parsed_job=job)
                        for j, job in enumerate(state["parsed_jobs"])
                        if j % _SCORING_SIMULTANEOUS_JOBS == i
                    ]
                },
            )
            for i in range(_SCORING_SIMULTANEOUS_JOBS)
        ]

    def _starting_route(state: PipelineState) -> str | list[Send]:
        if state["parsed_jobs"]:
            return _route_scoring(state)
        if state["job_rows"]:
            return "scrape"
        return [
            Send("fetch_single_api", {"api_call": api_call})
            for api_call in state["api_calls"]
        ]

    def fetch_single_api_node(state: PipelineState) -> dict[str, list[JobRow]]:
        """Fetches jobs for one API call descriptor selected by the fetch factory.

        Retries up to _MAX_FETCH_RETRIES times on failure, with linear backoff
        of _FETCH_RETRY_BASE_SLEEP * attempt seconds.

        Args:
            state (PipelineState): Branch state containing a single api_call.

        Returns:
            dict[str, list[JobRow]]: Partial state update merged into job_rows
                via the reducer defined on PipelineState.

        Raises:
            RuntimeError: If all fetch attempts are exhausted for this api_call.
        """
        api_call = state["api_call"]
        for attempt in range(1, _MAX_FETCH_RETRIES + 1):
            try:
                df = api_call.fetcher.fetch_jobs()
                job_rows = [
                    JobRow(site=str(row["site"]), job_url=str(row["job_url"]))
                    for row in df[["site", "job_url"]].to_dict(orient="records")
                ]
                logger.info(
                    f"Fetched {len(job_rows)} job listings with tool '{api_call.tool}'."
                )
                return {"job_rows": job_rows}
            except Exception as e:
                if attempt == _MAX_FETCH_RETRIES:
                    logger.error(
                        f"Job fetch failed for tool '{api_call.tool}' after {_MAX_FETCH_RETRIES} attempts: {e}"
                    )
                    raise RuntimeError(
                        f"Job fetch exhausted all retries for tool '{api_call.tool}'."
                    ) from e
                sleep_time = _FETCH_RETRY_BASE_SLEEP * attempt
                logger.warning(
                    f"Fetch attempt {attempt}/{_MAX_FETCH_RETRIES} failed for tool '{api_call.tool}': {e} — retrying in {sleep_time:.0f}s."
                )
                time.sleep(sleep_time)
        return {"job_rows": []}  # unreachable, satisfies type checker

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

    def score_batch_of_offerings_node(
        state: PipelineState,
    ) -> dict[str, list[ScoredOffering]]:
        """Scores a batch of parsed jobs using the structured LLM ranker.

        Retries up to _MAX_LLM_RETRIES times on failure. Returns an empty list on
        exhaustion so the parsed jobs are silently dropped from the final aligned output.

        Args:
            state (PipelineState): Branch state with scoring_jobs populated by the
                Send from _route_scoring, plus the full shared state fields.

        Returns:
            dict[str, list[ScoredOffering]]: Partial state update accumulated via
                the scored_offerings reducer across all parallel invocations.
        """
        llm = ChatOllama(model=model_name)
        scoring_jobs = state["scoring_jobs"]
        total = len(state["parsed_jobs"])
        scored_offerings: list[ScoredOffering] = []
        for scoring_job in scoring_jobs:
            job_idx = scoring_job["job_idx"]
            parsed_job = scoring_job["parsed_job"]
            try:
                scoring_input = ScoringInput(
                    job_description=parsed_job.job_description,
                    profile=state["profile"],
                    preferences=state["preferences"],
                    document_categories=state["document_categories"],
                )
            except Exception as e:
                logger.error(
                    f"Failed to build scoring input for job {job_idx + 1}/{total} — skipping: {e}"
                )
                continue
            structured_llm = llm.with_structured_output(
                build_ranking_output(scoring_input)
            )
            messages = [
                ("system", SCORING_SYSTEM_PROMPT),
                ("human", build_scoring_user_message(scoring_input)),
            ]
            for attempt in range(1, _MAX_LLM_RETRIES + 1):
                try:
                    llm_result = structured_llm.invoke(messages)
                    ranking = RankingOutput(
                        candidate_rank=llm_result.candidate_rank,
                        offering_rank=llm_result.offering_rank,
                        related_category=llm_result.related_category,
                    )
                    logger.info(f"Scored job {job_idx + 1}/{total}.")
                    scored_offerings.append(
                        {
                            "job_idx": job_idx,
                            "parsed_job": parsed_job,
                            "ranking": ranking,
                        }
                    )
                    break
                except Exception as e:
                    if attempt == _MAX_LLM_RETRIES:
                        logger.error(
                            f"LLM scoring exhausted for job {job_idx + 1}/{total} — skipping: {e}"
                        )
                    else:
                        logger.warning(
                            f"LLM attempt {attempt}/{_MAX_LLM_RETRIES} failed for job {job_idx + 1}: {e} — retrying."
                        )
        return {"scored_offerings": scored_offerings}

    def collect_scores_node(state: PipelineState) -> dict:
        """Reassembles parallel scoring results into aligned parsed_jobs and rankings.

        Sorts the accumulated scored_offerings by original job index to restore
        the order from parsed_jobs, then sets parsed_jobs and rankings from the
        successful entries only.

        Args:
            state (PipelineState): State with scored_offerings accumulated across
                all parallel score_batch_of_offerings nodes.

        Returns:
            dict: Partial state update with parsed_jobs and rankings populated.
        """
        sorted_offerings = sorted(
            state.get("scored_offerings", []), key=lambda o: o["job_idx"]
        )
        return {
            "parsed_jobs": [o["parsed_job"] for o in sorted_offerings],
            "rankings": [o["ranking"] for o in sorted_offerings],
        }

    def collect_confirmations(state: PipelineState) -> PipelineState:
        """Prompts the user about directory conflicts and sets each ranking's status.

        Iterates through (ranking, parsed_job) pairs. For each job whose output
        directory already exists, the user is prompted to choose: override (Y),
        override all (T), keep (N), keep all (K), or cancel (X). Jobs with no
        matching document category are silently skipped. No file I/O or LLM
        calls are performed here.

        When the user chooses X, all rankings (including previously confirmed
        ones) are set to 'aborted' and cancelled is set to True.

        Args:
            state (PipelineState): Current graph state with parsed_jobs and
                rankings populated.

        Returns:
            PipelineState: Updated state with ranking statuses and cancelled flag.
        """
        out_dir = state["out_dir"]
        doc_map = {doc.category: doc for doc in state["document_categories"]}
        rankings = list(state["rankings"])

        override_all = False
        keep_all = False
        cancelled = False

        for ranking, parsed_job in zip(rankings, state["parsed_jobs"]):
            if doc_map.get(ranking.related_category) is None:
                logger.warning(
                    f"No document found for category '{ranking.related_category}' "
                    f"— skipping output for '{parsed_job.job_title}'."
                )
                ranking.status = "skipped"
                continue

            job_dir = out_dir / f"{parsed_job.company}__{parsed_job.job_title}"

            if not job_dir.exists():
                ranking.status = "created"
                continue

            if keep_all:
                ranking.status = "skipped"
                continue

            if not override_all:
                while True:
                    print(
                        f"\nOutput directory for '{parsed_job.job_title}' already exists.\n"
                        "  [Y] Override   [T] Override all   [N] Keep   [K] Keep all   [X] Cancel"
                    )
                    choice = input("Choice: ").strip().upper()
                    if choice in ("Y", "T", "N", "K", "X"):
                        break
                if choice == "X":
                    logger.info("Output writing cancelled by user.")
                    cancelled = True
                    break
                if choice == "K":
                    keep_all = True
                    ranking.status = "skipped"
                    continue
                if choice == "N":
                    ranking.status = "skipped"
                    continue
                if choice == "T":
                    override_all = True
            ranking.status = "updated"

        if cancelled:
            for r in rankings:
                r.status = "aborted"

        return {
            **state,
            "rankings": rankings,
            "cover_rewrites": [],
            "cancelled": cancelled,
        }

    def rewrite_cover_batch_node(
        state: PipelineState,
    ) -> dict[str, list[CoverRewriteResult]]:
        """Rewrites the cover letter closing for each job in the assigned batch.

        Extracts the last paragraph from each job's cover letter content, calls
        the LLM to rewrite it, and returns a partial state update. Parallel
        invocations of this node are merged via the cover_rewrites reducer.

        Args:
            state (PipelineState): Branch state with cover_rewrite_batch populated
                by the Send from _route_rewrites.

        Returns:
            dict[str, list[CoverRewriteResult]]: Partial state update with
                cover_rewrites entries for each successfully rewritten job.
        """
        llm = ChatOllama(model=model_name)
        cover_rewrites: list[CoverRewriteResult] = []
        for job in state["cover_rewrite_batch"]:
            last_paragraph = extract_cover_last_paragraph(job["cover_content"])
            if last_paragraph is None:
                continue
            cover_rewrites.append(
                {
                    "job_idx": job["job_idx"],
                    "rewritten_paragraph": _call_rewrite_llm(
                        llm, job["job_description"], last_paragraph
                    ),
                }
            )
        return {"cover_rewrites": cover_rewrites}

    def write_files(state: PipelineState) -> PipelineState:
        """Writes per-job output folders and a summary ODS to out_dir.

        Skips everything and returns immediately when cancelled is True.
        For each (parsed_job, ranking) pair with status 'updated' or 'created':
        deletes the existing directory if updating, then calls write_job_output
        with the pre-computed cover rewrite. Finally writes the summary ODS.

        Args:
            state (PipelineState): Current graph state after all rewrite batches
                have completed.

        Returns:
            PipelineState: State unchanged (side-effect node).
        """
        if state.get("cancelled", False):
            logger.info("Output writing aborted — no files written.")
            return state

        out_dir = state["out_dir"]
        doc_map = {doc.category: doc for doc in state["document_categories"]}
        cover_rewrites_map = {
            r["job_idx"]: r["rewritten_paragraph"]
            for r in (state.get("cover_rewrites") or [])
        }
        created_count = 0
        updated_count = 0

        for i, (parsed_job, ranking) in enumerate(
            zip(state["parsed_jobs"], state["rankings"])
        ):
            if ranking.status not in ("created", "updated"):
                continue

            job_dir = out_dir / f"{parsed_job.company}__{parsed_job.job_title}"
            if ranking.status == "updated":
                shutil.rmtree(job_dir)

            write_job_output(
                job_dir,
                doc_map[ranking.related_category],
                cover_rewrites_map.get(i),
            )

            if ranking.status == "updated":
                updated_count += 1
            else:
                created_count += 1
            logger.info(
                f"Output written for '{parsed_job.company}__{parsed_job.job_title}'."
            )

        logger.info(
            f"Output complete: {created_count} offering(s) created, {updated_count} updated."
        )
        write_summary_ods(out_dir, state["parsed_jobs"], state["rankings"])
        return state

    graph = StateGraph(PipelineState)
    graph.add_node("fetch_single_api", fetch_single_api_node)
    graph.add_node("scrape", scrape_node)
    graph.add_node("score_batch_of_offerings", score_batch_of_offerings_node)
    graph.add_node("collect_scores", collect_scores_node)
    graph.add_node("collect_confirmations", collect_confirmations)
    graph.add_node("rewrite_cover_batch", rewrite_cover_batch_node)
    graph.add_node("write_files", write_files)
    graph.set_conditional_entry_point(
        _starting_route,
        {"scrape": "scrape"},
    )
    graph.add_edge("fetch_single_api", "scrape")
    graph.add_conditional_edges("scrape", _route_scoring)
    graph.add_edge("score_batch_of_offerings", "collect_scores")
    graph.add_edge("collect_scores", "collect_confirmations")
    graph.add_conditional_edges("collect_confirmations", _route_rewrites)
    graph.add_edge("rewrite_cover_batch", "write_files")
    graph.add_edge("write_files", END)
    return graph.compile()
