import sys

from chat import ChatBot
from config import OPENAI_API_KEY


def print_welcome() -> None:
    """Print welcome message and instructions"""
    print("\n=== Seele Chat ===")
    print("A chatbot with memory and personality")
    print("\nCommands:")
    print("  /save    - Archive current session and start a new empty one")
    print("  /reset   - Clear current conversations and session data")
    print(
        "  /exit    - Save session and exit (preserves conversations for next startup)"
    )
    print("  /help    - Show this help message")
    print("\nPress Ctrl+C to exit without saving")
    print("=" * 20)


def print_session_info(bot: ChatBot) -> None:
    """Print current session information and conversation history"""
    print(f"\nSession ID: {bot.memory.session_id}")
    print(f"Started: {bot.memory.start_time.strftime('%Y-%m-%d %H:%M:%S')}")

    if bot.memory.current_conversations:
        print("\nRecent conversations:")
        for conv in bot.memory.current_conversations:
            role = "You" if conv["role"] == "user" else "Seele"
            print(f"{role}: {conv['content']}")
    print("\n" + "=" * 20)


def main() -> None:
    """Main entry point"""
    # Check for API key
    if not OPENAI_API_KEY:
        print("Error: OPENAI_API_KEY environment variable is not set")
        print("Please set it in .env file or environment variables")
        sys.exit(1)

    print_welcome()

    # Initialize chatbot
    bot = ChatBot()
    print_session_info(bot)  # Show initial session info

    try:
        while True:
            # Get user input
            user_input = input("\nYou: ").strip()

            # Handle commands
            if user_input.lower() == "/help":
                print_welcome()
                continue
            elif user_input.lower() == "/save":
                bot.archive_session()
                print("\nSession archived. Starting new session...")
                print_session_info(bot)  # Show new session info
                continue
            elif user_input.lower() == "/reset":
                bot.clear_conversations()
                print("\nConversations and session data cleared...")
                print_session_info(bot)  # Show session info
                continue
            elif user_input.lower() == "/exit":
                bot.save_and_preserve()
                print("\nSession saved with preserved conversations. Goodbye!")
                break
            elif not user_input:
                continue

            # Get bot response
            try:
                response = bot.chat(user_input)
                print(f"\nSeele: {response}")
            except Exception as e:
                print(f"\nError: Failed to get response - {str(e)}")
                continue

    except KeyboardInterrupt:
        print("\n\nExiting without saving. Goodbye!")


if __name__ == "__main__":
    main()
