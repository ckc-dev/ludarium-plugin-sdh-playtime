import sqlite3
from datetime import datetime, timedelta

from database import GameTrackerAdapter, _attach_icon


class SDHPlaytimeAdapter(GameTrackerAdapter):
    def __init__(self, source_id, display_name, db_path="storage.db", default_user_id=1):
        self.source_id = source_id
        self.display_name = display_name
        self.db_path = db_path
        self.default_user_id = default_user_id
        self.type = 'sdh_playtime'

    def _get_conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _sync_overall_time(self, cursor):
        cursor.execute(
            "SELECT game_id, SUM(duration) as total FROM play_time GROUP BY game_id")
        actual_totals = cursor.fetchall()
        cursor.execute("DELETE FROM overall_time")
        for row in actual_totals:
            if row['total'] is not None and row['total'] > 0:
                cursor.execute(
                    "INSERT INTO overall_time (game_id, duration) VALUES (?, ?)", (row['game_id'], row['total']))

    def fetch_dashboard_data(self):
        conn = self._get_conn()
        games_raw = conn.execute("""
            SELECT g.game_id, g.name, COALESCE(o.duration, 0) as stored_duration,
            COALESCE((SELECT SUM(duration) FROM play_time p WHERE p.game_id = g.game_id), 0) as actual_duration,
            (SELECT MAX(date_time) FROM play_time p WHERE p.game_id = g.game_id) as last_session
            FROM game_dict g LEFT JOIN overall_time o ON g.game_id = o.game_id
        """).fetchall()

        sessions_raw = conn.execute("""
            SELECT p.date_time, p.duration, p.game_id, g.name
            FROM play_time p LEFT JOIN game_dict g ON p.game_id = g.game_id
        """).fetchall()
        conn.close()

        games_list = [dict(r, icon_url=_attach_icon(r['game_id']))
                      for r in games_raw]
        sessions = []
        for r in sessions_raw:
            s = dict(r, icon_url=_attach_icon(r['game_id']))
            start_dt = datetime.strptime(str(s['date_time']).split('.')[
                                         0], "%Y-%m-%dT%H:%M:%S")
            s['start_dt'], s['end_dt'], s['has_overlap'] = start_dt, start_dt + \
                timedelta(seconds=float(s['duration'])), False
            sessions.append(s)

        return games_list, sessions, sum(r['actual_duration'] for r in games_list)

    def get_all_games(self):
        conn = self._get_conn()
        games = conn.execute("SELECT game_id, name FROM game_dict").fetchall()
        conn.close()
        return games

    def add_game(self, game_id, name):
        conn = self._get_conn()
        conn.execute(
            "INSERT OR IGNORE INTO game_dict (game_id, name) VALUES (?, ?)", (game_id, name))
        conn.commit()
        conn.close()

    def delete_game(self, game_id):
        conn = self._get_conn()
        conn.execute("DELETE FROM play_time WHERE game_id = ?", (game_id,))
        conn.execute("DELETE FROM overall_time WHERE game_id = ?", (game_id,))
        conn.execute("DELETE FROM game_dict WHERE game_id = ?", (game_id,))
        conn.commit()
        conn.close()

    def add_session(self, game_id, start_time, duration):
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO play_time (game_id, date_time, duration) VALUES (?, ?, ?)",
                       (game_id, start_time, duration))
        self._sync_overall_time(cursor)
        conn.commit()
        conn.close()
        self.report(f"Session added to '{self.display_name}' ({self.type})")

    def update_session(self, game_id, duration, new_start, old_start):
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute("UPDATE play_time SET game_id = ?, duration = ?, date_time = ? WHERE date_time = ?",
                       (game_id, duration, new_start, old_start))
        self._sync_overall_time(cursor)
        conn.commit()
        conn.close()

    def delete_session(self, original_date_time):
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM play_time WHERE date_time = ?",
                       (original_date_time,))
        self._sync_overall_time(cursor)
        conn.commit()
        conn.close()

    def recalculate_totals(self):
        conn = self._get_conn()
        cursor = conn.cursor()
        self._sync_overall_time(cursor)
        conn.commit()
        conn.close()

    def get_round_candidates(self):
        conn = self._get_conn()
        raw = conn.execute("""
            SELECT p.date_time, p.duration, g.name, g.game_id FROM play_time p
            JOIN game_dict g ON p.game_id = g.game_id WHERE p.duration != ROUND(p.duration) ORDER BY p.date_time DESC
        """).fetchall()
        conn.close()
        return [{'date_time': r['date_time'], 'name': r['name'], 'old_duration': r['duration'], 'new_duration': round(r['duration']), 'icon_url': _attach_icon(r['game_id'])} for r in raw]

    def apply_rounding(self, dates_list):
        conn = self._get_conn()
        cursor = conn.cursor()
        for dt in dates_list:
            cursor.execute(
                "UPDATE play_time SET duration = ROUND(duration) WHERE date_time = ?", (dt,))
        self._sync_overall_time(cursor)
        conn.commit()
        conn.close()

    def get_cleanup_candidates(self, threshold_seconds):
        conn = self._get_conn()
        raw = conn.execute("""
            SELECT p.date_time, p.duration, g.name, g.game_id FROM play_time p
            JOIN game_dict g ON p.game_id = g.game_id WHERE p.duration < ? ORDER BY p.date_time DESC
        """, (threshold_seconds,)).fetchall()
        conn.close()
        return [{'date_time': r['date_time'], 'duration': r['duration'], 'name': r['name'], 'icon_url': _attach_icon(r['game_id'])} for r in raw]

    def apply_cleanup(self, dates_list):
        conn = self._get_conn()
        cursor = conn.cursor()
        for dt in dates_list:
            cursor.execute("DELETE FROM play_time WHERE date_time = ?", (dt,))
        self._sync_overall_time(cursor)
        conn.commit()
        conn.close()

    def get_sessions_chronological(self):
        conn = self._get_conn()
        raw = conn.execute("""
            SELECT p.date_time, p.duration, p.game_id, g.name FROM play_time p
            JOIN game_dict g ON p.game_id = g.game_id ORDER BY p.game_id, p.date_time ASC
        """).fetchall()
        conn.close()
        return raw

    def apply_merges(self, merges_list):
        conn = self._get_conn()
        cursor = conn.cursor()
        for p in merges_list:
            parts = p.split('|')
            cursor.execute("UPDATE play_time SET duration = ? WHERE date_time = ?", (float(
                parts[1]), parts[0]))
            for d in parts[2].split(','):
                cursor.execute(
                    "DELETE FROM play_time WHERE date_time = ?", (d,))
        self._sync_overall_time(cursor)
        conn.commit()
        conn.close()

    def get_game_merge_candidates(self):
        conn = self._get_conn()
        dupes = conn.execute(
            "SELECT name FROM game_dict GROUP BY name HAVING COUNT(game_id) > 1").fetchall()

        candidates = []
        for d in dupes:
            name = d['name']
            instances = conn.execute("""
                SELECT g.game_id,
                       COALESCE((SELECT SUM(duration) FROM play_time p WHERE p.game_id = g.game_id), 0) as actual_duration,
                       (SELECT MAX(date_time) FROM play_time p WHERE p.game_id = g.game_id) as last_session
                FROM game_dict g WHERE g.name = ?
            """, (name,)).fetchall()

            inst_list = [dict(r) for r in instances]
            inst_list.sort(key=lambda x: x['actual_duration'], reverse=True)

            candidates.append({
                'name': name,
                'instances': inst_list,
                'icon_url': _attach_icon(inst_list[0]['game_id'])
            })
        conn.close()
        return candidates

    def apply_game_merges(self, primary_id, duplicate_ids):
        conn = self._get_conn()
        cursor = conn.cursor()
        for dup_id in duplicate_ids:
            cursor.execute(
                "UPDATE play_time SET game_id = ? WHERE game_id = ?", (primary_id, dup_id))
            cursor.execute(
                "DELETE FROM overall_time WHERE game_id = ?", (dup_id,))
            cursor.execute(
                "DELETE FROM game_dict WHERE game_id = ?", (dup_id,))
        self._sync_overall_time(cursor)
        conn.commit()
        conn.close()

    def get_raw_export(self):
        conn = self._get_conn()
        games = conn.execute("SELECT game_id, name FROM game_dict").fetchall()
        sessions = conn.execute(
            "SELECT game_id, date_time, duration FROM play_time").fetchall()
        conn.close()
        return [dict(g) for g in games], [dict(s) for s in sessions]

    def import_raw_data(self, games, sessions):
        conn = self._get_conn()
        cursor = conn.cursor()
        for g in games:
            cursor.execute(
                "INSERT OR IGNORE INTO game_dict (game_id, name) VALUES (?, ?)", (g['game_id'], g['name']))
        for s in sessions:
            cursor.execute("INSERT OR IGNORE INTO play_time (game_id, date_time, duration) VALUES (?, ?, ?)",
                           (s['game_id'], s['date_time'], s['duration']))
        self._sync_overall_time(cursor)
        conn.commit()
        conn.close()

    def backup_and_disable(self):
        import os
        from datetime import datetime
        if os.path.exists(self.db_path):
            backup_path = self.db_path + \
                f".backup_{datetime.now().strftime('%Y%m%d%H%M%S')}"
            os.rename(self.db_path, backup_path)
