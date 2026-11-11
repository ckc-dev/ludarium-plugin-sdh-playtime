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

## Acknowledgements

This plugin is designed to interoperate with the maintained
[SDH-PlayTime fork](https://github.com/0u73r-h34v3n/SDH-PlayTime) by
0u73r-h34v3n, distributed under the BSD 3-Clause License. It is based on the
archived [ma3a/SDH-PlayTime](https://github.com/ma3a/SDH-PlayTime) project. The
upstream project supplied the database format this adapter reads and writes;
its copyright and license are preserved in
[`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).

Steam Deck is a trademark of Valve Corporation. This project is not affiliated
with or endorsed by Valve.

## License

This plugin is free software: you can redistribute it and/or modify it under
the terms of the GNU General Public License as published by the Free Software
Foundation, version 3 only.

This program is distributed in the hope that it will be useful, but WITHOUT
ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
FOR A PARTICULAR PURPOSE. See [`LICENSE`](LICENSE) for the full terms.

Copyright (C) 2026 Ludarium contributors.

## Continuous integration

The plugin CI checks out the private Ludarium host into a temporary `host/`
directory so the plugin can run its full integration suite against the current
host contract. The workflow requires a repository secret named
`HOST_REPO_TOKEN`: a fine-grained token with read-only access to
`ckc-dev/ludarium`. No host code is vendored or linked into this repository.
