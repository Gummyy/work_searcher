from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field
from typing_extensions import TypedDict

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


class SingleJobState(TypedDict):
    """State for the single-job scoring agent.

    Attributes:
        job_offering (str): Raw text of the job offering being evaluated.
        profile (str): Raw text of the candidate's profile.
        preferences (str): Raw text of the candidate's job preferences.
        ranking (RankingOutput | None): Structured output produced by the
            scoring model. None until the scoring step runs.
    """

    job_offering: str
    profile: str
    preferences: str
    ranking: Optional[RankingOutput]


class PipelineState(TypedDict):
    """Full state of the pipeline agent throughout its execution.

    Attributes:
        profile (str): Raw text of the candidate's profile.
        preferences (str): Raw text of the candidate's job preferences.
        api_data (dict[str, Any]): Data fetched from external APIs (e.g. job
            boards), keyed by source name. Empty until the fetch step runs.
        rankings (list[RankingOutput]): One ranking per job offering scored.
            Empty until the score_all step runs.
    """

    profile: str
    preferences: str
    api_data: dict[str, Any]
    rankings: list[RankingOutput]
