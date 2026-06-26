"""Rendering for the leaderboard: a CLI table and a standalone HTML report.

The HTML report embeds its data and pulls Chart.js from a CDN, so it needs no
build step and no extra Python packages — just open the file in a browser.
"""
import json

from crossplay.leaderboard import Leaderboard

_COLS = ("#", "Agent", "Rating", "Games", "W-L-T", "Win%", "AvgScore", "Margin")


def render_standings(board: Leaderboard) -> str:
    rows = [_COLS]
    for i, (name, rec) in enumerate(board.standings(), 1):
        rows.append((
            str(i), name, f"{rec.rating:.0f}", str(rec.games),
            f"{rec.wins}-{rec.losses}-{rec.ties}",
            f"{rec.winrate * 100:.1f}", f"{rec.avg_score:.1f}",
            f"{rec.avg_margin:+.1f}",
        ))
    widths = [max(len(r[c]) for r in rows) for c in range(len(_COLS))]
    lines = []
    for ri, row in enumerate(rows):
        lines.append("  ".join(cell.ljust(widths[c]) for c, cell in enumerate(row)))
        if ri == 0:
            lines.append("  ".join("-" * widths[c] for c in range(len(_COLS))))
    return "Leaderboard\n" + "\n".join(lines)


def _series_by_agent(history: list[dict], key: str) -> dict[str, list]:
    series: dict[str, list] = {}
    for point in history:
        series.setdefault(point["agent"], []).append(point.get(key))
    return series


def render_html_report(board: Leaderboard) -> str:
    """Return the standalone HTML leaderboard report as a string."""
    standings = [
        {"rank": i, "agent": name, "rating": round(rec.rating, 1), "games": rec.games,
         "record": f"{rec.wins}-{rec.losses}-{rec.ties}",
         "winrate": round(rec.winrate * 100, 1), "avg_score": round(rec.avg_score, 1),
         "margin": round(rec.avg_margin, 1)}
        for i, (name, rec) in enumerate(board.standings(), 1)
    ]
    data = {
        "standings": standings,
        "rating": _series_by_agent(board.history, "rating"),
        "winrate": _series_by_agent(board.history, "winrate"),
        "avg_score": _series_by_agent(board.history, "avg_score"),
    }
    return _HTML_TEMPLATE.replace("__DATA__", json.dumps(data))


def write_html_report(board: Leaderboard, path: str) -> None:
    with open(path, "w") as f:
        f.write(render_html_report(board))


_HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Crossplay Leaderboard</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<style>
  body { font-family: -apple-system, system-ui, sans-serif; margin: 2rem; color: #1a1a1a; }
  h1 { margin-bottom: .25rem; } .sub { color: #777; margin-top: 0; }
  table { border-collapse: collapse; margin: 1rem 0 2rem; }
  th, td { padding: .4rem .8rem; border-bottom: 1px solid #ddd; text-align: right; }
  th:nth-child(2), td:nth-child(2) { text-align: left; }
  th { background: #f5f5f5; } tr:first-child td { font-weight: 600; }
  .chart { max-width: 760px; margin: 1.5rem 0; }
</style>
</head>
<body>
<h1>Crossplay Leaderboard</h1>
<p class="sub">Self-play standings and progress over time.</p>
<div id="standings"></div>
<div class="chart"><canvas id="ratingChart"></canvas></div>
<div class="chart"><canvas id="winrateChart"></canvas></div>
<div class="chart"><canvas id="scoreChart"></canvas></div>
<script>
const DATA = __DATA__;

function table(rows) {
  if (!rows.length) return "<p>No games recorded yet.</p>";
  const head = "<tr><th>#</th><th>Agent</th><th>Rating</th><th>Games</th>" +
               "<th>W-L-T</th><th>Win%</th><th>Avg Score</th><th>Margin</th></tr>";
  const body = rows.map(r =>
    `<tr><td>${r.rank}</td><td>${r.agent}</td><td>${r.rating}</td><td>${r.games}</td>` +
    `<td>${r.record}</td><td>${r.winrate}</td><td>${r.avg_score}</td><td>${r.margin}</td></tr>`
  ).join("");
  return `<table>${head}${body}</table>`;
}
document.getElementById("standings").innerHTML = table(DATA.standings);

const palette = ["#2563eb","#dc2626","#16a34a","#9333ea","#ea580c","#0891b2"];
function lineChart(canvasId, seriesMap, title) {
  const agents = Object.keys(seriesMap);
  const maxLen = Math.max(0, ...agents.map(a => seriesMap[a].length));
  const labels = Array.from({length: maxLen}, (_, i) => i + 1);
  const datasets = agents.map((a, i) => ({
    label: a, data: seriesMap[a], borderColor: palette[i % palette.length],
    backgroundColor: palette[i % palette.length], tension: .2, fill: false,
  }));
  new Chart(document.getElementById(canvasId), {
    type: "line",
    data: { labels, datasets },
    options: { plugins: { title: { display: true, text: title } },
               scales: { x: { title: { display: true, text: "snapshot" } } } },
  });
}
lineChart("ratingChart", DATA.rating, "Elo rating over time");
lineChart("winrateChart", DATA.winrate, "Win rate over time");
lineChart("scoreChart", DATA.avg_score, "Average score over time");
</script>
</body>
</html>
"""
