# Project

Django project with SQLite database for collecting band performance data from live house websites.

## Stack

- **uv** - Package management (`uv add`, `uv run`)
- **poethepoet** - Task runner (`uv run poe <task>`)
- **pre-commit** - Git hooks
- **ruff** - Linting/formatting
- **Django test runner** - Testing (NOT pytest — `uv run poe test` runs `cd malcom && uv run python manage.py test --debug-mode`)

## Development Commands

All commands must be run from the **`malcom/`** subdirectory (where `manage.py` lives), or via `poe` tasks from the repo root.

```bash
# Run tests (from repo root)
uv run poe test

# Run a management command (from repo root)
cd malcom && uv run python manage.py <command>

# Lint/format (from repo root)
uv run ruff check malcom/
uv run ruff format malcom/
```

## Git Workflow

All source files live under `malcom/` — always include the prefix when staging:
```bash
git add malcom/commons/youtube_utils.py malcom/houses/management/commands/foo.py
```

`ellen-goc` does **not** have push access to `monkut/hakoake-backend`. Use the `fork` remote to push branches and open PRs:
```bash
git push fork <branch-name>
gh pr create --repo monkut/hakoake-backend --head "ellen-goc:<branch-name>" --base main ...
```

## Testing Conventions

This project uses `ruff` with `select = ["ALL"]`. Tests must follow these rules to pass pre-commit hooks:

- **Mock parameters require type annotations** (ANN001): always annotate mock args as `MagicMock`
  ```python
  def test_foo(self, mock_upload: MagicMock, mock_get_client: MagicMock) -> None:
  ```
- **Hardcoded `/tmp/` paths** trigger S108 — suppress with `# noqa: S108`, or use `tempfile.NamedTemporaryFile`
- **Methods with >6 `return` statements** trigger PLR0911 — suppress with `# noqa: PLR0911` on the `def` line

## Django Shell Output

`manage.py shell -c "..."` prints a startup line before the value (e.g. `19 objects imported automatically`). Prefer dedicated management commands with `--json` output over `shell -c` hacks. Parse JSON output with `jq` (`jq` is installed):
```bash
value=$(uv run python manage.py my_command --json | jq -r '.field')
```

## Crawler Development

Create crawlers in `houses/crawlers/` extending `houses.crawlers.LiveHouseWebsiteCrawler`.

**Playwright** (`fetch_page_js()`): Use for JS-rendered content or "Load More" buttons.
**Standard** (`fetch_page()`): Use for static HTML pages.

## Management Commands

All commands must be run from the `malcom/` directory: `cd malcom && uv run python manage.py <command>`

### Data Collection Workflow

| Command | Purpose | Key Options |
|---------|---------|-------------|
| `current_status` | Show venue collection status, schedule counts | - |
| `list-livehouses` | List all venues with IDs and status | - |
| `collect_schedules` | Scrape performance data from venues | `--venue-id <id>` |
| `reset_collection` | Delete schedules and allow re-collection | `--venue-id <id> --target-date YYYY-MM-DD` (both required) |
| `addwebsite` | Register new venue URL | `<url>` (positional) |
| `clear-livehouses` | Clear last collection data for specified venues | `<livehouse_ids>` (positional, multiple), `--dry-run` |

**Collection notes:**
- `collect_schedules` skips venues already collected today; use `reset_collection` first to force re-collection
- `reset_collection` requires confirmation; deletes schedules from target date onwards

### Playlist Generation

| Command | Purpose | Key Options |
|---------|---------|-------------|
| `create_weekly_playlist` | Create YouTube playlist for week | `<target_week>` (YYYY-MM-DD Monday), `--top-n`, `--dry-run` |
| `create_monthly_playlist` | Create YouTube playlist for month | `<target_month>` (YYYY-MM), `--top-n`, `--dry-run` |
| `list_weekly_playlist` | Show weekly playlist entries | `<target_week>` |
| `list_monthly_playlist` | Show monthly playlist entries | `<target_month>` |
| `list_weeklyplaylist_performers` | List performers eligible for weekly playlist | `<target_week>` |
| `list_monthlyplaylist_performers` | List performers eligible for monthly playlist | `<target_month>` |
| `add_weeklyplaylist_spotlight` | Add performer to weekly spotlight | `--playlist-id`, `--performer-id` |
| `add_monthlyplaylist_spotlight` | Add performer to monthly spotlight | `--playlist-id`, `--performer-id` |
| `list_monthly_performers` | List all performers scheduled for a month | `--month` (YYYY-MM), `--upcoming-only` |
| `fix_playlist_positions` | Fix playlist entry positions to be sequential | `--playlist-id`, `--dry-run` |

### Video Generation

| Command | Purpose | Key Options |
|---------|---------|-------------|
| `generate_weekly_playlist_introduction` | Generate AI narration for weekly video | `<playlist_id>`, `--audio`, `--voice` |
| `generate_weekly_playlist_video` | Create weekly playlist video (auto-generates narration) | `<playlist_id>`, `--intro-text-file` |
| `create_weekly_playlist_intro_video` | Create intro video for weekly playlist | `<playlist_id>`, `--output`, `--duration` |
| `generate_playlist_introduction` | Generate AI narration for monthly video | `<target_month>` |
| `generate_playlist_video` | Create monthly playlist video | `<target_month>` |
| `create_monthly_playlist_intro_video` | Create intro video for monthly playlist | `<target_month>` |
| `generate_tts_samples` | Generate TTS audio samples with different tunings | `--count`, `--text`, `--output-dir`, `--voice` |

**Weekly video workflow:**
1. `create_weekly_playlist <target_week>` - Creates YouTube playlist and `WeeklyPlaylist` record (returns playlist ID)
2. `generate_weekly_playlist_video <playlist_id>` - Creates video with auto-generated narration

### Performer Data

| Command | Purpose | Key Options |
|---------|---------|-------------|
| `fetch_performer_images` | Fetch artist images from TheAudioDB | `--performer-id`, `--performer-name`, `--missing-only`, `--force` |
| `search_youtube_songs` | Search YouTube for performer songs | `--performer-id`, `--performer-name` |
| `clean_band_prefix` | Remove "BAND:" prefix from performer names | - |
| `clean_trailing_chars` | Remove trailing slashes/backslashes from data | - |
| `performersociallink_list` | List all PerformerSocialLink entries | - |
| `performersociallink_fix` | Update a PerformerSocialLink URL | `--performer-id`, `--platform`, `<url>` |
| `performersociallink_verify` | Mark a PerformerSocialLink as verified | `--performer-id`, `--platform` |
| `backfill_youtube_sociallinks` | Backfill PerformerSocialLink from existing YouTube song data | `--secrets-file`, `--dry-run`, `--limit` |

**Playlist creation notes:**
- `create_weekly_playlist` only includes performers with a verified YouTube PerformerSocialLink (`verified_datetime` must be set)
- Use `performersociallink_verify` to mark YouTube links as verified after manual review

### Dev Utilities

| Command | Purpose | Key Options |
|---------|---------|-------------|
| `dump_model_info` | Output model/ER diagram info | `-a <apps>` (required), `-e` (ER diagram), `-o <dir>` |
| `get_test_names` | List test names for CI/filtering | `--exclude-tags`, `-o <file>` |

### Debug Commands

```bash
# Verbose logging for any command
DJANGO_LOG_LEVEL=DEBUG uv run python manage.py <command> --verbosity=2
```