import argparse
import sys
from pathlib import Path
from typing import Literal

from agents.scoring_agent import build_pipeline_graph
from agents.single_job_agent import build_single_job_graph
from agents.types import ScoringInput
from config.Config import Config
from config.types import DocumentCategory
from files.File import read_file_content, validate_file
from logger import logger


def parse_arguments() -> argparse.Namespace:
    """Parses command-line arguments.

    Returns:
        argparse.Namespace: The parsed arguments containing 'config' and 'out' paths.
    """
    parser = argparse.ArgumentParser(
        description="Process job applications based on configuration."
    )
    parser.add_argument(
        "--config",
        dest="config_path",
        type=str,
        required=True,
        help="Path to the configuration file (e.g., config.json)",
    )
    parser.add_argument(
        "--out",
        dest="out_path",
        type=str,
        required=True,
        help="Path to the output directory",
    )
    parser.add_argument(
        "--job",
        dest="job_path",
        type=str,
        required=False,
        help="Path to the job offering file (.txt, .odt, ...)",
    )
    parser.add_argument(
        "--model",
        dest="model_name",
        type=Literal["llama3", "llama2"],
        default="llama3",
        help="Ollama model name to use for scoring (default: llama3)",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_arguments()

    try:
        config = Config(args.config_path).get_config()
    except ValueError as e:
        logger.error(f"Error loading config: {e}")
        sys.exit(1)

    out_dir = Path(args.out_path)
    if not out_dir.parent.exists():
        logger.error(
            f"Parent directory of output path does not exist: {out_dir.parent}"
        )
        sys.exit(1)

    if args.job_path is not None:
        if config.api_calls is not None:
            logger.warning(
                "Both --job and api_calls are provided. api_calls will be ignored."
            )

        try:
            validate_file(args.job_path)
            job_offering = read_file_content(args.job_path)
        except ValueError as e:
            logger.error(f"Error loading job offering: {e}")
            sys.exit(1)

        scoring_input = ScoringInput(
            job_description=job_offering,
            profile=config.profile.content,
            preferences=config.preferences.content,
            document_categories=[
                DocumentCategory(category=doc.category, description=doc.description)
                for doc in config.documents
            ],
        )
        final_state = build_single_job_graph(model_name=args.model_name).invoke(
            {"scoring_input": scoring_input, "ranking": None}
        )
        ranking = final_state["ranking"]
        logger.info(
            f"Candidate rank : {ranking.candidate_rank.rank}/100\n"
            f"  {ranking.candidate_rank.explanation}\n\n"
            f"Offering rank  : {ranking.offering_rank.rank}/100\n"
            f"  {ranking.offering_rank.explanation}"
        )
    else:
        if config.api_calls is None:
            logger.error(
                "No job source provided: supply --job or include api_calls in the config."
            )
            sys.exit(1)

        document_categories = [
            DocumentCategory(category=doc.category, description=doc.description)
            for doc in config.documents
        ]
        final_state = build_pipeline_graph(model_name=args.model_name).invoke(
            {
                "profile": config.profile.content,
                "preferences": config.preferences.content,
                "document_categories": document_categories,
                "api_calls": config.api_calls,
                "job_rows": [],
                "job_descriptions": [],
                "rankings": [],
            }
        )
        for i, ranking in enumerate(final_state["rankings"], start=1):
            logger.info(
                f"[Job {i}] Candidate rank : {ranking.candidate_rank.rank}/100\n"
                f"         {ranking.candidate_rank.explanation}\n"
                f"         Offering rank  : {ranking.offering_rank.rank}/100\n"
                f"         {ranking.offering_rank.explanation}"
            )
