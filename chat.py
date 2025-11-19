#!/usr/bin/env python3
"""Simple chat interface for vibe-narrator.

This script provides a terminal-based chat interface where:
- User types messages in the terminal
- Messages are sent to the bridge for narration
- AI responses are spoken via audio (not printed to terminal)
- Supports multi-turn conversations
"""

import sys

def main():
    print("🎤 Vibe Narrator Chat")
    print("=" * 50)
    print()
    print("Type your messages and press Enter.")
    print("The AI will respond via audio (not shown in terminal).")
    print()
    print("Commands:")
    print("  /quit or /exit - Exit the chat")
    print("  /clear - Clear conversation history (not implemented yet)")
    print()
    print("=" * 50)
    print()

    try:
        while True:
            # Read user input
            try:
                user_input = input("You: ").strip()
            except EOFError:
                # Handle Ctrl+D
                print()
                break

            # Check for empty input
            if not user_input:
                continue

            # Check for commands
            if user_input.lower() in ["/quit", "/exit"]:
                print("👋 Goodbye!")
                break
            elif user_input.lower() == "/clear":
                print("📝 (Clear history not implemented yet)")
                continue

            # Simply print the user input to stdout
            # Bridge will capture this and send to MCP
            print(user_input)
            sys.stdout.flush()

    except KeyboardInterrupt:
        # Handle Ctrl+C
        print()
        print("👋 Goodbye!")
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
