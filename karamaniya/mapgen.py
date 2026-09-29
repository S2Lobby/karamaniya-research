"""The map of Solvara, drawn from the scenario's regions.

The geography is generated once from a fixed seed, so every run shares the same island: a
noisy coastline around the region centres, regions grown outwards from their centres with
wandering borders, relief shaped by each region's terrain, rivers that run downhill to the
sea, and the cities, ports and roads between them. Everything comes out as SVG path data in a
1000 x 700 frame. The report colours it month by month.

How it works: the frame is cut into small square cells. Each cell gets a label (sea, lake or a
region). The edges between differently labelled cells form a planar graph; its chains (runs of
edges between junctions) are simplified and smoothed once, and every region outline, border and
coastline is assembled from those shared chains, so neighbouring regions always meet exactly.
"""
from __future__ import annotations

import math
import random
from collections import deque
from functools import lru_cache

W, H = 1000, 700
CELL = 4
NX, NY = W // CELL, H // CELL
SEED = 1847
SEA, LAKE = -1, -2

# How the scenario's regions look on the ground (the rivals only carry names and positions).
RELIEF = {"aster": 1.15, "kessel": 1.35, "lissen": 0.95, "highlands": 1.9, "dorran": 0.85,
          "arven": 1.0, "tolmar": 1.35, "irongate": 1.7, "belcor": 1.0, "goldfield": 0.9}
SPREAD = {"aster": 0.80, "kessel": 1.0, "lissen": 0.95, "highlands": 1.2, "dorran": 1.1,
          "arven": 1.15, "tolmar": 1.1, "irongate": 1.1, "belcor": 1.05, "goldfield": 1.1}
FARMLAND = {"lissen", "dorran", "goldfield", "tolmar"}
INDUSTRY = {"kessel": "factory", "irongate": "mine", "aster": "shipyard", "belcor": "factory"}
CITY_NAMES = {"aster": "Port Aster", "kessel": "Kessel", "lissen": "Lissen", "highlands": "Vellmark",
              "dorran": "Dorran", "arven": "Arven", "tolmar": "Tolmar", "irongate": "Irongate",
              "belcor": "Belcor", "goldfield": "Goldfield"}
SYLLABLES = ("ka", "ra", "ven", "dor", "lis", "mar", "tel", "os", "var", "an", "sel", "brin", "ost", "vel",
             "ham", "kor", "len", "tor", "mir", "sa", "del", "gar", "ne", "ul", "ber", "ton")


class Noise:
    """2D gradient noise (Perlin), seeded."""

    def __init__(self, seed: int):
        rng = random.Random(seed)
        p = list(range(256))
        rng.shuffle(p)
        self.p = p + p
        self.g = []
        for _ in range(256):
            a = rng.random() * 2 * math.pi
            self.g.append((math.cos(a), math.sin(a)))

    def __call__(self, x: float, y: float) -> float:
        xi, yi = math.floor(x), math.floor(y)
        xf, yf = x - xi, y - yi
        xi &= 255
        yi &= 255
        p, g = self.p, self.g
        g00 = g[p[p[xi] + yi] & 255]
        g10 = g[p[p[xi + 1] + yi] & 255]
        g01 = g[p[p[xi] + yi + 1] & 255]
        g11 = g[p[p[xi + 1] + yi + 1] & 255]
        n00 = g00[0] * xf + g00[1] * yf
        n10 = g10[0] * (xf - 1) + g10[1] * yf
        n01 = g01[0] * xf + g01[1] * (yf - 1)
        n11 = g11[0] * (xf - 1) + g11[1] * (yf - 1)
        u = xf * xf * xf * (xf * (xf * 6 - 15) + 10)
        v = yf * yf * yf * (yf * (yf * 6 - 15) + 10)
        a = n00 + (n10 - n00) * u
        b = n01 + (n11 - n01) * u
        return (a + (b - a) * v) * 1.41

    def fbm(self, x: float, y: float, octaves: int = 4) -> float:
        total, amp, freq, norm = 0.0, 1.0, 1.0, 0.0
        for _ in range(octaves):
            total += amp * self(x * freq, y * freq)
            norm += amp
            amp *= 0.5
            freq *= 2.03
        return total / norm


# ---- geometry helpers ------------------------------------------------------------------
def _simplify(pts: list, eps: float) -> list:
    """Douglas-Peucker: turn grid staircases into straight runs before smoothing."""
    if len(pts) < 3:
        return pts
    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        a, b = stack.pop()
        (x1, y1), (x2, y2) = pts[a], pts[b]
        dx, dy = x2 - x1, y2 - y1
        norm = math.hypot(dx, dy) or 1e-9
        best, idx = -1.0, -1
        for i in range(a + 1, b):
            x0, y0 = pts[i]
            d = abs(dy * x0 - dx * y0 + x2 * y1 - y2 * x1) / norm
            if d > best:
                best, idx = d, i
        if best > eps:
            keep[idx] = True
            stack += [(a, idx), (idx, b)]
    return [p for p, k in zip(pts, keep) if k]


def _chaikin(pts: list, rounds: int, closed: bool) -> list:
    for _ in range(rounds):
        if len(pts) < 3:
            return pts
        out = [] if closed else [pts[0]]
        n = len(pts)
        rng = range(n) if closed else range(n - 1)
        for i in rng:
            (x0, y0), (x1, y1) = pts[i], pts[(i + 1) % n]
            out.append((0.75 * x0 + 0.25 * x1, 0.75 * y0 + 0.25 * y1))
            out.append((0.25 * x0 + 0.75 * x1, 0.25 * y0 + 0.75 * y1))
        if not closed:
            out.append(pts[-1])
        pts = out
    return pts


def _fmt(v: float) -> str:
    s = f"{v:.1f}"
    return s[:-2] if s.endswith(".0") else s


def _path(pts: list, closed: bool) -> str:
    if not pts:
        return ""
    head = f"M{_fmt(pts[0][0])} {_fmt(pts[0][1])}"
    body = "".join(f"L{_fmt(x)} {_fmt(y)}" for x, y in pts[1:])
    return head + body + ("Z" if closed else "")


# ---- the map ---------------------------------------------------------------------------
def _frame_fn(regions):
    xs, ys = [r["x"] for r in regions], [r["y"] for r in regions]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    return lambda x, y: (200 + (x - x0) / ((x1 - x0) or 1) * 600, 150 + (y - y0) / ((y1 - y0) or 1) * 410)


def _hull(points):
    """Convex hull (monotone chain), counter-clockwise."""
    pts = sorted(set(points))
    if len(pts) < 3:
        return pts

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    lower, upper = [], []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def _outside_distance(x, y, hull):
    """Signed distance to the convex hull: negative inside, positive outside."""
    inside = True
    n = len(hull)
    for k in range(n):
        (ax, ay), (bx, by) = hull[k], hull[(k + 1) % n]
        if (bx - ax) * (y - ay) - (by - ay) * (x - ax) < 0:
            inside = False
            break
    best = 1e18
    for k in range(n):
        (ax, ay), (bx, by) = hull[k], hull[(k + 1) % n]
        dx, dy = bx - ax, by - ay
        t = max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / ((dx * dx + dy * dy) or 1e-9)))
        best = min(best, math.hypot(x - ax - t * dx, y - ay - t * dy))
    return -best if inside else best


def _neighbors4(i, j):
    if i > 0:
        yield i - 1, j
    if i < NX - 1:
        yield i + 1, j
    if j > 0:
        yield i, j - 1
    if j < NY - 1:
        yield i, j + 1


def _components(mask_fn, cells):
    """Connected groups (4-neighbour) of the cells for which mask_fn is true."""
    seen = set()
    groups = []
    for start in cells:
        if start in seen or not mask_fn(*start):
            continue
        comp, q = [], deque([start])
        seen.add(start)
        while q:
            c = q.popleft()
            comp.append(c)
            for nb in _neighbors4(*c):
                if nb not in seen and mask_fn(*nb):
                    seen.add(nb)
                    q.append(nb)
        groups.append(comp)
    return groups


@lru_cache(maxsize=4)
def _build(regions_key: tuple) -> dict:
    regions = [dict(zip(("id", "name", "nation", "x", "y", "coast", "capital"), r)) for r in regions_key]
    rng = random.Random(SEED)
    coast_n, warp_x, warp_y, relief_n, ridge_n, moist_n = (Noise(SEED + k) for k in range(6))
    frame = _frame_fn(regions)
    centers = []
    for r in regions:
        cx, cy = frame(r["x"], r["y"])
        centers.append((cx, cy, SPREAD.get(r["id"], 1.0)))
    all_cells = [(i, j) for j in range(NY) for i in range(NX)]
    hull = _hull([(cx, cy) for cx, cy, _ in centers])

    # 1. Land: everything between the region centres, plus a noisy margin outside them, so the
    #    coast has capes and bays but open sea all round the frame.
    land = [[False] * NX for _ in range(NY)]
    for j in range(NY):
        y = (j + 0.5) * CELL
        for i in range(NX):
            x = (i + 0.5) * CELL
            d = _outside_distance(x, y, hull)
            if d > 190:
                continue
            near = min(math.hypot(x - cx, y - cy) for cx, cy, _ in centers)
            v = (1 - d / 80 + 1.45 * coast_n.fbm(x / 210, y / 210, 5)
                 + 0.32 * coast_n.fbm(x / 48 + 17, y / 48, 3))
            land[j][i] = v > 0.25 or near < 48
    # Keep the main island and sizeable islets; small sea pockets inland become lakes or land.
    groups = _components(lambda i, j: land[j][i], all_cells)
    groups.sort(key=len, reverse=True)
    for comp in groups[1:]:
        if len(comp) < 60:
            for i, j in comp:
                land[j][i] = False
    water = _components(lambda i, j: not land[j][i], all_cells)
    lake = [[False] * NX for _ in range(NY)]
    for comp in water:
        touches_edge = any(i in (0, NX - 1) or j in (0, NY - 1) for i, j in comp)
        if touches_edge:
            continue
        if len(comp) < 90:
            for i, j in comp:
                land[j][i] = True
        else:
            for i, j in comp:
                lake[j][i] = True

    # 2. Regions: nearest centre after warping the map, so borders wander like real ones.
    label = [[SEA] * NX for _ in range(NY)]
    for j in range(NY):
        y = (j + 0.5) * CELL
        for i in range(NX):
            if lake[j][i]:
                label[j][i] = LAKE
                continue
            if not land[j][i]:
                continue
            x = (i + 0.5) * CELL
            wx = x + 55 * warp_x.fbm(x / 160, y / 160, 3)
            wy = y + 55 * warp_y.fbm(x / 160 + 9, y / 160, 3)
            best, bi = 1e18, 0
            for k, (cx, cy, s) in enumerate(centers):
                d = math.hypot(wx - cx, wy - cy) / s
                if d < best:
                    best, bi = d, k
            label[j][i] = bi
    # Every region must be one piece: stray fragments join the neighbour they touch most.
    for _ in range(3):
        changed = False
        for k, (cx, cy, s) in enumerate(centers):
            home = (min(NX - 1, int(cx / CELL)), min(NY - 1, int(cy / CELL)))
            parts = _components(lambda i, j, k=k: label[j][i] == k, [c for c in all_cells if label[c[1]][c[0]] == k])
            if not parts:
                continue
            parts.sort(key=lambda comp: (home in comp, len(comp)), reverse=True)
            for comp in parts[1:]:
                votes = {}
                for c in comp:
                    for nb in _neighbors4(*c):
                        lab = label[nb[1]][nb[0]]
                        if lab >= 0 and lab != k:
                            votes[lab] = votes.get(lab, 0) + 1
                target = max(votes, key=votes.get) if votes else SEA
                for i, j in comp:
                    label[j][i] = target
                changed = True
        if not changed:
            break

    # 3. Relief: height rises inland and with each region's ruggedness.
    dist = [[0] * NX for _ in range(NY)]
    q = deque()
    for j in range(NY):
        for i in range(NX):
            if label[j][i] >= 0 and any(label[b][a] < 0 for a, b in _neighbors4(i, j)):
                dist[j][i] = 1
                q.append((i, j))
    while q:
        i, j = q.popleft()
        for a, b in _neighbors4(i, j):
            if label[b][a] >= 0 and dist[b][a] == 0:
                dist[b][a] = dist[j][i] + 1
                q.append((a, b))
    ids = [r["id"] for r in regions]
    elev = [[-1.0] * NX for _ in range(NY)]
    for j in range(NY):
        y = (j + 0.5) * CELL
        for i in range(NX):
            k = label[j][i]
            if k < 0:
                continue
            x = (i + 0.5) * CELL
            rug = RELIEF.get(ids[k], 1.0)
            inland = min(1.0, dist[j][i] / 30)
            ridge = 1 - abs(ridge_n.fbm(x / 120, y / 120, 4))
            elev[j][i] = (0.12 + 0.28 * inland + 0.18 * relief_n.fbm(x / 90, y / 90, 4)
                          + (rug - 0.9) * 0.42 * ridge * (0.4 + 0.6 * inland))

    # 4. The planar graph of borders between differently labelled cells.
    def lab(i, j):
        return label[j][i] if 0 <= i < NX and 0 <= j < NY else SEA

    edges = {}          # corner -> list of (other corner, pair)
    for j in range(NY + 1):
        for i in range(NX):
            a, b = lab(i, j - 1), lab(i, j)
            if a != b:
                pair = (min(a, b), max(a, b))
                edges.setdefault((i, j), []).append(((i + 1, j), pair))
                edges.setdefault((i + 1, j), []).append(((i, j), pair))
    for j in range(NY):
        for i in range(NX + 1):
            a, b = lab(i - 1, j), lab(i, j)
            if a != b:
                pair = (min(a, b), max(a, b))
                edges.setdefault((i, j), []).append(((i, j + 1), pair))
                edges.setdefault((i, j + 1), []).append(((i, j), pair))

    def junction(c):
        i, j = c
        labs = {lab(i - 1, j - 1), lab(i, j - 1), lab(i - 1, j), lab(i, j)}
        return len(labs) >= 3 or len(edges.get(c, ())) != 2

    used = set()
    chains = []   # (pair, points, closed)

    def walk(start, nxt, pair):
        pts = [start, nxt]
        used.add(frozenset((start, nxt)))
        prev, cur = start, nxt
        while not junction(cur) and cur != start:
            step = None
            for other, p in edges[cur]:
                if p == pair and other != prev and frozenset((cur, other)) not in used:
                    step = other
                    break
            if step is None:
                break
            used.add(frozenset((cur, step)))
            pts.append(step)
            prev, cur = cur, step
        return pts

    for c in list(edges):
        if junction(c):
            for other, pair in edges[c]:
                if frozenset((c, other)) not in used:
                    chains.append((pair, walk(c, other, pair), False))
    for c in list(edges):
        for other, pair in edges[c]:
            if frozenset((c, other)) not in used:
                pts = walk(c, other, pair)
                chains.append((pair, pts, pts[0] == pts[-1]))

    smooth = []
    for pair, pts, closed in chains:
        xy = [(i * CELL, j * CELL) for i, j in pts]
        if closed:
            xy = xy[:-1]
            xy = _simplify(xy + [xy[0]], CELL * 0.9)[:-1] if len(xy) > 3 else xy
            xy = _chaikin(xy, 2, True)
        else:
            xy = _chaikin(_simplify(xy, CELL * 0.9), 2, False)
        smooth.append((pair, xy, closed))

    # 5. Region outlines assembled from the shared chains.
    def rings_for(k):
        parts = [(xy, closed) for pair, xy, closed in smooth if k in pair and pair[0] != pair[1]]
        rings = [xy for xy, closed in parts if closed]
        open_parts = [xy for xy, closed in parts if not closed]
        ends = {}
        for idx, xy in enumerate(open_parts):
            for end in (0, -1):
                key = (round(xy[end][0], 3), round(xy[end][1], 3))
                ends.setdefault(key, []).append(idx)
        left = set(range(len(open_parts)))
        while left:
            idx = left.pop()
            ring = list(open_parts[idx])
            start = (round(ring[0][0], 3), round(ring[0][1], 3))
            for _ in range(len(open_parts) + 1):
                tail = (round(ring[-1][0], 3), round(ring[-1][1], 3))
                if tail == start:
                    break
                nxt = next((n for n in ends.get(tail, []) if n in left), None)
                if nxt is None:
                    break
                left.discard(nxt)
                seg = open_parts[nxt]
                if (round(seg[0][0], 3), round(seg[0][1], 3)) != tail:
                    seg = seg[::-1]
                ring += seg[1:]
            rings.append(ring)
        return rings

    nation = {k: r["nation"] for k, r in enumerate(regions)}
    borders, coast, shores = [], [], []
    adjacency = set()
    for (a, b), xy, closed in smooth:
        if a == SEA or b == SEA:
            if max(a, b) >= 0:
                coast.append(_path(xy, closed))
        elif a == LAKE or b == LAKE:
            if max(a, b) >= 0:
                shores.append(_path(xy, closed))
        elif a >= 0 and b >= 0:
            adjacency.add((a, b))
            borders.append({"a": ids[a], "b": ids[b], "national": nation[a] != nation[b],
                            "path": _path(xy, closed), "mid": [round(v, 1) for v in xy[len(xy) // 2]]})
    lakes = []
    for comp in _components(lambda i, j: label[j][i] == LAKE, all_cells):
        pass  # lakes are drawn from their shore chains
    lake_rings = [_path(xy, True) for (a, b), xy, closed in smooth if LAKE in (a, b) and closed]

    # 6. Rivers: from high ground, downhill to the sea.
    def cell_elev(c):
        i, j = c
        return elev[j][i] if label[j][i] >= 0 else -1.0

    sources = [(i, j) for j in range(2, NY - 2, 3) for i in range(2, NX - 2, 3)
               if label[j][i] >= 0 and elev[j][i] > 0.52]
    rng.shuffle(sources)
    river_cells = set()
    rivers = []
    for src in sources:
        if len(rivers) >= 7:
            break
        if any(abs(src[0] - a) + abs(src[1] - b) < 18 for a, b in river_cells):
            continue
        path, seen = [src], {src}
        cur = src
        ok = False
        for _ in range(400):
            options = [nb for nb in ((cur[0] + dx, cur[1] + dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1) if dx or dy)
                       if 0 <= nb[0] < NX and 0 <= nb[1] < NY and nb not in seen]
            if not options:
                break
            nxt = min(options, key=lambda c: cell_elev(c) + 0.015 * rng.random())
            seen.add(nxt)
            path.append(nxt)
            if label[nxt[1]][nxt[0]] < 0 or nxt in river_cells:
                ok = True
                break
            cur = nxt
        if ok and len(path) > 22:
            river_cells.update(path)
            xy = [((i + 0.5) * CELL, (j + 0.5) * CELL) for i, j in path]
            rivers.append(_path(_chaikin(_simplify(xy, CELL * 0.9), 3, False), False))

    # 7. Relief symbols, forests and fields.
    mountains, hills, forest, fields = [], [], [], []
    for j in range(1, NY - 1, 3):
        for i in range(1, NX - 1, 3):
            jj = min(NY - 1, j + rng.randint(-1, 1))
            ii = min(NX - 1, i + rng.randint(-1, 1))
            k = label[jj][ii]
            if k < 0 or dist[jj][ii] < 3:
                continue
            x, y = (ii + 0.5) * CELL, (jj + 0.5) * CELL
            e = elev[jj][ii]
            if e > 0.62 and rng.random() < 0.75:
                mountains.append([round(x, 1), round(y, 1), round(min(1.6, 0.8 + (e - 0.62) * 3), 2)])
            elif e > 0.5 and rng.random() < 0.45:
                hills.append([round(x, 1), round(y, 1)])
            elif moist_n.fbm(x / 70, y / 70, 3) > 0.22 and rng.random() < 0.8:
                forest.append([round(x, 1), round(y, 1)])
            elif ids[k] in FARMLAND and e < 0.48 and rng.random() < 0.35:
                fields.append([round(x, 1), round(y, 1), rng.choice((0, 30, 60, 90, 120, 150))])

    # 8. Cities, towns, ports and roads.
    cities = []
    for k, r in enumerate(regions):
        cx, cy = centers[k][0], centers[k][1]
        ci, cj = min(NX - 1, int(cx / CELL)), min(NY - 1, int(cy / CELL))
        port = False
        if r["coast"] or r["capital"]:
            shore = [(i, j) for j in range(NY) for i in range(NX)
                     if label[j][i] == k and dist[j][i] == 1 and any(label[b][a] == SEA for a, b in _neighbors4(i, j))]
            if shore:
                si, sj = min(shore, key=lambda c: math.hypot(c[0] - ci, c[1] - cj))
                # Coastal regions put their main city on the water; inland capitals only if the sea is near.
                if r["coast"] or math.hypot(si - ci, sj - cj) < 30:
                    ci, cj, port = si, sj, True
        cities.append({"name": CITY_NAMES.get(r["id"], r["name"]), "region": r["id"], "kind": "capital" if r["capital"] else "city",
                       "x": round((ci + 0.5) * CELL, 1), "y": round((cj + 0.5) * CELL, 1), "port": port})
        # One or two towns per region, away from the main city.
        cells = [(i, j) for j in range(2, NY - 2, 2) for i in range(2, NX - 2, 2)
                 if label[j][i] == k and dist[j][i] > 3 and elev[j][i] < 0.6]
        rng.shuffle(cells)
        placed = 0
        for i, j in cells:
            x, y = (i + 0.5) * CELL, (j + 0.5) * CELL
            if all(math.hypot(x - c["x"], y - c["y"]) > 70 for c in cities):
                name = "".join(rng.choice(SYLLABLES) for _ in range(rng.choice((2, 2, 3)))).capitalize()
                cities.append({"name": name, "region": r["id"], "kind": "town", "x": round(x, 1), "y": round(y, 1), "port": False})
                placed += 1
                if placed >= (2 if len(cells) > 400 else 1):
                    break
    label_avoid = [(c["x"], c["y"]) for c in cities]
    out_regions = {}
    for k, r in enumerate(regions):
        cells = [(i, j) for j in range(NY) for i in range(NX) if label[j][i] == k]
        if not cells:
            continue
        # Label anchor: the cell farthest from the region's edge (a pole of inaccessibility).
        inner = {c: 0 for c in cells}
        dq = deque()
        for c in cells:
            if any(label[b][a] != k for a, b in _neighbors4(*c)) or c[0] in (0, NX - 1) or c[1] in (0, NY - 1):
                inner[c] = 1
                dq.append(c)
        while dq:
            c = dq.popleft()
            for nb in _neighbors4(*c):
                if nb in inner and inner[nb] == 0:
                    inner[nb] = inner[c] + 1
                    dq.append(nb)
        cx, cy = centers[k][0], centers[k][1]

        def score(c, cx=cx, cy=cy):
            x, y = (c[0] + 0.5) * CELL, (c[1] + 0.5) * CELL
            crowd = sum(max(0.0, 75 - math.hypot(x - t[0], y - t[1])) for t in label_avoid)
            return inner[c] * 3 - math.hypot(x - cx, y - cy) / 40 - crowd * 1.5
        best = max(cells, key=score)
        out_regions[r["id"]] = {
            "path": "".join(_path(ring, True) for ring in rings_for(k)),
            "lx": round((best[0] + 0.5) * CELL, 1), "ly": round((best[1] + 0.5) * CELL, 1),
            "area": len(cells),
        }

    main = {c["region"]: c for c in cities if c["kind"] != "town"}
    roads = []
    for a, b in sorted(adjacency):
        ca, cb = main.get(ids[a]), main.get(ids[b])
        if not ca or not cb:
            continue
        mx, my = (ca["x"] + cb["x"]) / 2, (ca["y"] + cb["y"]) / 2
        dx, dy = cb["x"] - ca["x"], cb["y"] - ca["y"]
        bend = rng.uniform(-0.12, 0.12)
        qx, qy = mx - dy * bend, my + dx * bend
        roads.append({"a": ids[a], "b": ids[b], "rail": nation[a] == nation[b],
                      "path": f"M{_fmt(ca['x'])} {_fmt(ca['y'])}Q{_fmt(qx)} {_fmt(qy)} {_fmt(cb['x'])} {_fmt(cb['y'])}"})
    for c in cities:
        if c["kind"] == "town":
            m = main.get(c["region"])
            if m:
                roads.append({"a": c["region"], "b": c["region"], "rail": False, "minor": True,
                              "path": f"M{_fmt(m['x'])} {_fmt(m['y'])}L{_fmt(c['x'])} {_fmt(c['y'])}"})

    # 9. Sea lanes out of the ports, towards the open sea.
    lanes = []
    coastal = {r["id"] for r in regions if r["coast"]}
    for c in cities:
        if not c["port"] or c["region"] not in coastal:
            continue
        best = None
        for ang in range(0, 360, 10):
            dx, dy = math.cos(math.radians(ang)), math.sin(math.radians(ang))
            clear = 0
            for step in range(4, 160, 4):
                x, y = c["x"] + dx * step, c["y"] + dy * step
                i, j = int(x / CELL), int(y / CELL)
                if not (0 <= i < NX and 0 <= j < NY):
                    clear = 999
                    break
                if label[j][i] >= 0:
                    clear = -1
                    break
                clear = step
            if clear >= 120 and (best is None or clear > best[0]):
                best = (clear, dx, dy)
        if best:
            _, dx, dy = best
            x2, y2 = c["x"] + dx * 170, c["y"] + dy * 170
            lanes.append({"region": c["region"], "path": f"M{_fmt(c['x'])} {_fmt(c['y'])}L{_fmt(x2)} {_fmt(y2)}",
                          "x": round(c["x"] + dx * 55, 1), "y": round(c["y"] + dy * 55, 1),
                          "dx": round(dx, 3), "dy": round(dy, 3)})

    return {"w": W, "h": H, "regions": out_regions, "borders": borders, "coast": coast, "shores": shores,
            "lakes": lake_rings, "rivers": rivers, "mountains": mountains, "hills": hills, "forest": forest,
            "fields": fields, "cities": cities, "roads": roads, "lanes": lanes,
            "industry": {rid: kind for rid, kind in INDUSTRY.items()}}


def build_map(regions) -> dict:
    """regions: dicts or objects with id, name, nation, x, y and optionally coast and capital."""
    key = []
    for r in regions:
        get = r.get if isinstance(r, dict) else (lambda k, d=None, r=r: getattr(r, k, d))
        key.append((get("id"), get("name"), get("nation"), float(get("x")), float(get("y")),
                    bool(get("coast", False)), bool(get("capital", False))))
    return _build(tuple(key))
