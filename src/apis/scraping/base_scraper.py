from abc import ABC, abstractmethod

from lxml import html
from markdownify import markdownify
from playwright.sync_api import Browser, sync_playwright

from agents.types import ParsedJob


class BaseScraper(ABC):
    """Abstract base class for job page scrapers using a Playwright headless browser.

    The page is loaded once during initialisation and stored as a parsed lxml
    tree in _loaded_html_page, which all extraction methods share.

    Attributes:
        _url (str): The job listing URL passed at construction time.
        _browser (Browser): The Playwright browser instance.
        _loaded_html_page (lxml.html.HtmlElement): Parsed HTML tree of the job page.
    """

    _HEADERS: dict[str, str] = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
    }

    def __init__(self, url: str) -> None:
        self._url = url
        self._playwright = sync_playwright().start()
        self._browser: Browser = self._playwright.chromium.launch(headless=True)
        page = self._browser.new_page(extra_http_headers=self._HEADERS)
        page.goto(url)
        page.wait_for_load_state("networkidle")
        self._loaded_html_page = html.fromstring(page.content())
        page.close()

    @abstractmethod
    def get_llm_parsed_description(self) -> str:
        """Extracts and returns an LLM-ready formatted job description string.

        Returns:
            str: Formatted job description for LLM consumption.
        """

    @abstractmethod
    def get_job_title(self) -> str:
        """Extracts and returns the job title from the listing page.

        Returns:
            str: The job title text.
        """

    @abstractmethod
    def get_company(self) -> str:
        """Extracts and returns the company name from the listing page.

        Returns:
            str: The company name text.
        """

    @staticmethod
    def _html_to_markdown(element: html.HtmlElement) -> str:
        """Converts an lxml HTML element to a Markdown string.

        Args:
            element (html.HtmlElement): The HTML element to convert.

        Returns:
            str: The element content rendered as GitHub-Flavoured Markdown.
        """
        return markdownify(html.tostring(element, encoding="unicode"))

    def scrape(self) -> ParsedJob:
        """Scrapes all relevant fields and returns a ParsedJob.

        Returns:
            ParsedJob: The fully populated job record for this listing.
        """
        return ParsedJob(
            company=self.get_company(),
            job_title=self.get_job_title(),
            job_description=self.get_llm_parsed_description(),
            job_url=self._url,
        )

    def close(self) -> None:
        """Closes the browser and stops the Playwright instance."""
        self._browser.close()
        self._playwright.stop()

    def __enter__(self) -> "BaseScraper":
        return self

    def __exit__(self, *_) -> None:
        self.close()
