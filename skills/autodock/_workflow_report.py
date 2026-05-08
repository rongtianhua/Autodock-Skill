"""
_workflow_report.py — HTML report generator for SnakeMake virtual screening workflow.

generate_html_report(df, output_path, top_n=20)
    df: DataFrame with at least columns:
          compound, best_affinity_kcal_mol [, mmpbsa_delta_g, clash_score]
"""

from __future__ import annotations
import os


def generate_html_report(
    df,
    output_path: str,
    top_n: int = 20,
    title: str = "Virtual Screening Results",
) -> None:
    """
    Generate an HTML summary report from a virtual screening results DataFrame.

    Parameters
    ----------
    df : pandas.DataFrame
        Must contain at least: ``compound``, ``best_affinity_kcal_mol``.
        Optional columns: ``mmpbsa_delta_g``, ``clash_score``, ``pre_dock_score``.
    output_path : str
        Path to write the HTML file.
    top_n : int
        Number of top-ranked results to show in the summary table.
    title : str
        Report title.
    """
    import pandas as pd

    # ── Sort and cap ─────────────────────────────────────────────────────────
    if df.empty:
        top = df
    elif "best_affinity_kcal_mol" in df.columns:
        df_sorted = df.dropna(subset=["best_affinity_kcal_mol"]).sort_values(
            "best_affinity_kcal_mol"
        )
        top = df_sorted.head(top_n)
    else:
        top = df.head(top_n)

    # ── Build table rows ──────────────────────────────────────────────────────
    rows = ""
    for rank, (_, row) in enumerate(top.iterrows(), 1):
        aff = row.get("best_affinity_kcal_mol")
        aff_str = f"{aff:.3f}" if aff is not None and not pd.isna(aff) else "N/A"

        mmpbsa = row.get("mmpbsa_delta_g")
        mmpbsa_str = (
            f"{mmpbsa:.3f}" if mmpbsa is not None and not pd.isna(mmpbsa) else "—"
        )

        clash = row.get("clash_score")
        clash_str = f"{clash:.2f}" if clash is not None and not pd.isna(clash) else "—"

        # Colour-code affinity
        if aff is not None and not pd.isna(aff):
            if aff < -10:
                aff_cls = "aff-great"
            elif aff < -8:
                aff_cls = "aff-good"
            elif aff < -6:
                aff_cls = "aff-moderate"
            else:
                aff_cls = "aff-weak"
        else:
            aff_cls = ""

        # 2D figure if available
        compound_name = str(row.get("compound", ""))
        fig_path = os.path.join(
            os.path.dirname(output_path), f"{compound_name}_2d.png"
        )
        fig_cell = (
            f'<img src="{compound_name}_2d.png" width="200" '
            f'alt="{compound_name}" title="{compound_name}" />'
            if os.path.exists(fig_path)
            else "—"
        )

        rows += f"""
        <tr>
          <td class="center">{rank}</td>
          <td><strong>{compound_name}</strong></td>
          <td class="{aff_cls} center">{aff_str}</td>
          <td class="center">{mmpbsa_str}</td>
          <td class="center">{clash_str}</td>
          <td class="center">{fig_cell}</td>
        </tr>"""

    # ── Summary statistics ────────────────────────────────────────────────────
    n_total = len(df)
    n_scored = (
        df["best_affinity_kcal_mol"].dropna().count()
        if "best_affinity_kcal_mol" in df.columns
        else 0
    )
    n_failed = n_total - n_scored

    aff_col = "best_affinity_kcal_mol"
    if aff_col in df.columns and n_scored > 0:
        mean_aff = df[aff_col].dropna().mean()
        min_aff = df[aff_col].dropna().min()
        max_aff = df[aff_col].dropna().max()
        stats_html = f"""
        <div class="stats">
          <div class="stat"><span class="label">Total compounds</span><span class="value">{n_total}</span></div>
          <div class="stat"><span class="label">Docked</span><span class="value">{n_scored}</span></div>
          <div class="stat"><span class="label">Failed</span><span class="value">{n_failed}</span></div>
          <div class="stat"><span class="label">Best ΔG</span><span class="value">{min_aff:.3f} kcal/mol</span></div>
          <div class="stat"><span class="label">Mean ΔG</span><span class="value">{mean_aff:.3f} kcal/mol</span></div>
          <div class="stat"><span class="label">Worst ΔG</span><span class="value">{max_aff:.3f} kcal/mol</span></div>
        </div>"""
    else:
        stats_html = f"""
        <div class="stats">
          <div class="stat"><span class="label">Total compounds</span><span class="value">{n_total}</span></div>
          <div class="stat"><span class="label">Docked</span><span class="value">{n_scored}</span></div>
          <div class="stat"><span class="label">Failed</span><span class="value">{n_failed}</span></div>
        </div>"""

    # ── Assemble HTML ─────────────────────────────────────────────────────────
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
          background: #f8f9fa; color: #212529; padding: 2rem; }}
  h1 {{ color: #1a237e; margin-bottom: 0.25rem; }}
  .subtitle {{ color: #555; margin-bottom: 1.5rem; font-size: 0.9rem; }}
  .stats {{ display: flex; flex-wrap: wrap; gap: 1rem; margin-bottom: 2rem; }}
  .stat {{ background: white; border: 1px solid #e0e0e0; border-radius: 8px;
           padding: 0.75rem 1.25rem; min-width: 120px; }}
  .stat .label {{ display: block; font-size: 0.75rem; color: #777; text-transform: uppercase;
                   letter-spacing: 0.05em; }}
  .stat .value {{ display: block; font-size: 1.25rem; font-weight: 700; color: #1a237e; }}
  table {{ width: 100%; border-collapse: collapse; background: white;
           border-radius: 8px; overflow: hidden; box-shadow: 0 2px 8px rgba(0,0,0,0.08); }}
  th {{ background: #1a237e; color: white; padding: 0.75rem 1rem;
         text-align: left; font-size: 0.85rem; text-transform: uppercase;
         letter-spacing: 0.05em; }}
  td {{ padding: 0.6rem 1rem; border-bottom: 1px solid #f0f0f0; font-size: 0.9rem; }}
  tr:last-child td {{ border-bottom: none; }}
  tr:hover td {{ background: #f5f5ff; }}
  .center {{ text-align: center; }}
  .aff-great  {{ color: #1b5e20; font-weight: 700; }}
  .aff-good   {{ color: #2e7d32; }}
  .aff-moderate {{ color: #f57f17; }}
  .aff-weak   {{ color: #c62828; }}
  img {{ border-radius: 4px; vertical-align: middle; }}
  .legend {{ margin-bottom: 1rem; font-size: 0.8rem; color: #666; }}
  .legend span {{ display: inline-block; margin-right: 1rem; }}
  .dot {{ display: inline-block; width: 10px; height: 10px;
          border-radius: 50%; margin-right: 4px; vertical-align: middle; }}
</style>
</head>
<body>
<h1>{title}</h1>
<p class="subtitle">Generated by autodock SnakeMake workflow</p>

{stats_html}

<p class="legend">
  <span><span class="dot" style="background:#1b5e20"></span>ΔG &lt; −10 (strong)</span>
  <span><span class="dot" style="background:#2e7d32"></span>ΔG &lt; −8 (good)</span>
  <span><span class="dot" style="background:#f57f17"></span>ΔG &lt; −6 (moderate)</span>
  <span><span class="dot" style="background:#c62828"></span>ΔG ≥ −6 (weak)</span>
</p>

<table>
  <thead>
    <tr>
      <th class="center">#</th>
      <th>Compound</th>
      <th class="center">Vina ΔG (kcal/mol)</th>
      <th class="center">MM/PBSA ΔG</th>
      <th class="center">Clash</th>
      <th class="center">2D Interaction</th>
    </tr>
  </thead>
  <tbody>
    {rows}
  </tbody>
</table>
</body>
</html>"""

    with open(output_path, "w", encoding="utf-8") as fh:
        fh.write(html)


# ── CLI helper ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import pandas as pd
    import sys

    if len(sys.argv) < 3:
        print("Usage: python _workflow_report.py <results.csv> <output.html>")
        sys.exit(1)

    df = pd.read_csv(sys.argv[1])
    generate_html_report(df, sys.argv[2])
    print(f"Report written: {sys.argv[2]}")
