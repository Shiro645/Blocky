"""Minimal async RCON client (Minecraft / Source RCON protocol).

Written with asyncio streams so it never blocks the bot: no thread and no
signal handling (the mcrcon library uses SIGALRM, which only works in the
main thread).
"""
from __future__ import annotations

import asyncio
import struct

from utils.config import load_config

LOGIN, COMMAND, RESPONSE = 3, 2, 0
TIMEOUT = 10
FRAGMENT_SIZE = 4096  # Minecraft splits longer answers into several packets


class RconError(Exception):
    pass


def _packet(request_id: int, kind: int, payload: str) -> bytes:
    body = struct.pack("<ii", request_id, kind) + payload.encode("utf-8") + b"\x00\x00"
    return struct.pack("<i", len(body)) + body


async def _read_packet(reader: asyncio.StreamReader) -> tuple[int, int, str]:
    (length,) = struct.unpack("<i", await reader.readexactly(4))
    data = await reader.readexactly(length)
    request_id, kind = struct.unpack("<ii", data[:8])
    return request_id, kind, data[8:-2].decode("utf-8", errors="replace")


async def send_command(host: str, port: int, password: str, command: str) -> str:
    try:
        reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), TIMEOUT)
    except (OSError, asyncio.TimeoutError) as e:
        raise RconError(f"Cannot reach the Minecraft server RCON at {host}:{port} ({e or 'timeout'}).") from e
    try:
        async def exchange() -> str:
            writer.write(_packet(1, LOGIN, password))
            await writer.drain()
            while True:  # some servers send an empty packet before the auth answer
                request_id, kind, _ = await _read_packet(reader)
                if request_id == -1:
                    raise RconError("RCON authentication failed: check minecraft.rcon_password.")
                if kind == COMMAND:  # auth response type
                    break

            writer.write(_packet(2, COMMAND, command))
            await writer.drain()
            _, _, payload = await _read_packet(reader)
            if len(payload.encode("utf-8")) < FRAGMENT_SIZE:
                return payload

            # The answer was split in several packets: send a dummy request, the
            # server answers it only once the whole command output has been sent.
            writer.write(_packet(3, RESPONSE, ""))
            await writer.drain()
            parts = [payload]
            while True:
                request_id, _, payload = await _read_packet(reader)
                if request_id != 2:
                    break
                parts.append(payload)
            return "".join(parts)

        return await asyncio.wait_for(exchange(), TIMEOUT)
    except asyncio.TimeoutError as e:
        raise RconError("The Minecraft server did not answer in time (still starting?).") from e
    except asyncio.IncompleteReadError as e:
        raise RconError("The Minecraft server closed the RCON connection.") from e
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except OSError:
            pass


async def rcon_command(command: str) -> str:
    """Send a command to the Minecraft server configured in config.json."""
    mc = load_config()["minecraft"]
    return await send_command(mc["rcon_host"], int(mc["rcon_port"]), mc["rcon_password"], command)
