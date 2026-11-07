"""All static figures: galaxy (poster + paper), group trees, and the paper's charts.

Paper figures are drawn at their printed width (6.5 in) so fonts print at their nominal size, carry no
watermark, and are checked for overlapping text before saving (results/figure_qa.csv).
"""
from __future__ import annotations

import math
import re

import matplotlib

matplotlib.use("Agg")
import matplotlib.colors as mcolors  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib import font_manager  # noqa: E402
from matplotlib.collections import LineCollection  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402
from matplotlib.ticker import MaxNLocator, PercentFormatter  # noqa: E402

from .analyze import UO_ORDER  # noqa: E402
from .names import short_company_name  # noqa: E402
from .utils import LOG, ensure_dir, write_csv  # noqa: E402
from .viz_galaxy import edge_segments, galaxy  # noqa: E402
from .viz_layout import (GT_LABEL, IND, IND_LABEL, THEMES, compute_layout, load, node_category,  # noqa: E402
                         node_weights, text_overlaps)

INK, GRAY = "#1B2133", "#8C94A8"
CHART = {"axes.spines.top": False, "axes.spines.right": False, "axes.edgecolor": GRAY, "axes.labelcolor": INK,
         "xtick.color": "#3A4256", "ytick.color": "#3A4256", "font.size": 7.5, "axes.titlesize": 8.5,
         "axes.titleweight": "bold", "axes.titlelocation": "left", "axes.labelsize": 7.5, "xtick.labelsize": 7,
         "ytick.labelsize": 7, "legend.fontsize": 6.8, "legend.frameon": False, "axes.grid": True,
         "grid.color": "#E6E9F1", "grid.linewidth": 0.6}


def setup_fonts() -> None:
    avail = {f.name for f in font_manager.fontManager.ttflist}
    latin = next((f for f in ["Inter", "IBM Plex Sans", "Source Sans 3", "Source Sans Pro", "Lato", "Fira Sans",
                              "Open Sans", "Liberation Sans", "DejaVu Sans"] if f in avail), "DejaVu Sans")
    thai = next((f for f in ["Noto Sans Thai", "Sarabun", "TH Sarabun New", "Leelawadee UI", "Tahoma", "Loma",
                             "Garuda", "Norasi", "Kinnari"] if f in avail), None)
    plt.rcParams["font.family"] = [latin] + ([thai] if thai else [])  # per-glyph fallback for Thai names
    plt.rcParams["pdf.fonttype"] = 42
    plt.rcParams["axes.unicode_minus"] = False


def _save(fig, out, dpi=300) -> list:
    bad = text_overlaps(fig)
    if bad:
        LOG.warning("%s: %d overlapping text pairs, e.g. %s", out.name, len(bad), bad[:3])
    fig.savefig(out, dpi=dpi, bbox_inches="tight", pad_inches=0.03, facecolor="white")
    plt.close(fig)
    return bad


def _placeholder(out, text) -> list:
    fig, ax = plt.subplots(figsize=(6.5, 1.2))
    ax.axis("off")
    ax.text(0.5, 0.5, text, ha="center", va="center", color="#5E6780", fontsize=8)
    return _save(fig, out)


def _ink(color) -> str:
    r, g, b = mcolors.to_rgb(color)
    return "white" if 0.2126 * r + 0.7152 * g + 0.0722 * b < 0.55 else INK


def _clip(s, n) -> str:
    s = str(s)
    return s if len(s) <= n else s[: n - 1].rstrip(" (,") + "…"


def _listed(U, t):
    return U[(U["threshold"] == t) & U["firm"].astype(str).str.startswith("L:")]


def spread_1d(targets, dy, lo, hi) -> np.ndarray:
    """Move label positions apart so neighbours are at least dy apart, staying inside [lo, hi]."""
    t = np.asarray(targets, float)
    n = len(t)
    if n == 0:
        return t
    dy = min(dy, (hi - lo) / max(n - 1, 1))
    order = np.argsort(t)
    y = np.clip(t[order], lo, hi)
    for i in range(1, n):
        y[i] = max(y[i], y[i - 1] + dy)
    if y[-1] > hi:
        y[-1] = hi
        for i in range(n - 2, -1, -1):
            y[i] = min(y[i], y[i + 1] - dy)
    out = np.empty(n)
    out[order] = y
    return out


def group_tree(D, N, Gl, gid, out, max_labels=40) -> list:
    """Radial control tree of one group; listed firms labelled in two side columns with leader lines."""
    th = THEMES["light"]
    g = Gl[Gl["group_id"] == gid].iloc[0]
    sub = N[N["group_id"] == gid].reset_index(drop=True).copy()
    for c, o in (("x", g["x"]), ("cx", g["x"]), ("y", g["y"]), ("cy", g["y"])):
        sub[c] = (sub[c] - o) / g["r"]
    cat, w = node_category(sub), node_weights(sub, Gl)
    present = [c for c in IND if c in set(sub["industry"])]
    W_IN, XL, YL = 6.5, 2.1, 1.3
    ax_h, rows2 = W_IN * YL / XL, math.ceil(len(present) / 5)
    bot, top = 0.12 + 0.17 * rows2 + 0.26, 0.58
    H = ax_h + bot + top
    fig = plt.figure(figsize=(W_IN, H))
    ax = fig.add_axes([0, bot / H, 1, ax_h / H])
    icol = np.array([mcolors.to_rgba(th["ind"].get(i, th["ind"]["OTHER"])) for i in sub["industry"]])
    segs, sel = edge_segments(sub, 14)
    ecol = icol[sel].copy()
    ecol[:, 3] = 0.5
    ax.add_collection(LineCollection(segs, colors=ecol, linewidths=0.55, zorder=1))
    sz = w * (9 if len(sub) < 150 else 4.5)
    xs, ys = sub["x"].to_numpy(), sub["y"].to_numpy()
    m = cat == "private"
    ax.scatter(xs[m], ys[m], s=sz[m], c=icol[m], edgecolors="white", linewidths=0.25, zorder=3)
    m = cat == "foreign"
    ax.scatter(xs[m], ys[m], s=sz[m], facecolors="white", edgecolors=icol[m], linewidths=0.7, zorder=3)
    m = cat == "holding"
    ax.scatter(xs[m], ys[m], s=sz[m] * 1.4, marker="s", c=icol[m], edgecolors=INK, linewidths=0.5, zorder=3.5)
    m = cat == "listed"
    ax.scatter(xs[m], ys[m], s=sz[m], c=icol[m], edgecolors=INK, linewidths=0.7, zorder=4)
    a = cat == "apex"
    gcol = th["gt"].get(g["group_type"], th["gt"]["unknown"])
    ax.scatter(xs[a], ys[a], s=sz[a] * 1.2, c=gcol, edgecolors=INK, linewidths=0.9, zorder=5)
    lab = sub[cat == "listed"].assign(mc=lambda d: pd.to_numeric(d["mcap"], errors="coerce").fillna(0))
    lab = lab.sort_values("mc", ascending=False).head(max_labels)
    fs = 6.5
    dy = 1.5 * fs / 72 * (2 * XL / W_IN)
    for side in (1, -1):
        s = lab[(lab["x"] >= 0) if side > 0 else (lab["x"] < 0)]
        if s.empty:
            continue
        yl = spread_1d(s["y"].to_numpy(), dy, -YL + 0.08, YL - 0.08)
        for (x, y, tk, nm), ylab in zip(s[["x", "y", "ticker", "name"]].itertuples(index=False), yl):
            ax.plot([x, side * 1.0, side * 1.05], [y, ylab, ylab], color="#A3ABBD", lw=0.5, zorder=2)
            ax.text(side * 1.07, ylab, f"{tk}  {short_company_name(nm, 26)}", ha="left" if side > 0 else "right",
                    va="center", fontsize=fs, color=INK, zorder=6)
    ax.set_xlim(-XL, XL)
    ax.set_ylim(-YL, YL)
    ax.set_aspect("equal")
    ax.axis("off")
    apex = sub.loc[a, "name"].iloc[0] if a.any() else g.get("apex_name", "")
    fig.text(0.5, 1 - 0.1 / H, str(g["label"]), ha="center", va="top", fontsize=10, fontweight="bold", color=INK)
    depth = int(g["max_depth"]) if pd.notna(g["max_depth"]) else 0
    fig.text(0.5, 1 - 0.34 / H, f"{int(g['n_firms'])} firms, {int(g['n_listed'])} listed, up to {depth} ownership "
             f"links. Ultimate owner: {short_company_name(apex, 34)} "
             f"({GT_LABEL.get(g['group_type'], g['group_type']).lower()})", ha="center", va="top", fontsize=7,
             color=th["muted"])
    kinds = [("apex", "Ultimate owner", "o", gcol, INK), ("listed", "Listed company", "o", GRAY, INK),
             ("holding", "Holding company", "s", GRAY, INK), ("private", "Unlisted company", "o", GRAY, "white"),
             ("foreign", "Registered abroad", "o", "white", GRAY)]
    h1 = [Line2D([], [], marker=mk, ls="none", ms=5.5, mfc=fc, mec=ec, mew=0.8, label=lb)
          for k, lb, mk, fc, ec in kinds if (cat == k).any()]
    h2 = [Line2D([], [], marker="o", ls="none", ms=4.5, color=th["ind"][c], label=IND_LABEL[c]) for c in present]
    kw = dict(loc="lower center", fontsize=6.5, frameon=False, handletextpad=0.2, columnspacing=1.4)
    fig.legend(handles=h2, bbox_to_anchor=(0.5, 0.06 / H), ncol=min(len(h2), 5) or 1, **kw)
    fig.legend(handles=h1, bbox_to_anchor=(0.5, (0.12 + 0.17 * rows2) / H), ncol=len(h1) or 1, **kw)
    return _save(fig, out)


def fig_uo(D, cfg, out) -> list:
    U, th = D["U"], THEMES["light"]
    mcap = D["E"].set_index("id")["market_cap"]
    bars, labels = [], []
    for t in cfg["ownership"]["thresholds"]:
        bars.append(_listed(U, t)["uo_type"].value_counts(normalize=True))
        labels.append(f"{round(t * 100)}% threshold")
    t = cfg["ownership"]["group_threshold"]
    u = _listed(U, t)
    wv = u.assign(m=u["firm"].map(mcap).fillna(0)).groupby("uo_type")["m"].sum()
    bars.append(wv / wv.sum() if wv.sum() > 0 else wv)
    labels.append(f"{round(t * 100)}%, by market value")
    types = [x for x in UO_ORDER if any(x in b.index for b in bars)]
    with plt.rc_context(CHART):
        fig, ax = plt.subplots(figsize=(6.5, 2.6))
        for i, b in enumerate(bars):
            left = 0.0
            for ty in types:
                v, col = float(b.get(ty, 0)), th["gt"].get(ty, th["gt"]["unknown"])
                ax.barh(i, v, left=left, height=0.62, color=col, edgecolor="white", linewidth=0.6)
                if v >= 0.07:
                    ax.text(left + v / 2, i, f"{v * 100:.0f}%", ha="center", va="center", fontsize=6.8, color=_ink(col))
                left += v
        ax.set_yticks(range(len(bars)), labels)
        ax.invert_yaxis()
        ax.set_xlim(0, 1)
        ax.xaxis.set_major_formatter(PercentFormatter(1.0, decimals=0))
        ax.grid(axis="y", visible=False)
        ax.set_xlabel("Share of listed firms (last bar: share of market value)")
        fig.tight_layout(rect=(0, 0.2, 1, 1))
        fig.legend(handles=[Patch(color=th["gt"].get(x, GRAY), label=GT_LABEL.get(x, x)) for x in types],
                   loc="lower center", bbox_to_anchor=(0.5, 0.0), ncol=4, handlelength=1.2, columnspacing=1.4)
        return _save(fig, out)


def fig_groups(D, out) -> list:
    G, th = D["G"], THEMES["light"]
    g = G.sort_values("n_firms", ascending=False).reset_index(drop=True)
    present = [x for x in UO_ORDER if x in set(g["group_type"])]
    with plt.rc_context(CHART):
        fig, (a1, a2) = plt.subplots(1, 2, figsize=(6.5, 2.9), gridspec_kw={"width_ratios": [1.3, 1]})
        a1.scatter(np.arange(1, len(g) + 1), g["n_firms"], s=7, linewidths=0, alpha=0.9,
                   c=[th["gt"].get(x, th["gt"]["unknown"]) for x in g["group_type"]])
        a1.set(xscale="log", yscale="log", xlabel="Rank of group by number of firms", ylabel="Firms in group")
        a1.set_title("(a) Size distribution of groups")
        dc = G[G["n_firms"] >= 3]["max_depth"].fillna(0).astype(int).value_counts().sort_index()
        a2.bar(dc.index, dc.values, color=th["ind"]["INDUS"], width=0.7)
        a2.xaxis.set_major_locator(MaxNLocator(integer=True))
        a2.set(xlabel="Longest ownership chain in the group (links)", ylabel="Groups with 3 or more firms")
        a2.set_title("(b) Depth of group trees")
        fig.tight_layout(rect=(0, 0.2, 1, 1), w_pad=2.0)
        fig.legend(handles=[Line2D([], [], marker="o", ls="none", ms=4.5, color=th["gt"].get(x, GRAY),
                                   label=GT_LABEL.get(x, x)) for x in present],
                   loc="lower center", bbox_to_anchor=(0.5, 0.0), ncol=3, handletextpad=0.2, columnspacing=1.4,
                   title="Colour of points in (a): type of ultimate owner", title_fontsize=6.8)
        return _save(fig, out)


def fig_wedge(D, cfg, out) -> list:
    U, th = D["U"], THEMES["light"]
    t = cfg["ownership"]["group_threshold"]
    u = U[(U["threshold"] == t) & U["uo_id"].notna()]
    L = u[u["firm"].astype(str).str.startswith("L:")]
    with plt.rc_context(CHART):
        fig, (a1, a2) = plt.subplots(1, 2, figsize=(6.5, 2.9))
        for ty in [x for x in UO_ORDER if x in set(L["uo_type"])]:
            grp = L[L["uo_type"] == ty]
            a1.scatter(grp["cf"] * 100, grp["cr"] * 100, s=7, alpha=0.8, color=th["gt"].get(ty, GRAY),
                       linewidths=0, label=GT_LABEL.get(ty, ty))
        a1.plot([0, 100], [0, 100], color="#9AA3B5", lw=0.8, ls="--", zorder=0)
        a1.set(xlim=(0, 100), ylim=(0, 100), xlabel="Cash-flow rights (%)", ylabel="Control rights (%)")
        a1.set_title("(a) Control vs. cash-flow rights")
        a1.legend(loc="lower right", fontsize=6, markerscale=1.3, handletextpad=0.2, labelspacing=0.3,
                  borderaxespad=0.3)   # empty corner: control rights are never below cash-flow rights
        d = u.dropna(subset=["depth"])
        d = d.assign(kind=np.where(d["firm"].astype(str).str.startswith("L:"), "Listed firms", "Unlisted firms"))
        tab = d.groupby(["depth", "kind"]).size().unstack(fill_value=0)
        x = tab.index.astype(int).to_numpy()
        for j, (k, col) in enumerate([("Listed firms", th["ind"]["FINCIAL"]), ("Unlisted firms", th["ind"]["INDUS"])]):
            if k in tab:
                a2.bar(x + (j - 0.5) * 0.38, tab[k].to_numpy(), width=0.38, label=k, color=col)
        a2.set_yscale("log")
        if len(tab):
            a2.set_ylim(0.7, float(tab.to_numpy().max()) * 15)   # free band at the top for the legend
        a2.xaxis.set_major_locator(MaxNLocator(integer=True))
        a2.set(xlabel="Ownership links to the ultimate owner", ylabel="Firms (log scale)")
        a2.set_title("(b) Length of control chains")
        a2.legend(loc="upper right", ncol=2)
        fig.tight_layout(w_pad=2.0)
        return _save(fig, out)


def fig_nexus(D, out, top=14) -> list:
    Nx = D["N"]
    if Nx is None or Nx.empty:
        return _placeholder(out, "No links between bank groups and business groups in the current data.")
    Nx = Nx.fillna({"bank_label": "?", "group_label": "?"})
    banks = Nx.groupby("bank_label")["total"].sum().sort_values(ascending=False).index[:8]
    cols = Nx[Nx["bank_label"].isin(banks)].groupby("group_label")["total"].sum().sort_values(ascending=False).index[:top]
    arr = Nx.pivot_table(index="bank_label", columns="group_label", values="total", aggfunc="sum",
                         fill_value=0).reindex(index=banks, columns=cols, fill_value=0).to_numpy(dtype=float)
    with plt.rc_context({**CHART, "axes.grid": False}):
        fig, ax = plt.subplots(figsize=(6.5, 0.3 * len(banks) + 1.9))
        ax.imshow(arr, cmap=LinearSegmentedColormap.from_list("nx", ["#F3F5FA", "#7C8FE6", "#1B2A7A"]),
                  aspect="auto", vmin=0)
        vmax = arr.max() or 1.0
        for i in range(arr.shape[0]):
            for j in range(arr.shape[1]):
                if arr[i, j]:
                    ax.text(j, i, str(int(arr[i, j])), ha="center", va="center", fontsize=6.5,
                            color="white" if arr[i, j] > 0.55 * vmax else INK)
        ax.set_xticks(range(len(cols)), [_clip(c, 24) for c in cols], rotation=90, ha="center", va="top",
                      fontsize=6.5)
        ax.set_yticks(range(len(banks)), [_clip(b, 30) for b in banks], fontsize=6.8)
        ax.tick_params(length=0)
        for sp in ax.spines.values():
            sp.set_visible(False)
        ax.set_xlabel("Business group (links: ownership, shared directors and fund holdings)")
        ax.set_ylabel("Bank group")
        return _save(fig, out)


def all_figures(cfg, synthetic=False):
    setup_fonts()
    D = load(cfg)
    if D["G"].empty:
        LOG.error("no results yet: run `python -m tbg analyze` first")
        return
    P, vz = cfg["_paths"], cfg["viz"]
    F = ensure_dir(P["figures"])
    N, Gl = compute_layout(D, cfg)
    write_csv(N, P["results"] / "layout_nodes.csv")
    write_csv(Gl, P["results"] / "layout_groups.csv")
    LOG.info("layout: %d nodes in %d groups", len(N), len(Gl))
    galaxy(D, N, Gl, cfg, "dark", F / "galaxy_poster_dark", synthetic, True, vz["poster_inches"], vz["dpi"],
           vz["label_top_groups"], ("png", "pdf"))
    galaxy(D, N, Gl, cfg, "light", F / "galaxy_poster_light", synthetic, True, vz["poster_inches"], vz["dpi"],
           vz["label_top_groups"])
    qa = {"galaxy_paper.png": galaxy(D, N, Gl, cfg, "light", F / "galaxy_paper", synthetic, False,
                                     vz["paper_inches"], vz["dpi"], 15, check=True)}
    T = ensure_dir(F / "groups")
    for i, r in enumerate(Gl.sort_values("rank").head(12).itertuples()):
        slug = re.sub(r"[^A-Za-z0-9]+", "_", str(r.label)).strip("_")[:40] or "group"
        group_tree(D, N, Gl, r.group_id, T / f"{int(r.rank):02d}_{slug}.png")
        if i == 0:
            qa["tree_top.pdf"] = group_tree(D, N, Gl, r.group_id, F / "tree_top.pdf")
    qa["fig_uo.pdf"] = fig_uo(D, cfg, F / "fig_uo.pdf")
    qa["fig_groups.pdf"] = fig_groups(D, F / "fig_groups.pdf")
    qa["fig_wedge.pdf"] = fig_wedge(D, cfg, F / "fig_wedge.pdf")
    qa["fig_nexus.pdf"] = fig_nexus(D, F / "fig_nexus.pdf")
    write_csv(pd.DataFrame([dict(figure=k, overlapping_text_pairs=len(v),
                                 examples="; ".join(" / ".join(p) for p in v[:5])) for k, v in qa.items()]),
              P["results"] / "figure_qa.csv")
    LOG.info("figures written to %s; overlapping text pairs in paper figures: %d", F,
             sum(len(v) for v in qa.values()))
