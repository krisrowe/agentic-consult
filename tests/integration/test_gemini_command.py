import os
import pytest
from pathlib import Path
from click.testing import CliRunner
from agentic_consult.cli.main import main

@pytest.mark.integration
def test_simple_prompt():
    """
    Test basic prompt with no context.
    """
    runner = CliRunner()
    result = runner.invoke(main, [
        'gemini', 
        'What is 4 + 5? Respond with ONLY the number.'
    ])
    
    assert result.exit_code == 0
    assert "9" in result.output.strip()

@pytest.mark.integration
def test_prompt_with_one_context_file():
    """
    Test prompt with a single file context.
    """
    runner = CliRunner()
    with runner.isolated_filesystem():
        # Create a secret file
        Path('secret.txt').write_text("The secret code is BLUE_ORION.")
        
        result = runner.invoke(main, [
            'gemini', 
            'What is the secret code? Respond with ONLY the code.',
            'secret.txt'
        ])
        
        assert result.exit_code == 0
        assert "BLUE_ORION" in result.output.strip()

@pytest.mark.integration
def test_prompt_with_multiple_files():
    """
    Test prompt reasoning across multiple files.
    """
    runner = CliRunner()
    with runner.isolated_filesystem():
        Path('a.txt').write_text("Value A is 10")
        Path('b.txt').write_text("Value B is 20")
        
        result = runner.invoke(main, [
            'gemini', 
            'What is Value A + Value B? Respond with ONLY the number.',
            'a.txt',
            'b.txt'
        ])
        
        assert result.exit_code == 0
        assert "30" in result.output.strip()

@pytest.mark.integration
def test_prompt_with_context_excluded():
    """
    Test directory walking with exclusion patterns.
    Structure:
      - root_file1.txt
      - root_file2.txt
      - sub/sub_keep.txt
      - sub/sub_exclude.log
    Excludes *.log.
    """
    runner = CliRunner()
    with runner.isolated_filesystem():
        Path('root_file1.txt').write_text("content")
        Path('root_file2.txt').write_text("content")
        
        sub = Path('sub')
        sub.mkdir()
        (sub / 'sub_keep.txt').write_text("content")
        (sub / 'sub_exclude.log').write_text("content")
        
        result = runner.invoke(main, [
            'gemini',
            'List the filenames (not paths, just names) found in the context, in alphabetical order, comma separated.',
            '.',
            '--exclude', '*.log'
        ])
        
        assert result.exit_code == 0
        out = result.output.strip()
        
        # Verify inclusions
        assert "root_file1.txt" in out
        assert "root_file2.txt" in out
        assert "sub_keep.txt" in out
        
        # Verify exclusion
        assert "sub_exclude.log" not in out

@pytest.mark.integration
def test_prompt_excludes_binaries():
    """
    Test that binary files are automatically excluded using the null-byte check.
    """
    runner = CliRunner()
    with runner.isolated_filesystem():
        Path('text.txt').write_text("I am a text file.")
        
        # Create a binary file with a null byte
        with open('binary.bin', 'wb') as f:
            f.write(b"Start \x00 End")
            
        result = runner.invoke(main, [
            'gemini',
            'List the filenames found in the context.',
            '.'
        ])
        
        assert result.exit_code == 0
        out = result.output.strip()
        
        assert "text.txt" in out
        assert "binary.bin" not in out
