#!/usr/bin/env python3
"""Listen to cursor-agent-log --stream and output each token.

This script runs `cursor-agent-log --stream` and outputs each token as it arrives.
"""

import argparse
import json
import os
import subprocess
import sys
from typing import Optional


def parse_token(line: str) -> Optional[str]:
    """Parse a token from a line of output.

    Handles different possible formats:
    - JSON lines: {"token": "..."}
    - Plain text tokens
    - Other JSON structures
    """
    line = line.strip()
    if not line:
        return None

    # Try to parse as JSON
    try:
        data = json.loads(line)
        # Check for common token field names
        if isinstance(data, dict):
            # Try various possible field names
            for key in ['token', 'text', 'content', 'delta', 'message']:
                if key in data:
                    value = data[key]
                    if isinstance(value, str):
                        return value
                    elif isinstance(value, dict) and 'content' in value:
                        return value['content']
            # If it's a dict but no token field, return the whole dict as string
            return str(data)
        elif isinstance(data, str):
            return data
    except (json.JSONDecodeError, ValueError):
        # Not JSON, treat as plain text
        pass

    # Return as-is if not JSON or if JSON parsing didn't yield a token
    return line


def main():
    """Main function to listen to cursor-agent-log --stream."""
    parser = argparse.ArgumentParser(
        description='Listen to cursor-agent-log --stream and output each token'
    )
    parser.add_argument(
        '--command',
        default=os.getenv('CURSOR_AGENT_LOG_CMD', 'cursor-agent-log'),
        help='Path to cursor-agent-log command (default: cursor-agent-log or CURSOR_AGENT_LOG_CMD env var)'
    )
    args = parser.parse_args()

    try:
        # Start the cursor-agent-log process
        process = subprocess.Popen(
            [args.command, '--stream'],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,  # Line buffered
        )

        print(f"🔍 Listening to {args.command} --stream...", file=sys.stderr)
        print("Press Ctrl+C to stop\n", file=sys.stderr)

        # Read output line by line
        try:
            for line in process.stdout:
                token = parse_token(line)
                if token:
                    # Output the token immediately (no buffering)
                    print(token, end='', flush=True)
        except KeyboardInterrupt:
            print("\n\n⚠️  Interrupted by user", file=sys.stderr)
            process.terminate()

        # Wait for process to finish
        process.wait()

        # Check for errors
        if process.returncode != 0:
            stderr_output = process.stderr.read()
            if stderr_output:
                print(f"\n❌ Error from cursor-agent-log:", file=sys.stderr)
                print(stderr_output, file=sys.stderr)
            sys.exit(process.returncode)

    except FileNotFoundError:
        print(f"❌ Error: {args.command} command not found", file=sys.stderr)
        print(f"Please make sure {args.command} is in your PATH", file=sys.stderr)
        print("Or specify the command path with --command option", file=sys.stderr)
        print("Or set CURSOR_AGENT_LOG_CMD environment variable", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"❌ Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

