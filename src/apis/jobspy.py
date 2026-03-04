import random
import time
from itertools import product

import pandas as pd
from jobspy import scrape_jobs

from config.types import APICalls

_DEFAULT_DELAY_SECONDS: float = 3.0
_DEFAULT_DELAY_STD: float = 1.0


def fetch_jobs(
    api_calls: APICalls,
    delay: float = _DEFAULT_DELAY_SECONDS,
    delay_std: float = _DEFAULT_DELAY_STD,
) -> pd.DataFrame:
    """Fetches job listings by calling jobspy for each combination of search parameters.

    jobspy expects single values for search_term, location, and job_type per call.
    This function iterates over the cartesian product of search_terms, locations, and
    job_types (if provided), consolidating all results into one DataFrame.
    A Gaussian-distributed delay is applied between consecutive calls to reduce the
    likelihood of triggering automation detection.

    Args:
        api_calls (APICalls): The API call descriptor holding jobspy arguments.
        delay (float): Mean sleep duration in seconds between scrape_jobs calls.
            Defaults to 3.0.
        delay_std (float): Standard deviation of the sleep duration. Defaults to 1.0.

    Returns:
        pd.DataFrame: Combined job listings from all calls, deduplicated on job_url.
    """
    args = api_calls.args
    results: list[pd.DataFrame] = []

    # Exclude iterated fields; they are injected per-combination below.
    base_kwargs = args.model_dump(
        exclude_unset=True, exclude={"search_terms", "location", "job_type"}
    )

    job_types = args.job_type if args.job_type is not None else [None]
    combinations = list(product(args.search_terms, args.location, job_types))

    for i, (search_term, location, job_type) in enumerate(combinations):
        call_kwargs = {**base_kwargs, "search_term": search_term, "location": location}
        if job_type is not None:
            call_kwargs["job_type"] = job_type
        results.append(scrape_jobs(**call_kwargs))
        if i < len(combinations) - 1:
            time.sleep(max(0.1, random.gauss(delay, delay_std)))

    return pd.concat(results, ignore_index=True).drop_duplicates(subset="job_url")
