from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field
from typing_extensions import TypedDict

from config.types import APICalls, DocumentCategory

_PROMPTS_DIR = Path(__file__).parent.parent.parent / "prompts"


class RankScore(BaseModel):
    """A numeric rank with an associated justification text.

    Attributes:
        rank (int): Numeric score from 0 (no fit at all) to 100 (perfect fit).
        explanation (str): Justification for the assigned rank.
    """

    rank: int = Field(
        ge=0,
        le=100,
        description=(_PROMPTS_DIR / "rank_score_rank_description.txt").read_text(
            encoding="utf-8"
        ),
    )
    explanation: str = Field(
        description=(_PROMPTS_DIR / "rank_score_explanation_description.txt").read_text(
            encoding="utf-8"
        )
    )


class RankingOutput(BaseModel):
    """Structured output produced by the scoring agent for a job application.

    Attributes:
        candidate_rank (RankScore): How well the candidate's profile matches the job offering.
        offering_rank (RankScore): How well the job offering matches the candidate's preferences.
    """

    candidate_rank: RankScore = Field(
        description=(
            _PROMPTS_DIR / "ranking_output_candidate_rank_description.txt"
        ).read_text(encoding="utf-8")
    )
    offering_rank: RankScore = Field(
        description=(
            _PROMPTS_DIR / "ranking_output_offering_rank_description.txt"
        ).read_text(encoding="utf-8")
    )


class JobRow(BaseModel):
    """Minimal representation of a jobspy DataFrame row needed for scraping.

    Attributes:
        site (str): Job board identifier (e.g. 'linkedin', 'indeed').
        job_url (str): Direct URL to the job listing page.
    """

    site: str
    job_url: str


class ScoringInput(BaseModel):
    """Structured input fed to the LLM for a single job scoring request.

    Attributes:
        job_description (str): LLM-ready formatted description produced by the scraper.
        profile (str): Raw text of the candidate's profile.
        preferences (str): Raw text of the candidate's job preferences.
        document_categories (list[DocumentCategory]): Available resume/cover letter
            categories with their domain descriptions.
    """

    job_description: str
    profile: str
    preferences: str
    document_categories: list[DocumentCategory]


class SingleJobState(TypedDict):
    """State for the single-job scoring agent.

    Attributes:
        scoring_input (ScoringInput): All data required by the LLM to score one job.
        ranking (RankingOutput | None): Structured output produced by the
            scoring model. None until the scoring step runs.
    """

    scoring_input: ScoringInput
    ranking: Optional[RankingOutput]


class PipelineState(TypedDict):
    """Full state of the pipeline agent throughout its execution.

    Attributes:
        profile (str): Raw text of the candidate's profile.
        preferences (str): Raw text of the candidate's job preferences.
        document_categories (list[DocumentCategory]): Document category descriptors
            built from config before entering the pipeline.
        api_calls (list[APICalls]): Configured API descriptors used to fetch
            job offerings. Populated at invocation.
        job_rows (list[JobRow]): Minimal job records (site + url) after the
            jobspy fetch step. Empty until fetch_jobs_node runs.
        job_descriptions (list[str]): LLM-ready strings produced by the scrapers,
            one per successfully scraped job. Empty until scrape_node runs.
        rankings (list[RankingOutput]): One ranking per scored job offering.
            Empty until score_all_node runs.
    """

    profile: str
    preferences: str
    document_categories: list[DocumentCategory]
    api_calls: list[APICalls]
    job_rows: list[JobRow]
    job_descriptions: list[str]
    rankings: list[RankingOutput]
