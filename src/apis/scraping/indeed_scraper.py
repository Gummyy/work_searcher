from lxml import html

from apis.scraping.base_scraper import BaseScraper


class IndeedScraper(BaseScraper):
    """Scraper for Indeed job listing pages.

    Uses lxml XPath to extract the job description from the rendered HTML.
    """

    def get_llm_parsed_description(self, url: str) -> str:
        """Scrapes an Indeed job listing page and returns an LLM-ready formatted string.

        Args:
            url (str): The Indeed job listing URL to scrape.

        Returns:
            str: Formatted job description for LLM consumption.
        """
        page = self._get_page(url)
        tree = html.fromstring(page.content())
        page.close()

        # TODO: refine XPath to match Indeed's description container
        fragments: list[str] = tree.xpath("")
        return " ".join(fragments).strip()
