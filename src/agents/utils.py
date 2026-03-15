from pathlib import Path
from urllib.parse import urlparse

from agents.types import JobRow, ParsedJob
from files.utils import read_file_content, validate_file

# Maps URL hostname substrings to the corresponding scraper key.
_URL_SITE_MAP: dict[str, str] = {
    "indeed.com": "indeed",
    "linkedin.com": "linkedin",
}


def build_parsed_jobs(job_paths: list[str]) -> list[ParsedJob]:
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
        try:
            validate_file(job_path_str)
        except ValueError as e:
            raise ValueError(f"Error with file '{job_path_str}': {e}") from e
        try:
            job_description = read_file_content(job_path_str)
        except Exception as e:
            raise ValueError(
                f"Failed to read content from '{job_path_str}': {e}"
            ) from e
        try:
            parsed_jobs.append(
                ParsedJob(
                    company=company,
                    job_title=job_title,
                    job_description=job_description,
                    job_url=job_path_str,
                )
            )
        except Exception as e:
            raise ValueError(
                f"Failed to create ParsedJob for '{job_path_str}': {e}"
            ) from e
    return parsed_jobs


def build_job_rows(job_urls: list[str]) -> list[JobRow]:
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
