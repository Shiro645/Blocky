from __future__ import annotations

import asyncio
import struct
import unittest

from utils.minecraft_rcon import RconError, send_command

PASSWORD = "secret"
LONG_LIST = "There are 400 whitelisted players: " + ", ".join(f"player_{i:03d}" for i in range(400))


def packet(request_id: int, kind: int, payload: str) -> bytes:
    body = struct.pack("<ii", request_id, kind) + payload.encode() + b"\x00\x00"
    return struct.pack("<i", len(body)) + body


class FakeMinecraftRcon:
    """Behaves like the vanilla server: auth, commands, 4096-byte fragments, unknown types."""

    def __init__(self):
        self.commands: list[str] = []

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        try:
            while True:
                (length,) = struct.unpack("<i", await reader.readexactly(4))
                data = await reader.readexactly(length)
                request_id, kind = struct.unpack("<ii", data[:8])
                payload = data[8:-2].decode()
                if kind == 3:
                    ok = payload == PASSWORD
                    writer.write(packet(request_id if ok else -1, 2, ""))
                elif kind == 2:
                    self.commands.append(payload)
                    answer = LONG_LIST if payload == "whitelist list" else f"Added {payload.split()[-1]} to the whitelist"
                    raw = answer.encode()
                    for i in range(0, len(raw), 4096):
                        writer.write(packet(request_id, 0, raw[i:i + 4096].decode()))
                else:
                    writer.write(packet(request_id, 0, f"Unknown request {kind:x}"))
                await writer.drain()
        except asyncio.IncompleteReadError:
            pass
        finally:
            writer.close()


class RconTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.fake = FakeMinecraftRcon()
        self.server = await asyncio.start_server(self.fake.handle, "127.0.0.1", 0)
        self.port = self.server.sockets[0].getsockname()[1]

    async def asyncTearDown(self):
        self.server.close()
        await self.server.wait_closed()

    async def test_command(self):
        answer = await send_command("127.0.0.1", self.port, PASSWORD, "whitelist add Steve")
        self.assertEqual(answer, "Added Steve to the whitelist")
        self.assertEqual(self.fake.commands, ["whitelist add Steve"])

    async def test_long_answer_is_reassembled(self):
        answer = await send_command("127.0.0.1", self.port, PASSWORD, "whitelist list")
        self.assertGreater(len(LONG_LIST), 4096)
        self.assertEqual(answer, LONG_LIST)

    async def test_wrong_password(self):
        with self.assertRaisesRegex(RconError, "authentication failed"):
            await send_command("127.0.0.1", self.port, "nope", "whitelist list")
        self.assertEqual(self.fake.commands, [])

    async def test_server_down(self):
        self.server.close()
        await self.server.wait_closed()
        with self.assertRaisesRegex(RconError, "Cannot reach"):
            await send_command("127.0.0.1", self.port, PASSWORD, "list")


if __name__ == "__main__":
    unittest.main()
