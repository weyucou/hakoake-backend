from commons.definitions import StringEnumWithChoices

# Constants for crawler validation and limits
MIN_LIVEHOUSE_CAPACITY = 50
MAX_LIVEHOUSE_CAPACITY = 350
MIN_TICKET_PRICE = 500
MAX_TICKET_PRICE = 20000
YEAR_LOOKBACK = 1
YEAR_LOOKAHEAD = 1
MONTHS_PER_YEAR = 12
MAX_DAYS_PER_MONTH = 31
MAX_SCHEDULES_PER_FETCH = 20
MAX_PERFORMERS_TO_DISPLAY = 5
MIN_PERFORMER_NAME_LENGTH = 2
MIN_SLASH_PARTS = 2
HTTP_SUCCESS = 200
MAX_SOCIAL_LINKS = 5
MAX_CONTEXT_CHARS = 200
MAX_PERFORMERS_IN_CONTEXT = 3

PLAYLIST_TAGS = (
    "indies",
    "indierock",
    "punk",
    "punkrock",
    "garagerock",
    "インディーズ",
    "インディーズバンド",
    "underground",
    "alternative",
    "alternativerock",
    "emorock",
    "jrock",
)


class WebsiteProcessingState(StringEnumWithChoices):
    """Enum representing the state of website processing."""

    NOT_STARTED = "not_started"  # noqa: N806
    IN_PROGRESS = "in_progress"  # noqa: N806
    COMPLETED = "completed"  # noqa: N806
    FAILED = "failed"  # noqa: N806


class CrawlerCollectionState(StringEnumWithChoices):
    """Enum representing the state of crawler collection for a live house."""

    PENDING = "pending"  # noqa: N806
    SUCCESS = "success"  # noqa: N806
    ERROR = "error"  # noqa: N806
    TIMEOUT = "timeout"  # noqa: N806
