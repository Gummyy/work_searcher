# Work Searcher

The software developed in this repository is used to enhance the job offering applications of the user.

## Features

The application processes job offerings matching user criteria and performs the following for each:

- **Candidate Rank**: Rankings how suitable the user is for the position based on their profile.
- **Offering Rank**: Rankings how suitable the job offering is for the user based on their preferences.
- **Document Selection**: Chooses the most relevant resume and cover letter category.
- **Customization**: Copies and renames the selected resume and cover letter (e.g., `resume_{company}_{position}.pdf`). It also modifies the cover letter to highlight soft skills demanded by the offering.
- **Summary Generation**: detailed Excel file containing ranks, explanations, and optional data like commute time, salary, and start date proximity.

## Configuration

The user provides a `config.json` file containing:

- A list of categorized resumes and cover letters.
- Job criteria (translating to API parameters).
- **User's Profile**: A detailed text description of every skill, education, and job experience.
- **User's Preferences**: A text file describing the user's dream job (industry, company size, remote work, etc.).

## Environment

This repository contains code developed in Python 3.13.7.

### Setup

To set up the environment:

1.  Activate the virtual environment (PowerShell):

    ```powershell
    .\work_searcher_env\Scripts\Activate.ps1
    ```

2.  Install dependencies:

    ```bash
    pip install -r requirements.txt
    ```

3.  Configure environment variables in `.env`. In order to support multiple file extensions and to be able convert these to markdown (for llm inferences) and pdf (the final versions to be sent to employers), it is necessary to install [pandoc](https://pandoc.org) and eventually [libreoffice](https://www.libreoffice.org) for some specific extensions. Once these are installed, `PANDOC_PATH` and `LIBREOFFICE_PATH` are set up as the paths to both executables.

4.  Install a PDF engine for pandoc. Pandoc requires a PDF engine to produce PDF files from markdown. Any [pandoc-supported engine](https://pandoc.org/MANUAL.html#option--pdf-engine) can be used. [Tectonic](https://tectonic-typesetting.github.io) is recommended: it is a single lightweight binary (~18 MB) that silently downloads only the packages it needs on first use, with no interactive prompts — making it well-suited for subprocess execution.

    Download the prebuilt Windows binary from the [Tectonic GitHub releases](https://github.com/tectonic-typesetting/tectonic/releases) (`x86_64-pc-windows-msvc` variant), place it somewhere on your `PATH`, then set `PANDOC_PDF_ENGINE=tectonic` in your `.env` file.

    If `PANDOC_PDF_ENGINE` is not set, pandoc falls back to its default engine (`pdflatex`), which requires a full TeX distribution (MiKTeX or TeX Live) to be installed.

## Tests

This repository uses `pytest`. Run tests with:

```bash
pytest
```
