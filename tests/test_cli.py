from pathlib import Path

from agentaudit import cli

SAMPLE = Path(__file__).resolve().parent.parent / "data" / "sample"


def test_grade_refuses_to_spend_without_confirmation(tmp_path, capsys, monkeypatch):
    def explode(*args, **kwargs):
        raise AssertionError("the API client must not be created")

    monkeypatch.setattr(cli, "Grader", explode)
    code = cli.main(["grade", "--kb", str(SAMPLE / "help_center"), "--conversations", str(SAMPLE / "conversations.jsonl"),
                     "--out", str(tmp_path / "grades.jsonl")])
    captured = capsys.readouterr()
    assert code == 1
    assert "Estimated cost" in captured.out and "--yes" in captured.err
    assert not (tmp_path / "grades.jsonl").exists()


def test_estimate_runs_offline(capsys):
    assert cli.main(["estimate", "--kb", str(SAMPLE / "help_center"), "--conversations", str(SAMPLE / "conversations.jsonl")]) == 0
    assert "Nothing was sent to the API" in capsys.readouterr().out


def test_pull_zendesk_requires_token_from_environment(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("ZENDESK_API_TOKEN", raising=False)
    code = cli.main(["pull-zendesk", "--out", str(tmp_path), "--subdomain", "acme", "--email", "a@b.c", "--ai-author-id", "1"])
    assert code == 1 and "ZENDESK_API_TOKEN" in capsys.readouterr().err
