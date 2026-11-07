"""The galaxy figure: every business group as a constellation of firms."""
from __future__ import annotations

import math
import textwrap

import matplotlib

matplotlib.use("Agg")
import matplotlib.colors as mcolors  # noqa: E402
import matplotlib.patheffects as pe  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.collections import LineCollection, PatchCollection  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.patches import Circle  # noqa: E402

from .viz_layout import GT_LABEL, GT_ORDER, IND, IND_LABEL, THEMES, node_category, node_weights, text_overlaps  # noqa: E402


def bezier(p0, p1, p2, n=9) -> np.ndarray:
    t = np.linspace(0, 1, n)[:, None]
    p0, p1, p2 = (np.asarray(p, float) for p in (p0, p1, p2))
    return (1 - t) ** 2 * p0 + 2 * (1 - t) * t * p1 + t ** 2 * p2


def edge_segments(N, n=9) -> tuple[np.ndarray, np.ndarray]:
    idx = {v: i for i, v in enumerate(N["id"])}
    pi = np.array([idx.get(p, -1) for p in N["parent"].fillna("").astype(str)])
    sel = pi >= 0
    xs, ys = N["x"].to_numpy(float), N["y"].to_numpy(float)
    t = np.linspace(0, 1, n)[None, :, None]
    P0 = np.stack([xs[pi[sel]], ys[pi[sel]]], axis=1)[:, None, :]
    P1 = np.stack([N["cx"].to_numpy(float)[sel], N["cy"].to_numpy(float)[sel]], axis=1)[:, None, :]
    P2 = np.stack([xs[sel], ys[sel]], axis=1)[:, None, :]
    return (1 - t) ** 2 * P0 + 2 * (1 - t) * t * P1 + t ** 2 * P2, sel


def _backdrop(ax, th, lim, area):
    n = 400
    yy, xx = np.mgrid[-lim:lim:n * 1j, -lim:lim:n * 1j]
    rr = np.clip(np.hypot(xx, yy) / (lim * 1.05), 0, 1) ** 1.3
    c0, c1 = np.array(mcolors.to_rgb(th["bg2"])), np.array(mcolors.to_rgb(th["bg"]))
    ax.imshow(c0 * (1 - rr[..., None]) + c1 * rr[..., None], extent=(-lim, lim, -lim, lim), origin="lower",
              zorder=0, interpolation="bilinear")
    rng = np.random.default_rng(7)
    k = 1600
    ax.scatter(rng.uniform(-lim, lim, k), rng.uniform(-lim, lim, k), s=rng.uniform(0.05, 0.9, k) * area * 2,
               c=th["fg"], alpha=0.2, linewidths=0, zorder=0.5)


def _ties(ax, T, gpos, th, ks, k=250):
    if T is None or T.empty:
        return
    tt = T[T["g1"].isin(gpos) & T["g2"].isin(gpos)].sort_values("weight", ascending=False).head(k)
    if tt.empty:
        return
    wmax = float(tt["weight"].max()) or 1.0
    segs, cols, lws = [], [], []
    for a, b, own, w in tt[["g1", "g2", "ownership", "weight"]].itertuples(index=False):
        (x1, y1, _), (x2, y2, _) = gpos[a], gpos[b]
        segs.append(bezier((x1, y1), ((x1 + x2) * 0.3, (y1 + y2) * 0.3), (x2, y2), 28))
        f = (float(w) / wmax) ** 0.5
        cols.append(mcolors.to_rgba(th["tie_own"] if own > 0 else th["tie_dir"], 0.10 + 0.32 * f))
        lws.append((0.35 + 1.5 * f) * ks)
    ax.add_collection(LineCollection(segs, colors=cols, linewidths=lws, zorder=1.5, capstyle="round"))


def _clip(s, n):
    s = str(s)
    return s if len(s) <= n else s[: n - 1] + "…"


def galaxy(D, N, Gl, cfg, theme, out_base, synthetic, panel=True, inches=24.0, dpi=300, top_n=40,
           formats=("png",), check=False):
    th = THEMES[theme]
    # crop to the packed circles so no space is wasted
    x0b, x1b = float((Gl["x"] - Gl["r"]).min()), float((Gl["x"] + Gl["r"]).max())
    y0b, y1b = float((Gl["y"] - Gl["r"]).min()), float((Gl["y"] + Gl["r"]).max())
    pad = 0.03 * max(x1b - x0b, y1b - y0b)
    x0b, x1b, y0b, y1b = x0b - pad, x1b + pad, y0b - pad, y1b + pad
    if panel:
        W, Hh = inches, inches * 0.6875
        side = Hh
        half = max(x1b - x0b, y1b - y0b) / 2
        cxm, cym = (x0b + x1b) / 2, (y0b + y1b) / 2
        x0b, x1b, y0b, y1b = cxm - half, cxm + half, cym - half, cym + half
        rect = [0, 0, Hh / W, 1]
    else:
        leg = 0.95                          # inches reserved for legends under the map
        side = inches
        mh = inches * (y1b - y0b) / (x1b - x0b)
        W, Hh = inches, mh + leg
        rect = [0, leg / Hh, 1, mh / Hh]
    span = max(x1b - x0b, y1b - y0b) / 2.07
    ks = side / 16.5 / span                # scale relative to the 16.5-inch poster map
    boost = 1.0 if side >= 12 else 1.7     # small (paper) figures need relatively larger marks
    area = ks * ks * boost
    fig = plt.figure(figsize=(W, Hh), facecolor=th["bg"])
    ax = fig.add_axes(rect)
    ax.set_facecolor(th["bg"])
    lim = max(abs(x0b), abs(x1b), abs(y0b), abs(y1b))
    if theme == "dark":
        _backdrop(ax, th, lim, area)
    gpos = {g: (x, y, r) for g, x, y, r in Gl[["group_id", "x", "y", "r"]].itertuples(index=False)}
    patches, fcs, ecs = [], [], []
    for x, y, r, gt in Gl[["x", "y", "r", "group_type"]].itertuples(index=False):
        col = th["gt"].get(gt, th["gt"]["unknown"])
        patches.append(Circle((x, y), r))
        fcs.append(mcolors.to_rgba(col, 0.05 if theme == "dark" else 0.04))
        ecs.append(mcolors.to_rgba(col, 0.45 if theme == "dark" else 0.55))
    ax.add_collection(PatchCollection(patches, facecolors=fcs, edgecolors=ecs, linewidths=0.7 * ks * boost ** 0.5,
                                      zorder=1))
    _ties(ax, D.get("T"), gpos, th, ks * boost ** 0.5)

    icol = np.array([mcolors.to_rgba(th["ind"].get(i, th["ind"]["OTHER"])) for i in N["industry"]])
    segs, sel = edge_segments(N)
    ecol = icol[sel].copy()
    ecol[:, 3] = th["edge_alpha"]
    ax.add_collection(LineCollection(segs, colors=ecol, linewidths=0.32 * ks * boost ** 0.5, zorder=2,
                                     capstyle="round"))
    xs, ys = N["x"].to_numpy(float), N["y"].to_numpy(float)
    cat, w = node_category(N), node_weights(N, Gl)
    base = 2.0 * area
    for c, z in (("private", 3.0), ("holding", 3.2)):
        m = cat == c
        ax.scatter(xs[m], ys[m], s=w[m] * base, c=icol[m], linewidths=0, alpha=th["node_alpha"], zorder=z)
    m = cat == "foreign"
    ax.scatter(xs[m], ys[m], s=w[m] * base, facecolors="none", edgecolors=icol[m], linewidths=0.45 * ks * boost ** 0.5,
               zorder=3.1)
    m = cat == "listed"
    ax.scatter(xs[m], ys[m], s=w[m] * base, c=icol[m], edgecolors=th["fg"], linewidths=0.55 * ks * boost ** 0.5,
               zorder=4)
    m = cat == "apex"
    gt_of = dict(zip(Gl["group_id"], Gl["group_type"]))
    gcol = np.array([mcolors.to_rgba(th["gt"].get(gt_of.get(g), th["gt"]["unknown"])) for g in N["group_id"]])
    for mult, alpha in ((7.0, 0.07), (3.0, 0.16)):
        ax.scatter(xs[m], ys[m], s=w[m] * base * mult, c=gcol[m][:, :3], alpha=alpha, linewidths=0, zorder=4.5)
    ax.scatter(xs[m], ys[m], s=w[m] * base, c=gcol[m], edgecolors=th["fg"], linewidths=0.6 * ks * boost ** 0.5,
               zorder=5)

    # numbered badges on the rim of each top group, moved around the rim until no two badges touch
    order = Gl.sort_values("rank")
    bfs = max(4.0, 7.5 * ks * boost ** 0.5)
    rb = 0.8 * bfs / 72 * (x1b - x0b) / (Hh if panel else W)      # badge radius in data units
    placed = []
    for r in order.head(top_n).itertuples():
        bx, by = r.x, r.y + r.r
        for ang in (90, 60, 120, 30, 150, 0, 180, 45, 135, 210, 330, 270, 240, 300):
            cx_, cy_ = r.x + r.r * math.cos(math.radians(ang)), r.y + r.r * math.sin(math.radians(ang))
            inside = x0b + rb < cx_ < x1b - rb and y0b + rb < cy_ < y1b - rb
            if inside and all(math.hypot(cx_ - px, cy_ - py) > 2.5 * rb for px, py in placed):
                bx, by = cx_, cy_
                break
        placed.append((bx, by))
        ax.text(bx, by, str(int(r.rank)), ha="center", va="center", color=th["bg"], fontweight="bold",
                fontsize=bfs, zorder=9, bbox=dict(boxstyle="circle,pad=0.18", fc=th["fg"], ec=th["bg"], lw=0.5))
    ax.set_xlim(x0b, x1b)
    ax.set_ylim(y0b, y1b)
    ax.set_aspect("equal")
    ax.axis("off")
    present = [g for g in GT_ORDER if g in set(Gl["group_type"])]
    if panel:
        _panel(fig, Hh / W, th, D, N, Gl, cfg, synthetic, W / 24.0, top_n, present)
    else:
        _below_legend(fig, th, present)
    issues = text_overlaps(fig) if check else []
    for fmt in formats:
        fig.savefig(f"{out_base}.{fmt}", dpi=dpi, facecolor=th["bg"])
    plt.close(fig)
    return issues


def _below_legend(fig, th, present):
    fs = 6.2
    h1 = [Line2D([], [], marker="o", ls="none", ms=4, color=th["ind"][c], label=IND_LABEL[c]) for c in IND]
    l1 = fig.legend(handles=h1, loc="lower left", bbox_to_anchor=(0.01, 0.005), ncol=3, fontsize=fs, frameon=False,
                    handletextpad=0.1, columnspacing=0.9, labelspacing=0.3, title="Industry of each firm",
                    title_fontsize=fs + 0.5, alignment="left")
    h2 = [Line2D([], [], marker="o", ls="none", ms=6, mfc="none", mec=th["gt"][g], mew=1.2, label=GT_LABEL[g])
          for g in present]
    fig.legend(handles=h2, loc="lower right", bbox_to_anchor=(0.995, 0.005), ncol=2, fontsize=fs, frameon=False,
               handletextpad=0.1, columnspacing=0.9, labelspacing=0.3, title="Ring colour: ultimate owner of the group",
               title_fontsize=fs + 0.5, alignment="left")


def _panel(fig, x0, th, D, N, Gl, cfg, synthetic, kf, top_n, present):
    pa = fig.add_axes([x0 + 0.015, 0.03, 1 - x0 - 0.03, 0.94])
    pa.set_xlim(0, 1)
    pa.set_ylim(0, 1)
    pa.axis("off")
    fg, mu = th["fg"], th["muted"]
    fs = 10.5 * kf

    def head(y, text):
        pa.text(0, y, text, fontsize=12 * kf, color=fg, fontweight="bold", va="top")
        return y - 0.03

    def dot(x, y, kind, color=None):
        s = 60 * kf ** 2
        if kind == "ring":
            pa.scatter([x], [y], s=s * 1.4, facecolors="none", edgecolors=color, linewidths=1.8 * kf)
        elif kind == "foreign":
            pa.scatter([x], [y], s=s, facecolors="none", edgecolors=th["ind"]["INDUS"], linewidths=1.2 * kf)
        elif kind == "listed":
            pa.scatter([x], [y], s=s * 1.5, c=th["ind"]["INDUS"], edgecolors=fg, linewidths=1.0 * kf)
        elif kind == "apex":
            pa.scatter([x], [y], s=s * 6, c=th["gt"]["family"], alpha=0.15, linewidths=0)
            pa.scatter([x], [y], s=s * 2, c=th["gt"]["family"], edgecolors=fg, linewidths=1.0 * kf)
        else:
            pa.scatter([x], [y], s=s * 0.6, c=color or th["ind"]["INDUS"], linewidths=0)

    y = 1.0
    pa.text(0, y, cfg["project"].get("short_title") or "Thai business groups", fontsize=30 * kf, color=fg,
            fontweight="bold", va="top")
    y -= 0.05
    sub = ("Ownership network of listed companies and the subsidiaries they report. Each cluster is one business "
           "group: its ultimate owner sits at the centre and controlled firms radiate outward, one ring per "
           "ownership link.")
    pa.text(0, y, textwrap.fill(sub, 68), fontsize=12.5 * kf, color=mu, va="top", linespacing=1.45)
    y -= 0.095
    nlinks = int((N["parent"].fillna("") != "").sum())
    for i, (v, lab) in enumerate([(f"{len(N):,}", "entities drawn"), (f"{nlinks:,}", "control links"),
                                  (f"{len(Gl):,}", f"groups of {cfg['viz']['min_group_size']}+ firms")]):
        pa.text(i * 0.34, y, v, fontsize=22 * kf, color=fg, fontweight="bold", va="top")
        pa.text(i * 0.34, y - 0.034, lab, fontsize=fs, color=mu, va="top")
    y -= 0.09
    y = head(y, "Industry of each firm")
    for i, code in enumerate(IND):
        cx, cy = (i % 3) * 0.34, y - (i // 3) * 0.026 - 0.008
        dot(cx + 0.008, cy, "plain", th["ind"][code])
        pa.text(cx + 0.026, cy, IND_LABEL[code], fontsize=fs, color=fg, va="center")
    y -= 0.026 * 3 + 0.02
    y = head(y, "Nodes")
    for i, (k, lab) in enumerate([("apex", "Ultimate owner (centre of a group)"),
                                  ("listed", "Listed company, sized by market value"),
                                  ("plain", "Unlisted Thai company"), ("foreign", "Company registered abroad")]):
        cx, cy = (i % 2) * 0.5, y - (i // 2) * 0.028 - 0.008
        dot(cx + 0.008, cy, k)
        pa.text(cx + 0.03, cy, lab, fontsize=fs, color=fg, va="center")
    y -= 0.028 * 2 + 0.02
    y = head(y, "Ring colour: who ultimately controls the group")
    for i, gt in enumerate(present):
        cx, cy = (i % 2) * 0.5, y - (i // 2) * 0.026 - 0.008
        dot(cx + 0.008, cy, "ring", th["gt"][gt])
        pa.text(cx + 0.03, cy, GT_LABEL[gt], fontsize=fs, color=fg, va="center")
    y -= 0.026 * math.ceil(len(present) / 2) + 0.02
    y = head(y, "Arcs between groups")
    for i, (col, lab) in enumerate([(th["tie_dir"], "Shared directors"), (th["tie_own"], "Cross-ownership")]):
        pa.plot([i * 0.5, i * 0.5 + 0.035], [y - 0.008] * 2, color=col, lw=2.4 * kf, alpha=0.85,
                solid_capstyle="round")
        pa.text(i * 0.5 + 0.045, y - 0.008, lab, fontsize=fs, color=fg, va="center")
    y -= 0.05
    y = head(y, "Largest groups by number of firms (numbers on the map)")
    top = Gl.sort_values("rank").head(top_n)
    nrow = max(1, math.ceil(len(top) / 2))
    step = min(0.0235, (y - 0.065) / nrow)
    for i, r in enumerate(top.itertuples()):
        cx, cy = (i // nrow) * 0.5, y - (i % nrow) * step
        pa.text(cx, cy, f"{int(r.rank)}", fontsize=9.5 * kf, color=mu, va="top", fontweight="bold")
        pa.text(cx + 0.045, cy, _clip(r.label, 30), fontsize=9.5 * kf, color=fg, va="top")
        pa.text(cx + 0.47, cy, f"{int(r.n_firms)}", fontsize=9.5 * kf, color=mu, va="top", ha="right")
    foot = (f"Sources: SET, SEC (Form 56-1 One Report), DBD, bank Pillar 3 reports, GLEIF. Shareholdings as of "
            f"{cfg['project'].get('as_of') or 'n/a'}; control threshold {int(cfg['ownership']['group_threshold'] * 100)}%.")
    if synthetic:
        foot = "SYNTHETIC DEMONSTRATION: every company, person and number is fictional. " + foot
    pa.text(0, 0.0, textwrap.fill(foot, 92), fontsize=8.5 * kf, color=mu, va="bottom", linespacing=1.35)
