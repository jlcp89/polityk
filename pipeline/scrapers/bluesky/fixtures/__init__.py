"""Recorded AT-Proto firehose payloads used by the unit tests.

The fixtures are JSON-serialised ``app.bsky.feed.post`` records as they
appear after the firehose `RepoCommit` is decoded — trimmed to the keys
our filter / parser actually depend on. They are intentionally small;
real firehose volume is enormous and we drop everything that is not
Spanish + GT-handle before deserialising.
"""
