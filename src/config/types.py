from typing import Optional, Union

from jobspy import DescriptionFormat, JobType, Site, Country
from pydantic import BaseModel, Field, field_validator, model_validator

from files.File import read_file_content, validate_file

_VALID_SITE_NAMES: frozenset[str] = frozenset(s.value for s in Site)
_VALID_JOB_TYPES: frozenset[str] = frozenset(jt.value[0] for jt in JobType)
_VALID_DESCRIPTION_FORMATS: frozenset[str] = frozenset(
    d.value for d in DescriptionFormat
)


class FileOrContent(BaseModel):
    """A model that holds either a file path or a raw string value.

    At least one of the fields must be provided. If only 'file' is given,
    'content' is automatically populated from the file's text.

    Attributes:
        file (str, optional): Path to a readable file. Defaults to None.
        content (str, optional): Raw string content. Defaults to None.
    """

    file: Optional[str] = Field(default=None)
    content: Optional[str] = Field(default=None)

    @field_validator("file")
    @classmethod
    def validate_file_exists_and_readable(cls, v: Optional[str]) -> Optional[str]:
        """Validates that the file path points to an existing, readable file.

        Args:
            v (str, optional): The file path to validate.

        Raises:
            ValueError: If the path does not exist, is not a file, or is not readable.

        Returns:
            str | None: The validated file path, or None if not provided.
        """
        if v is None:
            return v
        validate_file(v)
        return v

    @model_validator(mode="after")
    def populate_and_validate_content(self) -> "FileOrContent":
        """Ensures content is populated and non-empty.

        If only 'file' is provided, reads the file and populates 'content'.
        Raises an error if neither field is set or if content ends up empty.

        Raises:
            ValueError: If both fields are None, or if content is empty.

        Returns:
            FileOrContent: The validated model instance.
        """
        if self.file is None and self.content is None:
            raise ValueError("At least one of 'file' or 'content' must be provided.")
        if self.content is None:
            self.content = read_file_content(self.file)
        if not self.content.strip():
            raise ValueError("'content' must not be empty.")
        return self


class DocumentCategory(BaseModel):
    """Lightweight descriptor for a document category passed to the LLM.

    Attributes:
        category (str): Short label identifying the job domain.
        description (str): Human-readable description of the job domain.
    """

    category: str
    description: str


class Document(BaseModel):
    """A categorized document bundle pairing a resume and cover letter for a job domain.

    Attributes:
        category (str): Short label identifying the job domain (e.g. "data", "AI").
        description (str): Human-readable description of the job domain.
        resume (FileOrContent): Resume document for this category.
        cover_letter (FileOrContent): Cover letter document for this category.
    """

    category: str
    description: str
    resume: FileOrContent
    cover_letter: FileOrContent


class JobspyArgs(BaseModel):
    """Arguments forwarded to jobspy's scrape_jobs function.

    Fields that accept a list (site_name, search_terms, location, job_type) also
    accept a plain string, which is normalized to a single-element list.
    search_terms, location, and job_type are iterated as a cartesian product when
    calling scrape_jobs, since that function expects a single value for each.

    Attributes:
        site_name (list[str]): Job boards to scrape. Valid values are the
            Site enum values (e.g. "linkedin", "indeed", "glassdoor").
        search_terms (list[str]): Job titles or keywords. One scrape_jobs call is
            made per (search_term, location, job_type) combination.
        location (list[str]): Locations to search in.
        hours_old (int, optional): Maximum age of job postings in hours. Defaults to None.
        distance (int, optional): Radius in miles around the location. Defaults to 50.
        is_remote (bool): Filter for remote jobs only. Defaults to False.
        job_type (list[str], optional): Job contract types to search for. Valid values
            are the first entry of each JobType enum tuple (e.g. "fulltime",
            "parttime", "contract", "internship"). Defaults to None.
        easy_apply (bool, optional): Filter for easy-apply jobs (LinkedIn only).
            Defaults to None.
        results_wanted (int): Maximum results per scrape_jobs call. Defaults to 15.
        country_indeed (str): Country code for Indeed/Glassdoor searches. Must be a
            valid country string recognized by jobspy's Country enum. Defaults to "usa".
        proxies (list[str], optional): Proxy URLs to use. Defaults to None.
        ca_cert (str, optional): Path to a CA certificate file. Defaults to None.
        description_format (str): Format for job descriptions. Valid values:
            "markdown", "html". Defaults to "markdown".
        linkedin_fetch_description (bool): Whether to fetch full descriptions from
            LinkedIn (slower). Defaults to False.
        linkedin_company_ids (list[int], optional): Filter by LinkedIn company IDs.
            Defaults to None.
        offset (int): Pagination offset for results. Defaults to 0.
        enforce_annual_salary (bool): Normalize all salaries to annual amounts.
            Defaults to False.
        verbose (int): Logging verbosity level (0, 1, or 2). Defaults to 0.
        user_agent (str, optional): Custom User-Agent header string. Defaults to None.
    """

    site_name: list[str]
    search_terms: list[str]
    location: list[str]
    hours_old: Optional[int] = None
    distance: Optional[int] = 50
    is_remote: bool = False
    job_type: Optional[list[str]] = None
    easy_apply: Optional[bool] = None
    results_wanted: int = Field(default=15, gt=0)
    country_indeed: str = "usa"
    proxies: Optional[list[str]] = None
    ca_cert: Optional[str] = None
    description_format: str = "markdown"
    linkedin_fetch_description: bool = False
    linkedin_company_ids: Optional[list[int]] = None
    offset: int = Field(default=0, ge=0)
    enforce_annual_salary: bool = False
    verbose: int = Field(default=0, ge=0, le=2)
    user_agent: Optional[str] = None

    @field_validator("site_name", "search_terms", "location", mode="before")
    @classmethod
    def normalize_to_list(cls, v: Union[str, list[str]]) -> list[str]:
        """Normalizes a string or list field to a list.

        Args:
            v (str | list[str]): A single string or a list of strings.

        Returns:
            list[str]: The value(s) as a list.
        """
        if isinstance(v, str):
            return [v]
        return v

    @field_validator("job_type", mode="before")
    @classmethod
    def normalize_job_type(cls, v: Union[str, list[str], None]) -> Optional[list[str]]:
        """Normalizes job_type to a list, accepting a string, list, or None.

        Args:
            v (str | list[str] | None): A single job type string, a list, or None.

        Returns:
            list[str] | None: The job type(s) as a list, or None.
        """
        if v is None:
            return None
        if isinstance(v, str):
            return [v]
        return v

    @field_validator("site_name")
    @classmethod
    def validate_site_names(cls, v: list[str]) -> list[str]:
        """Validates that all site names are recognized by jobspy.

        Args:
            v (list[str]): List of site name strings.

        Raises:
            ValueError: If any site name is not a valid Site enum value.

        Returns:
            list[str]: The validated site names.
        """
        for name in v:
            if name not in _VALID_SITE_NAMES:
                raise ValueError(
                    f"Invalid site_name '{name}'. Valid values: {sorted(_VALID_SITE_NAMES)}"
                )
        return v

    @field_validator("job_type")
    @classmethod
    def validate_job_types(cls, v: Optional[list[str]]) -> Optional[list[str]]:
        """Validates that all job type strings are recognized by jobspy.

        Args:
            v (list[str] | None): List of job type strings, or None.

        Raises:
            ValueError: If any job type is not a valid canonical JobType value.

        Returns:
            list[str] | None: The validated job types, or None.
        """
        if v is None:
            return None
        for jt in v:
            if jt not in _VALID_JOB_TYPES:
                raise ValueError(
                    f"Invalid job_type '{jt}'. Valid values: {sorted(_VALID_JOB_TYPES)}"
                )
        return v

    @field_validator("country_indeed")
    @classmethod
    def validate_country(cls, v: str) -> str:
        """Validates that country_indeed is a country string recognized by jobspy.

        Args:
            v (str): The country string to validate.

        Raises:
            ValueError: If the string does not match any Country enum entry.

        Returns:
            str: The original country string.
        """
        Country.from_string(v)
        return v

    @field_validator("description_format")
    @classmethod
    def validate_description_format(cls, v: str) -> str:
        """Validates that description_format is a recognized format string.

        Args:
            v (str): The format string to validate.

        Raises:
            ValueError: If the string is not a valid DescriptionFormat value.

        Returns:
            str: The validated format string.
        """
        if v not in _VALID_DESCRIPTION_FORMATS:
            raise ValueError(
                f"Invalid description_format '{v}'. Valid values: {sorted(_VALID_DESCRIPTION_FORMATS)}"
            )
        return v


class APICalls(BaseModel):
    """A configured API call descriptor pairing a tool name with its arguments.

    Attributes:
        tool (str): Identifier of the tool to use (e.g. "jobspy").
        args (JobspyArgs): Arguments to pass to the tool.
    """

    tool: str
    args: JobspyArgs


class Config(BaseModel):
    """Top-level application configuration.

    Attributes:
        profile (FileOrContent): User profile document.
        preferences (FileOrContent): User job preferences document.
        documents (list[Document]): Resume/cover letter bundles per job category.
        api_calls (list[APICalls], optional): Configured API call descriptors.
            May be omitted when a job offering is supplied via --job. Defaults to None.
    """

    profile: FileOrContent
    preferences: FileOrContent
    documents: list[Document]
    api_calls: Optional[list[APICalls]] = None
