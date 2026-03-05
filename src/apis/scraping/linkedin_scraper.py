from apis.scraping.base_scraper import BaseScraper


class LinkedinScraper(BaseScraper):
    """Scraper for LinkedIn job listing pages.

    Uses lxml XPath to extract the job description, title, and company name
    from the pre-loaded HTML tree.
    """

    def get_llm_parsed_description(self) -> str:
        """Extracts and returns an LLM-ready formatted job description string.

        Returns:
            str: Formatted job description for LLM consumption.
        """
        # TODO: refine XPath to match LinkedIn's description container
        fragments: list[str] = self._loaded_html_page.xpath("")
        return " ".join(fragments).strip()

    def get_job_title(self) -> str:
        """Extracts and returns the job title from the listing page.

        Returns:
            str: The job title text.
        """
        # TODO: refine XPath to match LinkedIn's job title element
        fragments: list[str] = self._loaded_html_page.xpath("")
        return " ".join(fragments).strip()

    def get_company(self) -> str:
        """Extracts and returns the company name from the listing page.

        Returns:
            str: The company name text.
        """
        # TODO: refine XPath to match LinkedIn's company name element
        fragments: list[str] = self._loaded_html_page.xpath("")
        return " ".join(fragments).strip()
