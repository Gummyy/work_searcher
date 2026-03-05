from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, create_model
from typing_extensions import TypedDict

from config.types import APICalls, Document

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
            _PROMPTS_DIR / "ranking_output_offering_rank_description.md"
        ).read_text(encoding="utf-8")
    )
    related_category: str = Field(
        description=(
            _PROMPTS_DIR / "ranking_output_related_category_description.md"
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


class ParsedJob(BaseModel):
    """A fully parsed job offering ready for scoring and output writing.

    Produced either by the scraper (from a live URL) or by parsing a local
    job file whose name follows the '$COMPANY__$JOB_TITLE.ext' convention.

    Attributes:
        company (str): Company name.
        job_title (str): Job title.
        job_description (str): LLM-ready formatted job description text.
        job_url (str): URL of the job listing, or the local file path when
            sourced from --job_path.
    """

    company: str
    job_title: str
    job_description: str
    job_url: str


class ScoringInput(BaseModel):
    """Structured input fed to the LLM for a single job scoring request.

    Attributes:
        job_description (str): LLM-ready formatted description produced by the scraper.
        profile (str): Raw text of the candidate's profile.
        preferences (str): Raw text of the candidate's job preferences.
        document_categories (list[Document]): Available resume/cover letter
            categories with their domain descriptions.
    """

    job_description: str
    profile: str
    preferences: str
    document_categories: list[Document]


class PipelineState(TypedDict):
    """Full state of the pipeline agent throughout its execution.

    Attributes:
        profile (str): Raw text of the candidate's profile.
        preferences (str): Raw text of the candidate's job preferences.
        document_categories (list[Document]): Document category descriptors
            built from config before entering the pipeline.
        api_calls (list[APICalls]): Configured API descriptors used to fetch
            job offerings. Empty when job_rows or parsed_jobs are pre-populated.
        out_dir (Path): Directory where output folders and the summary ODS are
            written.
        job_rows (list[JobRow]): Minimal job records (site + url). Pre-populated
            when --job_url is used; otherwise filled by fetch_jobs_node.
        parsed_jobs (list[ParsedJob]): Full job records. Pre-populated when
            --job is used; otherwise filled by scrape_node.
        rankings (list[RankingOutput]): One ranking per scored job offering.
            Empty until score_all_node runs.
    """

    profile: str
    preferences: str
    document_categories: list[Document]
    api_calls: list[APICalls]
    out_dir: Path
    job_rows: list[JobRow]
    parsed_jobs: list[ParsedJob]
    rankings: list[RankingOutput]


def build_ranking_output(scoring_input: ScoringInput) -> type[BaseModel]:
    """Builds a RankingOutput object with a related_category key where the LLM chooses the relevant documents
    associated with the job_offering. The type built in this function ensures that only existing categories mentioned
    in the document_categories list of the ScoringInput can be chosen by the LLM.

    Args:
        scoring_input (ScoringInput): The structured LLM input for one job, containing the document categories.

    Returns:
        BaseModel: The BaseModel object with the related_category key added to the candidate_rank and offering_rank fields.
    """
    literal_categories = tuple(
        set([dc.category for dc in scoring_input.document_categories])
    )

    related_categories = Literal[literal_categories]

    return create_model(
        "RankingOutputWithRelatedCategory",
        candidate_rank=(RankScore, Field(...)),
        offering_rank=(RankScore, Field(...)),
        related_category=(
            related_categories,
            Field(
                None,
                description="The document category most relevant to the job offering, chosen from the provided document categories.",
            ),
        ),
    )
