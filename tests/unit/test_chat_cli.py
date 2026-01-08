import pytest
from unittest.mock import patch, MagicMock
from click.testing import CliRunner
from agentic_consult.cli.main import main

@pytest.fixture
def runner():
    return CliRunner()

@pytest.fixture
def mock_get_chat_mentions():
    with patch('agentic_consult.cli.chat.get_chat_mentions') as mock:
        yield mock

def test_chat_mentions_list_default(runner, mock_get_chat_mentions):
    """Test listing mentions with default arguments."""
    mock_get_chat_mentions.return_value = {
        "mentions": [
            {"sender": "User A", "text": "Hello world", "space": "Space X"}
        ],
        "scanned_spaces": 10
    }
    
    result = runner.invoke(main, ['chat', 'mentions', 'list'])
    
    assert result.exit_code == 0
    assert "Found 1 mentions" in result.output
    assert "[Space X] User A: Hello world" in result.output
    # Default limit should be passed as None to let SDK/Config handle it
    mock_get_chat_mentions.assert_called_with(limit=None, unanswered_only=True)

def test_chat_mentions_list_with_limit(runner, mock_get_chat_mentions):
    """Test listing mentions with explicit limit."""
    mock_get_chat_mentions.return_value = {"mentions": []}
    
    result = runner.invoke(main, ['chat', 'mentions', 'list', '--limit', '5'])
    
    assert result.exit_code == 0
    mock_get_chat_mentions.assert_called_with(limit=5, unanswered_only=True)

def test_chat_mentions_list_all(runner, mock_get_chat_mentions):
    """Test listing all mentions (including answered)."""
    mock_get_chat_mentions.return_value = {"mentions": []}
    
    result = runner.invoke(main, ['chat', 'mentions', 'list', '--all'])
    
    assert result.exit_code == 0
    mock_get_chat_mentions.assert_called_with(limit=None, unanswered_only=False)

def test_chat_mentions_error_handling(runner, mock_get_chat_mentions):
    """Test error handling during fetch."""
    mock_get_chat_mentions.side_effect = Exception("API Error")
    
    result = runner.invoke(main, ['chat', 'mentions', 'list'])
    
    assert result.exit_code == 1
    assert "Error: API Error" in result.output
