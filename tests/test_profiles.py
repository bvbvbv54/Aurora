from aurora.cli import parser, runner_options
from aurora.core.decision_engine import OPPORTUNITY_WEIGHTS


def test_profiles_change_exploration_not_scoring():
    root = parser()
    quick = runner_options(root.parse_args(["research", "--profile", "quick"]))
    deep = runner_options(root.parse_args(["research", "--profile", "deep"]))
    assert quick.max_keywords == 5
    assert quick.validation_depth == 1
    assert deep.max_keywords == 100
    assert deep.validation_depth == 6
    assert deep.max_depth == 6
    assert deep.max_suggestions == 14
    assert sum(OPPORTUNITY_WEIGHTS.values()) == 1


def test_custom_profile_overrides_each_exploration_parameter():
    args = parser().parse_args(
        [
            "research",
            "--profile",
            "custom",
            "--max-keywords",
            "7",
            "--max-depth",
            "2",
            "--max-suggestions",
            "4",
            "--search-breadth",
            "3",
            "--validation-depth",
            "2",
        ]
    )
    options = runner_options(args)
    assert (
        options.max_keywords,
        options.max_depth,
        options.max_suggestions,
        options.search_breadth,
        options.validation_depth,
    ) == (7, 2, 4, 3, 2)
