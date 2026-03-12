import random
import time
from abc import ABC, abstractmethod
from itertools import product

import pandas as pd
from jobspy import scrape_jobs


class BaseFetcher(ABC):
    """Abstract base class for job fetchers."""

    @abstractmethod
    def fetch_jobs(self) -> pd.DataFrame:
        """Fetch job listings and return a DataFrame."""
        pass


class JobspyFetcher(BaseFetcher):
    def __init__(self, args, delay: float = 3.0, delay_std: float = 1.0):
        self.args = args
        self.delay = delay
        self.delay_std = delay_std

    def fetch_jobs(self) -> pd.DataFrame:
        base_kwargs = self.args.model_dump(
            exclude_unset=True, exclude={"search_terms", "location", "job_type"}
        )
        job_types = self.args.job_type if self.args.job_type is not None else [None]
        combinations = list(
            product(self.args.search_terms, self.args.location, job_types)
        )
        results: list[pd.DataFrame] = []
        for i, (search_term, location, job_type) in enumerate(combinations):
            call_kwargs = {
                **base_kwargs,
                "search_term": search_term,
                "location": location,
            }
            if job_type is not None:
                call_kwargs["job_type"] = job_type
            results.append(scrape_jobs(**call_kwargs))
            if i < len(combinations) - 1:
                time.sleep(max(0.1, random.gauss(self.delay, self.delay_std)))
        return pd.concat(results, ignore_index=True).drop_duplicates(subset="job_url")
