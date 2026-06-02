# malcom README

Management tool for live house performances


## Local Development

Python: 3.13

> Requires [uv](https://docs.astral.sh/uv/guides/install-python/) for dependency management


### Install the local development environment

1. Setup `pre-commit` hooks (_ruff_):

    ```bash
    # assumes pre-commit is installed on system via: `pip install pre-commit`
    pre-commit install
    ```

2. The following command installs project and development dependencies:

    ```bash
    uv sync
    ```

3. Install Playwright browsers (required for JavaScript-enabled web scraping):

    ```bash
    uv run playwright install
    ```

### Required AI Models Setup

This project uses [Ollama](https://ollama.com/) for AI-powered features. Install Ollama first, then pull the required models:

#### 1. Install Ollama

Follow the installation instructions at [ollama.com](https://ollama.com/)

#### 2. Pull Required Models

**Text Generation Model** (for playlist introductions):
```bash
ollama pull mistral-small
```

**TTS Model** (for voice generation):
```bash
ollama pull legraphista/Orpheus:3b-ft-q4_k_m
```

#### Model Configuration

Models are configured in `malcom/settings.py`:
- `PLAYLIST_INTRO_TEXT_GENERATION_MODEL`: Text generation model (default: `mistral-small`)
- `VIDEO_TTS_MODEL`: TTS model (default: `legraphista/Orpheus:3b-ft-q4_k_m`)
- `VIDEO_TTS_VOICE`: Orpheus voice selection (options: tara, leah, jess, leo, dan, mia, zac, zoe, ceylia)

#### Voice Generation

The project uses two TTS systems:

1. **Ollama Orpheus** (token generation): Requires the model above
2. **Microsoft Edge TTS** (audio synthesis): No installation needed, uses edge-tts library

Robotic voice effects are applied using pydub with configurable static levels.

### Add new packages

From the project root directory run the following:
```
uv add {PACKAGE TO INSTALL}
```

 ## Run code checks

 To run linters:
 ```
 # runs flake8, pydocstyle
 uv run poe check
 ```

To run type checker:
```
uv run pyright
```

## Running tests

This project uses the standard django testsuite for running testcases.

Tests cases are written and placed in the `tests` directory of *each* app.

To run the tests use the following command:
```
python manage.py test
```

> Alternatively, from the parent directory you can run:

```
uv run poe test
```

## CI/CD Required Environment Variables

The following are required for this project to be integrated with auto-deploy using the `github flow` branching strategy.

> With `github flow` master is the *release* branch and features are added through Pull-Requests (PRs)
> On merge to master the code will be deployed to the production environment.

[[LIST REQUIRED ENVIRONMENT VARIABLES HERE]]
