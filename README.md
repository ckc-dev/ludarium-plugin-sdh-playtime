# Ludarium Steam Deck Playtime Plugin

Tracker adapter for the `sdh-playtime` SQLite database used by Steam Deck
playtime tools.

- `PLUGIN_TYPE`: `sdh_playtime`
- `PLUGIN_DISPLAY_NAME`: `Steam Deck (sdh-playtime)`
- Plugin API: 2
- Adapter: `adapter.py`

From this plugin repository, with the Ludarium checkout on `PYTHONPATH`:

```bash
PYTHONPATH=/path/to/host python -m unittest discover -s tests -q
```
