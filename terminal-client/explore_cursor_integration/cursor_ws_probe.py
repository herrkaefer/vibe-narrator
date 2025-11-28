#!/usr/bin/env python3
"""Enhanced Cursor WebSocket probe with multiple detection methods."""

import asyncio
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Optional, Tuple

import websockets


def check_env_vars() -> Optional[int]:
    """Check environment variables for WebSocket port."""
    env_vars = [
        "CURSOR_WS_PORT",
        "CURSOR_AGENT_PORT",
        "CURSOR_PORT",
        "WS_PORT",
    ]
    for var in env_vars:
        port = os.getenv(var)
        if port:
            try:
                return int(port)
            except ValueError:
                pass
    return None


def check_config_file() -> Optional[int]:
    """Check Cursor configuration files for WebSocket port."""
    config_paths = [
        Path.home() / "Library/Application Support/Cursor/User/settings.json",
        Path.home() / ".cursor/config.json",
        Path.home() / ".config/cursor/settings.json",
    ]

    for config_path in config_paths:
        if not config_path.exists():
            continue

        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)

            # Check various possible keys
            keys_to_check = [
                "cursor.wsPort",
                "cursor.agentPort",
                "wsPort",
                "agentPort",
                "websocket.port",
                "websocketPort",
            ]

            # Try nested keys (e.g., cursor.wsPort)
            for key in keys_to_check:
                parts = key.split(".")
                value = config
                for part in parts:
                    if isinstance(value, dict) and part in value:
                        value = value[part]
                    else:
                        break
                else:
                    if isinstance(value, (int, str)):
                        try:
                            return int(value)
                        except ValueError:
                            pass
        except (json.JSONDecodeError, IOError, KeyError):
            continue

    return None


def find_cursor_ports_with_lsof() -> list[int]:
    """Use lsof to find ports that Cursor processes are listening on."""
    ports = []
    try:
        # Find Cursor processes
        result = subprocess.run(
            ["lsof", "-i", "-P", "-n"],
            capture_output=True,
            text=True,
            timeout=5,
        )

        for line in result.stdout.split("\n"):
            # Look for Cursor processes listening on ports
            if "Cursor" in line and "LISTEN" in line:
                # Extract port number (format: *:PORT or IP:PORT)
                match = re.search(r":(\d+)", line)
                if match:
                    try:
                        port = int(match.group(1))
                        # Filter to reasonable range
                        if 30000 <= port <= 50000:
                            ports.append(port)
                    except ValueError:
                        pass
    except (subprocess.TimeoutExpired, FileNotFoundError, subprocess.SubprocessError):
        pass

    # Remove duplicates and sort
    return sorted(list(set(ports)))


def find_ports_from_process_args() -> list[int]:
    """Extract port numbers from Cursor process command line arguments."""
    ports = []
    try:
        # Find Cursor process PIDs
        result = subprocess.run(
            ["pgrep", "-f", "Cursor"],
            capture_output=True,
            text=True,
            timeout=3,
        )

        if not result.stdout.strip():
            return ports

        pids = result.stdout.strip().split("\n")

        for pid in pids:
            try:
                # Get process command line arguments
                ps_result = subprocess.run(
                    ["ps", "-p", pid, "-o", "command="],
                    capture_output=True,
                    text=True,
                    timeout=2,
                )

                cmd_line = ps_result.stdout
                # Look for port patterns in command line
                # Common patterns: --port=12345, --port 12345, port=12345, :12345
                patterns = [
                    r"--port[=:](\d+)",
                    r"port[=:](\d+)",
                    r":(\d{4,5})\b",  # Ports in URLs or addresses
                    r"(\d{5})",  # 5-digit numbers (likely ports)
                ]

                for pattern in patterns:
                    matches = re.finditer(pattern, cmd_line, re.IGNORECASE)
                    for match in matches:
                        try:
                            port = int(match.group(1))
                            if 30000 <= port <= 50000:
                                ports.append(port)
                        except (ValueError, IndexError):
                            pass
            except (subprocess.TimeoutExpired, ValueError, subprocess.SubprocessError):
                continue
    except (subprocess.TimeoutExpired, FileNotFoundError, subprocess.SubprocessError):
        pass

    return sorted(list(set(ports)))


def find_ports_from_logs() -> list[int]:
    """Search Cursor log files for port numbers."""
    ports = []
    log_paths = [
        Path.home() / "Library/Application Support/Cursor/logs",
        Path.home() / "Library/Logs/Cursor",
        Path.home() / ".cursor/logs",
    ]

    for log_dir in log_paths:
        if not log_dir.exists():
            continue

        try:
            # Get recent log files (last 5)
            log_files = sorted(
                log_dir.glob("*.log"),
                key=lambda p: p.stat().st_mtime,
                reverse=True
            )[:5]

            for log_file in log_files:
                try:
                    with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
                        # Read last 1000 lines to avoid reading huge files
                        lines = f.readlines()[-1000:]
                        for line in lines:
                            # Look for WebSocket URLs or port numbers
                            # Patterns: ws://localhost:12345, port 12345, :12345
                            patterns = [
                                r"ws://[^:]+:(\d+)",
                                r"wss://[^:]+:(\d+)",
                                r"port[:\s]+(\d{4,5})",
                                r":(\d{5})\b",
                            ]

                            for pattern in patterns:
                                matches = re.finditer(pattern, line, re.IGNORECASE)
                                for match in matches:
                                    try:
                                        port = int(match.group(1))
                                        if 30000 <= port <= 50000:
                                            ports.append(port)
                                    except (ValueError, IndexError):
                                        pass
                except (IOError, OSError):
                    continue
        except (OSError, PermissionError):
            continue

    return sorted(list(set(ports)))


def find_ports_from_netstat() -> list[int]:
    """Use netstat to find listening ports (alternative to lsof)."""
    ports = []
    try:
        # Try netstat (may not be available on all systems)
        result = subprocess.run(
            ["netstat", "-an"],
            capture_output=True,
            text=True,
            timeout=5,
        )

        for line in result.stdout.split("\n"):
            # Look for LISTEN state and localhost addresses
            if "LISTEN" in line and ("127.0.0.1" in line or "::1" in line or "*" in line):
                # Extract port number
                match = re.search(r":(\d+)", line)
                if match:
                    try:
                        port = int(match.group(1))
                        if 30000 <= port <= 50000:
                            ports.append(port)
                    except ValueError:
                        pass
    except (subprocess.TimeoutExpired, FileNotFoundError, subprocess.SubprocessError):
        pass

    return sorted(list(set(ports)))


def find_ports_from_runtime_files() -> list[int]:
    """Check Cursor runtime files and temporary directories for port info."""
    ports = []
    runtime_paths = [
        Path.home() / "Library/Application Support/Cursor",
        Path.home() / ".cursor",
        Path("/tmp"),
    ]

    # Look for files that might contain port information
    patterns = ["*.json", "*.txt", "*.log", "*.conf", "*.config"]

    for runtime_path in runtime_paths:
        if not runtime_path.exists():
            continue

        try:
            # Search for files with "port" or "ws" in name
            for pattern in ["*port*", "*ws*", "*websocket*", "*agent*"]:
                for file_path in runtime_path.rglob(pattern):
                    if not file_path.is_file():
                        continue

                    # Skip large files
                    try:
                        if file_path.stat().st_size > 100000:  # 100KB
                            continue
                    except OSError:
                        continue

                    try:
                        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                            content = f.read()
                            # Look for port numbers
                            matches = re.finditer(r":(\d{5})\b|port[:\s]+(\d{5})", content, re.IGNORECASE)
                            for match in matches:
                                port_str = match.group(1) or match.group(2)
                                try:
                                    port = int(port_str)
                                    if 30000 <= port <= 50000:
                                        ports.append(port)
                                except ValueError:
                                    pass
                    except (IOError, OSError, UnicodeDecodeError):
                        continue
        except (OSError, PermissionError):
            continue

    return sorted(list(set(ports)))


def get_common_dev_ports() -> list[int]:
    """Return common development server ports that might be used."""
    # Common ports for development servers, Chrome DevTools, etc.
    return [
        9222,   # Chrome DevTools
        9229,   # Chrome DevTools (alternative)
        8080,   # Common dev server
        3000,   # Common dev server
        5173,   # Vite default
        5174,   # Vite alternative
    ]


async def try_connect(port: int, timeout: float = 1.0) -> Optional[Tuple[str, websockets.WebSocketClientProtocol]]:
    """Try to connect to WebSocket on given port with various paths.

    Returns (url, ws) tuple if successful, None otherwise.
    Note: The WebSocket connection is kept open and should be closed by the caller.
    """
    paths = ["agent", "cursor", "cursor-agent", "ws", "websocket", ""]

    for path in paths:
        url = f"ws://127.0.0.1:{port}/{path}".rstrip("/")
        ws = None
        try:
            async with asyncio.timeout(timeout):
                # Connect without context manager to keep connection open
                ws = await websockets.connect(url, ping_interval=None)
                # Try to send a simple message to verify it's active
                try:
                    await asyncio.wait_for(ws.send(json.dumps({"type": "ping"})), timeout=0.5)
                except:
                    pass
                return (url, ws)
        except (asyncio.TimeoutError, OSError, websockets.exceptions.InvalidURI,
                websockets.exceptions.InvalidHandshake, ConnectionRefusedError):
            if ws:
                try:
                    await ws.close()
                except:
                    pass
            continue
        except Exception:
            # Other errors might indicate it's the right port but wrong path
            if ws:
                try:
                    await ws.close()
                except:
                    pass
            continue

    return None


async def find_ws() -> Optional[Tuple[str, websockets.WebSocketClientProtocol]]:
    """Find Cursor WebSocket using multiple methods."""

    # Method 1: Check environment variables
    print("🔍 Method 1: Checking environment variables...")
    port = check_env_vars()
    if port:
        print(f"   Found port {port} from environment variable")
        result = await try_connect(port)
        if result:
            return result

    # Method 2: Check configuration files
    print("🔍 Method 2: Checking configuration files...")
    port = check_config_file()
    if port:
        print(f"   Found port {port} from configuration file")
        result = await try_connect(port)
        if result:
            return result

    # Method 3: Use lsof to find Cursor ports
    print("🔍 Method 3: Using lsof to find Cursor ports...")
    ports = find_cursor_ports_with_lsof()
    if ports:
        print(f"   Found {len(ports)} potential port(s): {ports}")
        for port in ports:
            result = await try_connect(port)
            if result:
                return result
    else:
        print("   No Cursor ports found with lsof")

    # Method 4: Extract ports from process command line arguments
    print("🔍 Method 4: Checking process command line arguments...")
    ports = find_ports_from_process_args()
    if ports:
        print(f"   Found {len(ports)} potential port(s): {ports}")
        for port in ports:
            result = await try_connect(port)
            if result:
                return result
    else:
        print("   No ports found in process arguments")

    # Method 5: Search log files for port numbers
    print("🔍 Method 5: Searching log files for port numbers...")
    ports = find_ports_from_logs()
    if ports:
        print(f"   Found {len(ports)} potential port(s): {ports}")
        for port in ports:
            result = await try_connect(port)
            if result:
                return result
    else:
        print("   No ports found in logs")

    # Method 6: Use netstat (alternative to lsof)
    print("🔍 Method 6: Using netstat to find listening ports...")
    ports = find_ports_from_netstat()
    if ports:
        print(f"   Found {len(ports)} potential port(s): {ports}")
        for port in ports:
            result = await try_connect(port)
            if result:
                return result
    else:
        print("   No ports found with netstat")

    # Method 7: Check runtime files and temp directories
    print("🔍 Method 7: Checking runtime files and temp directories...")
    ports = find_ports_from_runtime_files()
    if ports:
        print(f"   Found {len(ports)} potential port(s): {ports}")
        for port in ports:
            result = await try_connect(port)
            if result:
                return result
    else:
        print("   No ports found in runtime files")

    # Method 8: Try common development server ports
    print("🔍 Method 8: Trying common development server ports...")
    ports = get_common_dev_ports()
    print(f"   Trying {len(ports)} common port(s): {ports}")
    for port in ports:
        result = await try_connect(port, timeout=0.5)
        if result:
            return result

    # Method 9: Scan common port range
    print("🔍 Method 9: Scanning ports 35000–45000...")
    # Scan in smaller chunks with progress updates
    chunk_size = 1000
    for start in range(35000, 45001, chunk_size):
        end = min(start + chunk_size, 45001)
        print(f"   Scanning {start}–{end}...", end="\r")

        # Try ports in this chunk
        for port in range(start, end):
            result = await try_connect(port, timeout=0.3)  # Faster timeout for scanning
            if result:
                print()  # New line after progress
                return result

    print()  # New line after progress
    return None


async def main():
    """Main function."""
    print("🚀 Starting Cursor WebSocket probe...\n")

    result = await find_ws()
    if not result:
        print("\n❌ WebSocket not found.")
        print("💡 Suggestions:")
        print("   - Make sure Cursor is running")
        print("   - Try opening AI Pane & Browser in Cursor")
        print("   - Check if Cursor is using a different port range")
        print("   - Set CURSOR_WS_PORT environment variable")
        print("   - Check Cursor's DevTools console (Cmd+Option+I)")
        print("   - Look for WebSocket connections in Network tab")
        print("   - Try: lsof -i -P -n | grep Cursor")
        print("   - Check Cursor's output panel for connection info")
        return

    url, ws = result
    print(f"\n✅ Connected to: {url}\n")
    print("👂 Listening for messages... (Press Ctrl+C to stop)\n")

    try:
        while True:
            try:
                msg = await ws.recv()
                try:
                    data = json.loads(msg)
                    print(json.dumps(data, indent=2, ensure_ascii=False))
                except json.JSONDecodeError:
                    print(msg)
            except websockets.exceptions.ConnectionClosed:
                print("\n⚠️  Connection closed by server")
                break
    except KeyboardInterrupt:
        print("\n\n👋 Stopped by user")
    finally:
        # Clean up connection
        try:
            await ws.close()
        except:
            pass


if __name__ == "__main__":
    asyncio.run(main())
