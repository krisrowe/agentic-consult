"""Tests for email analyzer module entry point (__main__.py).

Verifies that `python -m agentic_consult.email` correctly invokes the SDK.
"""
import pytest
from unittest.mock import patch, MagicMock


def test_invokes_process_queue():
    """Proof: Module entry point invokes EmailAnalyzer.process_queue with correct args."""
    from agentic_consult.email.__main__ import main

    mock_analyzer_instance = MagicMock()
    mock_analyzer_instance.process_queue.return_value = {"processed": 0, "status": "idle"}

    with patch('agentic_consult.email.__main__.EmailStore') as mock_store_cls, \
         patch('agentic_consult.email.__main__.EmailAnalyzer') as mock_analyzer_cls, \
         patch('agentic_consult.email.__main__.GeminiProvider') as mock_provider_cls, \
         patch.dict('os.environ', {}, clear=False):

        mock_analyzer_cls.return_value = mock_analyzer_instance

        main()

        # Verify EmailAnalyzer was instantiated with store and provider
        mock_analyzer_cls.assert_called_once()
        call_kwargs = mock_analyzer_cls.call_args[1]
        assert 'store' in call_kwargs or mock_analyzer_cls.call_args[0]
        assert 'provider' in call_kwargs or len(mock_analyzer_cls.call_args[0]) >= 2

        # Verify process_queue was called (with None defaults when no env vars)
        mock_analyzer_instance.process_queue.assert_called_once_with(
            lookback_days=None,
            limit=None
        )


def test_invokes_process_queue_with_env_overrides():
    """Proof: Module entry point passes env var overrides to process_queue."""
    from agentic_consult.email.__main__ import main

    mock_analyzer_instance = MagicMock()
    mock_analyzer_instance.process_queue.return_value = {"processed": 5, "status": "completed"}

    env_overrides = {
        'ANALYZER_LIMIT': '25',
        'ANALYZER_LOOKBACK_DAYS': '7',
        'ANALYZER_MODEL': 'gemini-2.0-flash'
    }

    with patch('agentic_consult.email.__main__.EmailStore') as mock_store_cls, \
         patch('agentic_consult.email.__main__.EmailAnalyzer') as mock_analyzer_cls, \
         patch('agentic_consult.email.__main__.GeminiProvider') as mock_provider_cls, \
         patch.dict('os.environ', env_overrides, clear=False):

        mock_analyzer_cls.return_value = mock_analyzer_instance

        main()

        # Verify GeminiProvider was called with model override
        mock_provider_cls.assert_called_once_with(model='gemini-2.0-flash')

        # Verify process_queue was called with parsed env values
        mock_analyzer_instance.process_queue.assert_called_once_with(
            lookback_days=7,
            limit=25
        )
