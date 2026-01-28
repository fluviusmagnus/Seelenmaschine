#!/usr/bin/env python3
"""Test script to verify cache optimization implementation."""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from config import Config
from prompts.system import get_cacheable_system_prompt, get_current_time_str

# Initialize config with a test profile (or use default)
Config.init("default")

def test_get_current_time_str():
    """Test the get_current_time_str function."""
    print("Testing get_current_time_str()...")
    time_str = get_current_time_str()
    print(f"✓ Current time: {time_str}")
    assert isinstance(time_str, str)
    assert len(time_str) > 0
    print()

def test_get_cacheable_system_prompt_without_summaries():
    """Test get_cacheable_system_prompt without recent summaries."""
    print("Testing get_cacheable_system_prompt() without recent summaries...")
    prompt = get_cacheable_system_prompt()
    print(f"✓ Prompt generated, length: {len(prompt)} chars")
    
    # Check for key sections
    assert "## Core Instructions" in prompt
    assert "## Your Identity and Personality" in prompt
    assert "## User Profile" in prompt
    print("✓ All required sections present")
    print()

def test_get_cacheable_system_prompt_with_summaries():
    """Test get_cacheable_system_prompt with recent summaries."""
    print("Testing get_cacheable_system_prompt() with recent summaries...")
    
    test_summaries = [
        "User asked about Python programming. Bot provided helpful examples.",
        "Discussion about machine learning concepts and applications.",
        "User shared personal project ideas, bot offered encouragement."
    ]
    
    prompt = get_cacheable_system_prompt(test_summaries)
    print(f"✓ Prompt generated with summaries, length: {len(prompt)} chars")
    
    # Check that summaries are included
    assert "## Recent Conversation Summaries" in prompt
    assert "Summary 1:" in prompt
    assert "Summary 2:" in prompt
    assert "Summary 3:" in prompt
    assert test_summaries[0] in prompt
    print("✓ Recent summaries included correctly")
    print()

def test_message_structure():
    """Test the overall message structure."""
    print("Testing message structure...")
    
    # Simulate what _build_chat_messages would create
    from llm.client import LLMClient
    
    client = LLMClient()
    
    current_context = [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi there!"},
        {"role": "user", "content": "How are you?"}
    ]
    
    retrieved_summaries = ["Summary from last week"]
    retrieved_conversations = ["Past conversation excerpt"]
    recent_summaries = ["Recent summary 1", "Recent summary 2"]
    
    messages = client._build_chat_messages(
        current_context=current_context,
        retrieved_summaries=retrieved_summaries,
        retrieved_conversations=retrieved_conversations,
        recent_summaries=recent_summaries
    )
    
    print(f"✓ Built {len(messages)} messages")
    
    # Verify structure
    assert messages[0]["role"] == "system", "First message should be system"
    assert "## Your Identity and Personality" in messages[0]["content"], "Should contain identity"
    assert "## Recent Conversation Summaries" in messages[0]["content"], "Should contain recent summaries"
    
    # Find the emphasized user message at the end
    last_message = messages[-1]
    assert last_message["role"] == "user", "Last message should be user"
    assert "⚡ [Current Request]" in last_message["content"], "Should have emphasis"
    assert "How are you?" in last_message["content"], "Should contain original message"
    
    print("✓ Message structure is correct:")
    print(f"  - System prompt (cacheable): {len(messages[0]['content'])} chars")
    print(f"  - History messages: {len([m for m in messages if m['role'] in ['user', 'assistant']]) - 1}")
    print(f"  - Retrieved summaries: {len(retrieved_summaries)}")
    print(f"  - Retrieved conversations: {len(retrieved_conversations)}")
    print(f"  - Current time message: present")
    print(f"  - Emphasized user input: present")
    print()

def main():
    """Run all tests."""
    print("=" * 60)
    print("Cache Optimization Implementation Tests")
    print("=" * 60)
    print()
    
    try:
        test_get_current_time_str()
        test_get_cacheable_system_prompt_without_summaries()
        test_get_cacheable_system_prompt_with_summaries()
        test_message_structure()
        
        print("=" * 60)
        print("✓ All tests passed!")
        print("=" * 60)
        return 0
        
    except Exception as e:
        print(f"\n✗ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    sys.exit(main())
