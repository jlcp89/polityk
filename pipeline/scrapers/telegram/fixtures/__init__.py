"""Recorded Telegram channel messages used by the unit tests.

The fixtures are JSON dumps of `telethon.Message.to_dict()` calls trimmed to
the fields the parser actually consumes. They are NOT exhaustive Telegram
objects — they are the minimal contract our parser depends on. If a future
telethon release renames or removes any consumed key, the parser tests fail
loudly and we update both sides together.
"""
