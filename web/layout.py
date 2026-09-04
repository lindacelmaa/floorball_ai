"""
Shared HTML layout helpers used by every route module.

Nothing in here talks to the filesystem or to the analysis modules -
it only knows how to turn plain Python values into HTML strings.
"""

import html


CSS = """
body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif;
    max-width: 1200px;
    margin: 30px auto;
    padding: 0 16px;
    color: #1a1a1a;
    background: #fafafa;
}

h1, h2, h3 {
    color: #111;
}

h2 {
    margin-top: 0;
}

a {
    color: #1a5fb4;
    text-decoration: none;
}

a:hover {
    text-decoration: underline;
}

nav {
    margin-bottom: 24px;
    padding-bottom: 12px;
    border-bottom: 2px solid #ddd;
}

nav a {
    margin-right: 16px;
    font-weight: 600;
}

table {
    border-collapse: collapse;
    width: 100%;
    margin: 12px 0 24px 0;
    background: white;
}

th, td {
    border: 1px solid #ddd;
    padding: 7px 10px;
    text-align: left;
    font-size: 14px;
    vertical-align: top;
}

th {
    background: #eee;
}

section {
    background: white;
    border: 1px solid #ddd;
    border-radius: 8px;
    padding: 18px 20px;
    margin-bottom: 20px;
}

.score {
    font-size: 22px;
    font-weight: 700;
}

.muted {
    color: #777;
    font-size: 13px;
}

.small {
    font-size: 12px;
}

.good {
    font-weight: 700;
}

.bad {
    font-weight: 700;
}

.cards {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
    gap: 12px;
    margin: 12px 0 20px 0;
}

.card {
    background: white;
    border: 1px solid #ddd;
    border-radius: 8px;
    padding: 14px;
}

.card .value {
    font-size: 24px;
    font-weight: 700;
    margin-top: 4px;
}

.card .label {
    color: #777;
    font-size: 12px;
}

.two-col {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 20px;
}

@media (max-width: 800px) {
    .two-col {
        grid-template-columns: 1fr;
    }

    table {
        display: block;
        overflow-x: auto;
    }
}

details {
    margin: 10px 0;
}

summary {
    cursor: pointer;
    font-weight: 600;
}

ul.games-list {
    list-style: none;
    padding: 0;
}

ul.games-list li {
    padding: 5px 0;
}

.note {
    background: #f5f5f5;
    border-left: 4px solid #bbb;
    padding: 10px 12px;
    margin: 10px 0;
}
"""


def esc(value):
    if value is None:
        return "N/A"

    return html.escape(str(value))


def fmt_pct(value):
    if value is None:
        return "N/A"

    return f"{value}%"


def fmt_signed(value):
    if value is None:
        return "N/A"

    return f"{value:+}"


def page(title: str, body: str) -> str:
    return f"""<!doctype html>
<html>
<head>
    <meta charset="utf-8">
    <title>{esc(title)}</title>
    <style>{CSS}</style>
</head>
<body>
    <nav>
        <a href="/">Home</a>
        <a href="/game-stats">Game Stats</a>
        <a href="/season-stats">Season Stats</a>
        <a href="/career">Career (all seasons)</a>
    </nav>

    <h1>{esc(title)}</h1>

    {body}
</body>
</html>"""


def table(headers: list, rows: list, row_teams: list = None, max_rows: int = None,) -> str:
    if not rows:
        return "<p class='muted'>No data available.</p>"

    head = "".join(
        f"<th>{esc(h)}</th>"
        for h in headers
    )

    body_rows = ""

    for i, row in enumerate(rows):
        attrs = ""

        if row_teams:
            team_value = (
                row_teams[i]
                if i < len(row_teams)
                else ""
            )

            attrs += (
                f' data-team="{esc(team_value)}"'
            )

        attrs += f' data-rank="{i}"'

        if max_rows is not None and i >= max_rows:
            attrs += ' style="display:none;"'

        cells = "".join(
            f"<td>{c}</td>"
            for c in row
        )

        body_rows += (
            f"<tr{attrs}>{cells}</tr>"
        )

    return (
        f"<table>"
        f"<tr>{head}</tr>"
        f"{body_rows}"
        f"</table>"
    )


def section(title, content):
    return (
        f"<section>"
        f"<h2>{title}</h2>"
        f"{content}"
        f"</section>"
    )


def subsection(title, content):
    return (
        f"<details>"
        f"<summary>{title}</summary>"
        f"{content}"
        f"</details>"
    )


def knss_filter_ui(my_team_keyword: str, team_display_name: str = None) -> str:
    """Checkbox that filters every stats table down to rows belonging to the
    active team. `team_display_name` drives the visible label so it stays
    correct after switching teams in Settings; `my_team_keyword` drives the
    actual matching logic (same as before)."""
    keyword = my_team_keyword.lower()
    label = team_display_name or my_team_keyword

    return f"""
<label style="display:inline-block; margin-bottom:12px;">
    <input
        type="checkbox"
        onchange="toggleKnssFilter(this)"
    >
    Show only {esc(label)}
</label>

<script>
function toggleKnssFilter(cb) {{
    var only = cb.checked;
    var keyword = '{keyword}';
    var maxRows = 40;

    /*
     * Tables:
     *
     * Filter by team first, then show the first 40
     * matching rows.
     */
    document.querySelectorAll('table').forEach(function(table) {{
        var rows = Array.from(
            table.querySelectorAll('tr[data-team]')
        );

        var visibleCount = 0;

        rows.forEach(function(row) {{
            var team = (
                row.getAttribute('data-team') || ''
            ).toLowerCase();

            var matches = (
                !only ||
                team.includes(keyword)
            );

            if (matches && visibleCount < maxRows) {{
                row.style.display = '';
                visibleCount++;
            }} else {{
                row.style.display = 'none';
            }}
        }});
    }});

    /*
     * Player dropdowns:
     * Show/hide the whole player <details>.
     */
    document.querySelectorAll('details[data-team]').forEach(
        function(details) {{
            var team = (
                details.getAttribute('data-team') || ''
            ).toLowerCase();

            details.style.display =
                (!only || team.includes(keyword))
                ? ''
                : 'none';
        }}
    );
}}
</script>
"""