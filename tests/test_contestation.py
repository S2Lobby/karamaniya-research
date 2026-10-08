from karamaniya import contestation


def test_vote_metrics_distinguish_unanimity_from_contested_vote():
    unanimous = contestation.vote_metrics({"id": "M1", "votes": {"A": "yes", "B": "yes", "C": "yes"}})
    split = contestation.vote_metrics({"id": "M2", "votes": {"A": "yes", "B": "yes", "C": "no", "D": "abstain"}})

    assert unanimous["yes_unanimous"] is True
    assert unanimous["contested"] is False
    assert split["yes_unanimous"] is False
    assert split["contested"] is True
    assert split["binary_dominant_share"] == 2 / 3
    assert split["polarization"] > 0


def test_stance_changes_are_not_called_when_delegate_stays_with_position():
    result = contestation.stance_changes(
        [{"id": "M1", "votes": {"A": "yes", "B": "no"}}],
        {"A": {"stances": {"M1": "support"}}, "B": {"stances": {"M1": "oppose"}}},
    )
    assert result["aligned"] == 2
    assert result["changed"] == 0
    assert result["binary_change_rate"] == 0


def test_stance_changes_capture_real_reversal_and_conditional_resolution():
    result = contestation.stance_changes(
        [{"id": "M1", "votes": {"A": "no", "B": "yes", "C": "yes"}}],
        {
            "A": {"stances": {"M1": "support"}},
            "B": {"stances": {"M1": "conditional"}},
            "C": {"stances": {"M1": "support"}},
        },
    )
    assert result["changed"] == 1
    assert result["conditional_resolutions"] == 1
    assert result["binary_change_rate"] == 1 / 2


def test_run_summary_works_for_legacy_records_without_vote_dynamics():
    months = [
        {"motions": [{"id": "M1", "votes": {"A": "yes", "B": "no"}}], "revisions": {
            "A": {"stances": {"M1": "support"}},
            "B": {"stances": {"M1": "oppose"}},
        }},
    ]
    result = contestation.run_summary(months)
    assert result["decided_motions"] == 1
    assert result["contested_count"] == 1
    assert result["unanimous_rate"] == 0
