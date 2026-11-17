"""AnkiQuest's own pages: the add-on's AnkiWeb page, its repository, releases and bug reports."""

from enum import Enum

REPO = "AnkiQuest/AnkiQuest-Desktop"
REPOSITORY = "https://github.com/" + REPO
RELEASES = REPOSITORY + "/releases"
BUG_FORM = REPOSITORY + "/issues/new?template=bug_report_form.yml"
ANKIWEB = "https://ankiweb.net/shared/info/414948448"


class RateTarget(Enum):
    """Where "Rate AnkiQuest" sends the player, in menu order: AnkiWeb, where Anki users rate
    add-ons, and the repository, to star it for installs outside AnkiWeb."""

    ANKIWEB = ("Rate on AnkiWeb", ANKIWEB)
    GITHUB = ("Star on GitHub", REPOSITORY)

    @property
    def title(self):
        return self.value[0]

    @property
    def url(self):
        return self.value[1]
