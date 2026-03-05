import argparse
import os
import subprocess
import sys
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from dotenv import load_dotenv

from agents.types import JobRow, ParsedJob
from agents.work_searcher_agent import build_pipeline_graph, _URL_SITE_MAP
from config.Config import Config
from files.File import ODF_EXTENSIONS, read_file_content, validate_file
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


def _odt_to_markdown(job_path: Path) -> str:
    """Converts an ODT file to a Markdown string using pandoc.

    Args:
        job_path (Path): Path to the .odt file.

    Returns:
        str: The file contents as GitHub-Flavoured Markdown.

    Raises:
        subprocess.CalledProcessError: If the pandoc subprocess exits with a non-zero code.
    """
    pandoc_path = os.environ.get("PANDOC_PATH", "pandoc")
    return subprocess.run(
        [pandoc_path, "--from=odt", "--to=gfm", str(job_path)],
        capture_output=True,
        text=True,
        check=True,
    ).stdout


def _build_parsed_jobs(job_paths: list[str]) -> list[ParsedJob]:
    """Parses a list of local job files into ParsedJob objects.

    Each file name must follow the '$COMPANY__$JOB_TITLE.ext' convention.

    Args:
        job_paths (list[str]): Paths to local job description files.

    Returns:
        list[ParsedJob]: One ParsedJob per valid file.

    Raises:
        ValueError: If any file name does not follow the naming convention or
            the file cannot be read.
    """
    parsed_jobs = []
    for job_path_str in job_paths:
        job_path = Path(job_path_str)
        stem = job_path.stem
        if "__" not in stem:
            raise ValueError(
                f"Job file name must follow the '$COMPANY__$JOB_TITLE' convention, got: '{stem}'."
            )
        company, job_title = stem.split("__", 1)
        validate_file(job_path_str)
        if job_path.suffix.lower() in ODF_EXTENSIONS:
            job_description = _odt_to_markdown(job_path)
        else:
            job_description = read_file_content(job_path_str)
        parsed_jobs.append(
            ParsedJob(
                company=company,
                job_title=job_title,
                job_description=job_description,
                job_url=job_path_str,
            )
        )
    return parsed_jobs


def _build_job_rows(job_urls: list[str]) -> list[JobRow]:
    """Parses a list of job URLs into JobRow objects.

    The site is detected from the URL hostname using _URL_SITE_MAP.

    Args:
        job_urls (list[str]): Direct URLs to job listings.

    Returns:
        list[JobRow]: One JobRow per valid URL.

    Raises:
        ValueError: If any URL hostname does not match a known job site.
    """
    job_rows = []
    for url in job_urls:
        hostname = urlparse(url).hostname or ""
        site = next(
            (site for domain, site in _URL_SITE_MAP.items() if domain in hostname),
            None,
        )
        if site is None:
            raise ValueError(
                f"Could not detect job site from URL '{url}'. "
                f"Supported domains: {list(_URL_SITE_MAP.keys())}."
            )
        job_rows.append(JobRow(site=site, job_url=url))
    return job_rows


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
        parsed_jobs = _build_parsed_jobs(args.job_paths or [])
    except ValueError as e:
        logger.error(f"Error loading job files: {e}")
        sys.exit(1)

    try:
        job_rows = _build_job_rows(args.job_urls or [])
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
