from abc import ABC, abstractmethod

from playwright.sync_api import Browser, Page, sync_playwright


class BaseScraper(ABC):
    """Abstract base class for job page scrapers using a Playwright headless browser.

    Subclasses must implement get_description() to extract the job description
    from the rendered page using site-specific XPath selectors.

    Attributes:
        _browser (Browser): The Playwright browser instance.
        _headers (dict[str, str]): HTTP headers injected into every page request.
    """

    _HEADERS: dict[str, str] = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
    }

    def __init__(self) -> None:
        self._playwright = sync_playwright().start()
        self._browser: Browser = self._playwright.chromium.launch(headless=True)

    def _get_page(self, url: str) -> Page:
        """Opens a new browser page, sets headers, navigates to the URL and waits for load.

        Args:
            url (str): The job listing URL to load.

        Returns:
            Page: The fully loaded Playwright page instance.
        """
        page = self._browser.new_page(extra_http_headers=self._HEADERS)
        page.goto(url)
        page.wait_for_load_state("networkidle")
        return page

    @abstractmethod
    def get_llm_parsed_description(self, url: str) -> str:
        """Scrapes a job listing page and returns an LLM-ready formatted string.

        Implementations must extract at minimum the job description text.
        Additional fields (title, company, location, etc.) may be included
        when discoverable from the page.

        Args:
            url (str): The job listing URL to scrape.

        Returns:
            str: Formatted job description for LLM consumption.
        """

    def close(self) -> None:
        """Closes the browser and stops the Playwright instance."""
        self._browser.close()
        self._playwright.stop()

    def __enter__(self) -> "BaseScraper":
        return self

    def __exit__(self, *_) -> None:
        self.close()
