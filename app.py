"""
Simple web UI for browsing floorball stats.

Reads the SAME JSON files the analysis scripts use.

Project layout:

    floorball_ai/
        analysis/
            game_stats.py
            season_stats.py
            career_stats.py
        data/
            parse_match.py
            url_import.py
            games/
                2025-2026/*.json
        web/
            layout.py            - CSS + shared HTML helpers
            season_sections.py   - one render_* function per season section
            routes_home.py       - "/" and "/import-match-url"
            routes_game.py       - "/game-stats" and "/game/<season>/<file>"
            routes_season.py     - "/season-stats" and "/season/<season>"
            routes_career.py     - "/career"
        app.py

Run from project root:

    python app.py

or:

    python app.py --games-dir data/games --port 5000
"""

import argparse

from flask import Flask

from web.routes_home import home_bp
from web.routes_game import game_bp
from web.routes_season import season_bp
from web.routes_career import career_bp


DEFAULT_GAMES_DIR = "data/games"
DEFAULT_MY_TEAM_KEYWORD = "knss"


def create_app(games_dir: str = DEFAULT_GAMES_DIR,
               my_team_keyword: str = DEFAULT_MY_TEAM_KEYWORD) -> Flask:
    app = Flask(__name__)

    app.config["GAMES_DIR"] = games_dir
    app.config["MY_TEAM_KEYWORD"] = my_team_keyword

    app.register_blueprint(home_bp)
    app.register_blueprint(game_bp)
    app.register_blueprint(season_bp)
    app.register_blueprint(career_bp)

    return app


# Module-level app object so `flask run` / gunicorn can still find it,
# using the defaults. `main()` below rebuilds it if --games-dir is passed.
app = create_app()


def main():
    parser = argparse.ArgumentParser(
        description="Simple local web UI for floorball stats."
    )

    parser.add_argument(
        "--games-dir",
        default=DEFAULT_GAMES_DIR,
        help="Folder with season subfolders",
    )

    parser.add_argument(
        "--port",
        type=int,
        default=5000,
    )

    args = parser.parse_args()

    application = create_app(games_dir=args.games_dir)

    application.run(
        debug=True,
        port=args.port,
    )


if __name__ == "__main__":
    main()
