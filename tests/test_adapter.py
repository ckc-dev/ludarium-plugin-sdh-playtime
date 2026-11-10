"""SDH adapter write matrix and capability contract."""

import os
import sqlite3
import tempfile
import unittest

from plugin_sdk import SessionRef
from plugins.sdh_playtime.adapter import SDHPlaytimeAdapter


def _sdh_fixture(path):
    conn = sqlite3.connect(path)
    try:
        conn.executescript("""
            CREATE TABLE game_dict (
                game_id TEXT PRIMARY KEY,
                name TEXT NOT NULL
            );
            CREATE TABLE play_time (
                game_id TEXT,
                date_time TEXT,
                duration REAL
            );
            CREATE TABLE overall_time (
                game_id TEXT PRIMARY KEY,
                duration REAL
            );
        """)
        conn.execute(
            "INSERT INTO game_dict (game_id, name) VALUES ('100', 'Steam Game')")
        conn.execute(
            "INSERT INTO play_time (game_id, date_time, duration) "
            "VALUES ('100', '2026-01-01T10:00:00', 3600)")
        conn.commit()
    finally:
        conn.close()

class TestSdhCapabilities(unittest.TestCase):
    def test_capabilities_are_honest(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, 'playtime.db')
            _sdh_fixture(path)
            adapter = SDHPlaytimeAdapter('sdh', 'SDH', path, 1)
            self.assertTrue(adapter.supports_session_write)
            self.assertTrue(adapter.supports_game_write)
            self.assertTrue(adapter.supports_game_merge)
            self.assertTrue(adapter.supports_raw_transfer)
            games, sessions = adapter.get_raw_export()
            self.assertIsInstance(games, list)
            self.assertIsInstance(sessions, list)


class TestSdhWriteMatrix(unittest.TestCase):
    def test_read_write_round_trip(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, 'playtime.db')
            _sdh_fixture(path)
            adapter = SDHPlaytimeAdapter('sdh', 'SDH', path, 1)

            adapter.add_game('200', 'Second Game')
            adapter.add_session('200', '2026-01-02T10:00:00', 120.5)
            games, sessions, _ = adapter.fetch_dashboard_data()
            self.assertTrue(any(game['game_id'] == '200' for game in games))
            session = next(s for s in sessions
                           if s['date_time'] == '2026-01-02T10:00:00')
            self.assertAlmostEqual(session['duration'], 120.5)

            candidates = adapter.get_round_candidates()
            candidate = next(c for c in candidates
                             if c['date_time'] == '2026-01-02T10:00:00')
            adapter.apply_rounding([SessionRef(
                'sdh', candidate['date_time'], candidate['session_id'])])
            _, sessions, _ = adapter.fetch_dashboard_data()
            rounded = next(s for s in sessions
                           if s['date_time'] == '2026-01-02T10:00:00')
            self.assertEqual(rounded['duration'], 121)

            adapter.update_session(
                '200', 60, '2026-01-02T11:00:00',
                rounded['date_time'], session_id=rounded['session_id'])
            _, sessions, _ = adapter.fetch_dashboard_data()
            updated = next(s for s in sessions
                           if s['date_time'] == '2026-01-02T11:00:00')
            self.assertEqual(updated['duration'], 60)
            adapter.delete_session(
                updated['date_time'], session_id=updated['session_id'])
            _, sessions, _ = adapter.fetch_dashboard_data()
            self.assertFalse(any(
                s['date_time'] == '2026-01-02T11:00:00' for s in sessions))

            adapter.add_session('200', '2026-01-03T10:00:00', 10)
            cleanup = adapter.get_cleanup_candidates(60)
            adapter.apply_cleanup([
                SessionRef('sdh', c['date_time'], c['session_id'])
                for c in cleanup
            ])
            _, sessions, _ = adapter.fetch_dashboard_data()
            self.assertFalse(any(
                s['date_time'] == '2026-01-03T10:00:00' for s in sessions))

            adapter.add_game('201', 'Second Game')
            adapter.add_session('201', '2026-01-04T10:00:00', 30)
            merge_candidates = adapter.get_game_merge_candidates()
            duplicate = next(
                c for c in merge_candidates if c['name'] == 'Second Game')
            adapter.apply_game_merges(
                duplicate['instances'][0]['game_id'],
                [duplicate['instances'][1]['game_id']])
            games, _, _ = adapter.fetch_dashboard_data()
            self.assertEqual(
                sum(1 for game in games if game['name'] == 'Second Game'), 1)

            raw_games, raw_sessions = adapter.get_raw_export()
            self.assertTrue(raw_games)
            self.assertTrue(raw_sessions)

    def test_backup_and_disable_renames_the_database(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, 'playtime.db')
            _sdh_fixture(path)
            adapter = SDHPlaytimeAdapter('sdh', 'SDH', path, 1)
            adapter.backup_and_disable()
            self.assertFalse(os.path.exists(path))
            self.assertTrue(any(name.startswith('playtime.db.backup_')
                                for name in os.listdir(tmpdir)))
