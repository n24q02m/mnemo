import json

from mnemo_mcp.server import recall_context, save_summary


def test_recall_context_empty_topic():
    result = recall_context("")
    data = json.loads(result)
    assert "error" in data
    assert "suggestion" in data
    assert "Topic cannot be empty" in data["error"]


def test_recall_context_whitespace_topic():
    result = recall_context("   ")
    data = json.loads(result)
    assert "error" in data
    assert "suggestion" in data
    assert "Topic cannot be empty" in data["error"]


def test_save_summary_empty_summary():
    result = save_summary("")
    data = json.loads(result)
    assert "error" in data
    assert "suggestion" in data
    assert "Summary cannot be empty" in data["error"]


def test_save_summary_whitespace_summary():
    result = save_summary("   ")
    data = json.loads(result)
    assert "error" in data
    assert "suggestion" in data
    assert "Summary cannot be empty" in data["error"]
