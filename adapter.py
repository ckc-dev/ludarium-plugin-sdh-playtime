
import sqlite3
from datetime import datetime, timedelta

from database import GameTrackerAdapter, _attach_icon


def _parse_dt(value):
    """Tolerant timestamp parse.

    Steam Playtime writes microseconds, but imported rows and host-padded
    values can arrive as a bare '%Y-%m-%dT%H:%M:%S'. The previous inline
    strptime assumed the microsecond form and its exact 'T' separator.
    """
    from database import parse_session_datetime
    parsed = parse_session_datetime(value)
    return parsed if parsed is not None else datetime.strptime(
        value.split('.')[0], "%Y-%m-%dT%H:%M:%S")


class SDHPlaytimeAdapter(GameTrackerAdapter):
    def __init__(self, source_id, display_name, db_path="storage.db", default_user_id=1):
        self.source_id = source_id
        self.display_name = display_name
        self.db_path = db_path
        self.default_user_id = default_user_id
        self.type = 'sdh_playtime'

    # play_time has no PRIMARY KEY and is NOT WITHOUT ROWID, so SQLite already
    # gives every row a unique, stable implicit rowid. We expose that as
    # session_id instead of adding a column: rewriting the table would collide
    # with the owning Steam Playtime app, which tracks its own migrations.
    supports_session_ids = True
    supports_session_write = True
    supports_game_write = True
    supports_game_merge = True
    supports_raw_transfer = True

    def _get_conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _session_id(self, original_date_time):
        """Resolves a date_time to a rowid for hosts that predate session ids.

        Lowest rowid wins, matching the single-row behaviour the session_id
        path gives us, so a duplicate date_time can no longer make one
        user action rewrite or delete several rows.
        """
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT rowid FROM play_time WHERE date_time = ? ORDER BY rowid LIMIT 1",
                (original_date_time,)).fetchone()
        finally:
            conn.close()
        return row['rowid'] if row else None

    @staticmethod
    def _target(session_id, original_date_time):
        """Returns (sql_fragment, params) addressing exactly one session row."""
        if session_id is not None:
            return "rowid = ?", (session_id,)
        return "date_time = ?", (original_date_time,)

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
            SELECT p.rowid AS session_id, p.date_time, p.duration, p.game_id, g.name
            FROM play_time p LEFT JOIN game_dict g ON p.game_id = g.game_id
        """).fetchall()
        conn.close()

        games_list = [dict(r, icon_url=_attach_icon(r['game_id']))
                      for r in games_raw]
        sessions = []
        for r in sessions_raw:
            s = dict(r, icon_url=_attach_icon(r['game_id']))
            start_dt = _parse_dt(str(s['date_time']))
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

    def update_session(self, game_id, duration, new_start, old_start, session_id=None):
        if session_id is None:
            session_id = self._session_id(old_start)
        conn = self._get_conn()
        cursor = conn.cursor()
        if session_id is not None:
            cursor.execute("UPDATE play_time SET game_id = ?, duration = ?, date_time = ? WHERE rowid = ?",
                           (game_id, duration, new_start, session_id))
        else:
            cursor.execute("UPDATE play_time SET game_id = ?, duration = ?, date_time = ? WHERE date_time = ?",
                           (game_id, duration, new_start, old_start))
        self._sync_overall_time(cursor)
        conn.commit()
        conn.close()

    supports_session_parts = False

    def get_session_parts(self, game_id, original_date_time):
        return []

    def update_session_part(self, part_id, duration, new_start, old_start):
        pass

    def add_session_part(self, game_id, start_time, duration):
        pass

    def delete_session_part(self, part_id):
        pass


    def delete_session(self, original_date_time, session_id=None):
        if session_id is None:
            session_id = self._session_id(original_date_time)
        conn = self._get_conn()
        cursor = conn.cursor()
        if session_id is not None:
            cursor.execute("DELETE FROM play_time WHERE rowid = ?", (session_id,))
        else:
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
            SELECT p.rowid AS session_id, p.date_time, p.duration, g.name, g.game_id FROM play_time p
            JOIN game_dict g ON p.game_id = g.game_id WHERE p.duration != ROUND(p.duration) ORDER BY p.date_time DESC
        """).fetchall()
        conn.close()
        return [{'session_id': r['session_id'], 'date_time': r['date_time'], 'name': r['name'], 'old_duration': r['duration'], 'new_duration': round(r['duration']), 'icon_url': _attach_icon(r['game_id'])} for r in raw]

    def apply_rounding(self, dates_list):
        conn = self._get_conn()
        cursor = conn.cursor()
        for dt in dates_list:
            if isinstance(dt, (tuple, list)):
                dt, session_id = dt
            else:
                session_id = None
            if session_id is None:
                row = cursor.execute(
                    "SELECT rowid FROM play_time WHERE date_time = ? ORDER BY rowid LIMIT 1", (dt,)).fetchone()
                session_id = row['rowid'] if row else None
            if session_id is not None:
                cursor.execute(
                    "UPDATE play_time SET duration = ROUND(duration) WHERE rowid = ?", (session_id,))
            else:
                cursor.execute(
                    "UPDATE play_time SET duration = ROUND(duration) WHERE date_time = ?", (dt,))
        self._sync_overall_time(cursor)
        conn.commit()
        conn.close()

    def get_cleanup_candidates(self, threshold_seconds):
        conn = self._get_conn()
        raw = conn.execute("""
            SELECT p.rowid AS session_id, p.date_time, p.duration, g.name, g.game_id FROM play_time p
            JOIN game_dict g ON p.game_id = g.game_id WHERE p.duration < ? ORDER BY p.date_time DESC
        """, (threshold_seconds,)).fetchall()
        conn.close()
        return [{'session_id': r['session_id'], 'date_time': r['date_time'], 'duration': r['duration'], 'name': r['name'], 'icon_url': _attach_icon(r['game_id'])} for r in raw]

    def apply_cleanup(self, dates_list):
        conn = self._get_conn()
        cursor = conn.cursor()
        for dt in dates_list:
            if isinstance(dt, (tuple, list)):
                dt, session_id = dt
            else:
                session_id = None
            if session_id is None:
                row = cursor.execute(
                    "SELECT rowid FROM play_time WHERE date_time = ? ORDER BY rowid LIMIT 1", (dt,)).fetchone()
                session_id = row['rowid'] if row else None
            if session_id is not None:
                cursor.execute("DELETE FROM play_time WHERE rowid = ?", (session_id,))
            else:
                cursor.execute("DELETE FROM play_time WHERE date_time = ?", (dt,))
        self._sync_overall_time(cursor)
        conn.commit()
        conn.close()

    def get_sessions_chronological(self):
        conn = self._get_conn()
        raw = conn.execute("""
            SELECT p.rowid AS session_id, p.date_time, p.duration, p.game_id, g.name FROM play_time p
            JOIN game_dict g ON p.game_id = g.game_id ORDER BY p.game_id, p.date_time ASC
        """).fetchall()
        conn.close()
        return raw

    def apply_merges(self, merges_list):
        conn = self._get_conn()
        cursor = conn.cursor()
        for p in merges_list:
            # Payload fields: primary_date_time|new_duration|doomed_csv[|primary_id][|doomed_ids_csv]
            # The trailing id fields are optional, so a payload built by an
            # older host still parses and falls back to date_time matching.
            parts = p.split('|')
            primary_dt = parts[0]
            primary_id = int(parts[3]) if len(parts) > 3 and parts[3] else None
            doomed_ids = parts[4].split(',') if len(parts) > 4 and parts[4] else []

            def _rowid_for(dt, sid):
                if sid:
                    return int(sid)
                row = cursor.execute(
                    "SELECT rowid FROM play_time WHERE date_time = ? ORDER BY rowid LIMIT 1",
                    (dt,)).fetchone()
                return row['rowid'] if row else None

            primary_id = _rowid_for(primary_dt, primary_id)
            if primary_id is not None:
                cursor.execute("UPDATE play_time SET duration = ? WHERE rowid = ?",
                               (float(parts[1]), primary_id))
            else:
                cursor.execute("UPDATE play_time SET duration = ? WHERE date_time = ?",
                               (float(parts[1]), primary_dt))

            doomed = [d for d in parts[2].split(',') if d]
            for idx, d in enumerate(doomed):
                sid = doomed_ids[idx] if idx < len(doomed_ids) else None
                doomed_id = _rowid_for(d, sid)
                if doomed_id is not None:
                    cursor.execute("DELETE FROM play_time WHERE rowid = ?", (doomed_id,))
                else:
                    cursor.execute("DELETE FROM play_time WHERE date_time = ?", (d,))
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
