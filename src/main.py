import argparse
import sys
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv

from agents.utils import build_job_rows, build_parsed_jobs
from agents.work_searcher_agent import build_pipeline_graph
from config.Config import Config
from logger import logger

load_dotenv()


def parse_arguments() -> argparse.Namespace:
    """Parses command-line arguments.

    Returns:
        argparse.Namespace: The parsed arguments containing 'config', 'out',
            'job', 'job_url', and 'model' values.
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
        "--job_file",
        dest="job_paths",
        type=str,
        nargs="+",
        required=False,
        help="One or more job offering files, each named '$COMPANY__$JOB_TITLE.ext'",
    )
    parser.add_argument(
        "--job_url",
        dest="job_urls",
        type=str,
        nargs="+",
        required=False,
        help="One or more direct URLs to job listings to scrape and score",
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

    has_job_paths = bool(args.job_paths)
    has_job_urls = bool(args.job_urls)
    has_api_calls = config.api_calls is not None

    if not has_job_paths and not has_job_urls and not has_api_calls:
        logger.error(
            "No job source provided: supply --job, --job_url, or include api_calls in the config."
        )
        sys.exit(1)

    if (has_job_paths or has_job_urls) and has_api_calls:
        logger.warning(
            "Both direct job sources and api_calls are provided. api_calls will be ignored."
        )

    try:
        parsed_jobs = build_parsed_jobs(args.job_paths or [])
    except ValueError as e:
        logger.error(f"Error loading job files: {e}")
        sys.exit(1)

    try:
        job_rows = build_job_rows(args.job_urls or [])
    except ValueError as e:
        logger.error(f"Error parsing job URLs: {e}")
        sys.exit(1)

    out_dir = Path(args.out_path)
    if not out_dir.parent.exists():
        logger.error(
            f"Parent directory of output path does not exist: {out_dir.parent}"
        )
        sys.exit(1)
    try:
        out_dir.mkdir(exist_ok=True)
    except Exception as e:
        logger.error(f"Error creating output directory: {e}")
        sys.exit(1)

    build_pipeline_graph(model_name=args.model_name).invoke(
        {
            "profile": config.profile.content,
            "preferences": config.preferences.content,
            "document_categories": config.documents,
            "api_calls": config.api_calls or [],
            "out_dir": out_dir,
            "job_rows": job_rows,
            "parsed_jobs": parsed_jobs,
            "rankings": [],
        }
    )
