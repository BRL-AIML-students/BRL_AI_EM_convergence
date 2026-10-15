"""Saved mesh experiments; compare geometry/topology independently of numbering.

No nearest-node displacement interpretation: only unique mutual matches within an
absolute Euclidean tolerance are used. Ambiguous neighbourhoods stay unresolved.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
from itertools import product
import json
from pathlib import Path
import uuid

import gmsh
import numpy as np

from .config import validate
from .reporting import write_json
from .sizing import METRES_PER_UNIT

METRICS = {
    "edge_length": "중복 제거한 삼각형 변의 Euclidean 길이; 목표 길이와 구분 (표시 단위)",
    "mean_ratio": "4√3·면적 / (a²+b²+c²); 0~1, 1이 정삼각형이며 클수록 좋음",
    "aspect_ratio": "최장변·둘레 / (4√3·면적); 1 이상, 1이 정삼각형이며 작을수록 좋음",
    "minimum_angle_deg": "삼각형별 최소 내각 (도); 0~60, 클수록 좋음",
    "gmsh_minSICN": "Gmsh getElementQualities(minSICN): 최소 signed inverse condition number; 이상적 요소 1, 클수록 좋음. 3D 면의 전역 법선 방향 판정은 별도 검사.",
}


def plate_preset(output_dir: str = "outputs") -> dict:
    return validate({"name": "plate_experiment", "output_dir": output_dir,
                     "geometry": {"kind": "plate", "parameters": {"length": 40, "width": 30}},
                     "mesh": {"controlled": True, "mode": "fixed", "target_size": 3,
                              "minimum_size": .1, "algorithm": 6, "random_seed": 1,
                              "local": {"enabled": False}, "improvement": {"enabled": False}}})


def indexed(mesh: dict) -> tuple[np.ndarray, np.ndarray]:
    ids = np.asarray(mesh["node_ids"])
    points = np.asarray(mesh["coordinates"], dtype=float)
    conn = np.asarray(mesh["connectivity"])
    eids = np.asarray(mesh["element_ids"])
    if (ids.ndim != 1 or ids.dtype.kind not in "iu" or len(ids) == 0 or
            len(np.unique(ids)) != len(ids) or np.any(ids <= 0) or
            points.shape != (len(ids), 3) or not np.isfinite(points).all()):
        raise ValueError("corrupt mesh: invalid nodes/coordinates")
    if (conn.ndim != 2 or conn.shape[1] != 3 or len(conn) == 0 or conn.dtype.kind not in "iu" or
            eids.shape != (len(conn),) or eids.dtype.kind not in "iu" or
            len(np.unique(eids)) != len(eids) or np.any(eids <= 0)):
        raise ValueError("corrupt mesh: invalid triangles/element IDs")
    lookup = {int(n): i for i, n in enumerate(ids)}
    try:
        faces = np.array([[lookup[int(n)] for n in row] for row in conn], dtype=np.int64)
    except KeyError as exc:
        raise ValueError("corrupt mesh: missing connectivity node") from exc
    p = points[faces]
    if np.any(np.linalg.norm(np.cross(p[:, 1]-p[:, 0], p[:, 2]-p[:, 0]), axis=1) <= 0):
        raise ValueError("corrupt mesh: degenerate triangles")
    if len(np.unique(np.sort(faces, axis=1), axis=0)) != len(faces):
        raise ValueError("corrupt mesh: duplicate triangles")
    return points, faces


def samples(mesh: dict, scale: float = 1) -> dict[str, np.ndarray]:
    points, faces = indexed(mesh)
    points = points * scale
    edges = np.unique(np.sort(np.concatenate([faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]]), axis=1), axis=0)
    p = points[faces]
    lengths = np.stack([np.linalg.norm(p[:, (j+1)%3]-p[:, j], axis=1) for j in range(3)], axis=1)
    area = np.linalg.norm(np.cross(p[:, 1]-p[:, 0], p[:, 2]-p[:, 0]), axis=1)/2
    angles = [np.degrees(np.arctan2(np.linalg.norm(np.cross(p[:, (j+1)%3]-p[:, j], p[:, (j+2)%3]-p[:, j]), axis=1),
                                  np.einsum("ij,ij->i", p[:, (j+1)%3]-p[:, j], p[:, (j+2)%3]-p[:, j]))) for j in range(3)]
    return {"edge_length": np.linalg.norm(points[edges[:, 0]]-points[edges[:, 1]], axis=1),
            "mean_ratio": 4*np.sqrt(3)*area/(lengths**2).sum(axis=1),
            "aspect_ratio": lengths.max(axis=1)*lengths.sum(axis=1)/(4*np.sqrt(3)*area),
            "minimum_angle_deg": np.min(angles, axis=0)}


def summary(values) -> dict:
    a = np.asarray(values, dtype=float)
    if not len(a) or not np.isfinite(a).all():
        return {"count": len(a), "status": "not_assessed"}
    return {"count": len(a), "min": float(a.min()), "q01": float(np.percentile(a, 1)),
            "q05": float(np.percentile(a, 5)), "median": float(np.median(a)),
            "q95": float(np.percentile(a, 95)), "q99": float(np.percentile(a, 99)),
            "max": float(a.max()), "mean": float(a.mean()), "std": float(a.std())}


def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024*1024), b""):
            h.update(block)
    return h.hexdigest()


def preserve_snapshot(stage: Path, mesh: dict, assessment: dict) -> dict:
    """Keep all generated snapshots, including shape-limit failures, for research."""
    structural = [g for g in assessment["fatal_gates"] if g["code"] != "triangle_shape_limits"]
    state = "invalid_mesh" if structural else "quality_warning" if assessment["fatal_gates"] else "valid"
    np.savez_compressed(stage / "mesh_snapshot.npz", **{k: mesh[k] for k in
                        ("node_ids", "coordinates", "element_ids", "connectivity")})
    result = {"version": 1, "mesh_state": state, "structural_gates": structural,
              "note": "Mesh shape quality only; no MoM/RCS accuracy was evaluated. Legacy NAS publication gates still apply.",
              "metric_definitions": METRICS, "snapshot": "mesh_snapshot.npz",
              "sha256": {name: file_hash(stage/name) for name in ("mesh_snapshot.npz", "diagnostic.msh")}}
    try:
        result["distributions"] = {k: summary(v) for k, v in samples(mesh).items()}
    except ValueError as exc:
        result.update(mesh_state="invalid_mesh", validation_error=str(exc))
    try:
        values = gmsh.model.mesh.getElementQualities(mesh["element_ids"].tolist(), "minSICN")
        result["gmsh_minSICN"] = {"definition": METRICS["gmsh_minSICN"], "summary": summary(values), "values": values.tolist()}
    except Exception as exc:
        result["gmsh_minSICN"] = {"status": "not_assessed", "reason": str(exc)}
    return result


def save_failure(configuration: dict, error: Exception, sizing=None) -> Path:
    root = Path(configuration["output_dir"]).resolve()
    folder = root / f'failed_{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}_{uuid.uuid4().hex}'
    folder.mkdir(parents=True)
    from .pipeline import code_state
    write_json(folder / "report.json", {"run_id": folder.name, "created_utc": datetime.now(timezone.utc).isoformat(),
               "status": "error", "configuration": configuration, "sizing": sizing,
               "experiment": {"mesh_state": "generation_failed"}, "error": str(error),
               "environment": {"gmsh": gmsh.__version__, **code_state()}})
    return folder


def load_run(folder: str | Path) -> tuple[dict, dict]:
    folder = Path(folder).resolve()
    report = json.loads((folder / "report.json").read_text(encoding="utf-8"))
    exp = report.get("experiment", {})
    if exp.get("mesh_state") not in {"valid", "quality_warning"}:
        raise ValueError(f"Cannot compare {folder.name}: {exp.get('mesh_state', 'legacy run without snapshot')}")
    # Fixed artifact names; no paths from saved JSON are executed or followed.
    for name in ("mesh_snapshot.npz", "diagnostic.msh"):
        if file_hash(folder/name) != exp.get("sha256", {}).get(name):
            raise ValueError(f"corrupt mesh: {name} hash mismatch")
    with np.load(folder/"mesh_snapshot.npz", allow_pickle=False) as data:
        mesh = {k: data[k] for k in ("node_ids", "coordinates", "element_ids", "connectivity")}
    indexed(mesh)
    return report, mesh


def catalog(root: str | Path) -> list[dict]:
    records = []
    for path in sorted(Path(root).glob("*/report.json")):
        try:
            r = json.loads(path.read_text(encoding="utf-8"))
            state = r.get("experiment", {}).get("mesh_state", "legacy_no_snapshot")
            if state in {"valid", "quality_warning"}:
                try:
                    load_run(path.parent)
                except (ValueError, OSError, KeyError, EOFError):
                    state = "corrupt_file"
            records.append({"path": str(path.parent.resolve()), "state": state, "run_id": r.get("run_id", path.parent.name)})
        except (ValueError, OSError, KeyError, EOFError):
            records.append({"path": str(path.parent.resolve()), "state": "corrupt_file", "run_id": path.parent.name})
    return records


def differences(a, b, path="") -> list[dict]:
    if isinstance(a, dict) and isinstance(b, dict):
        return [row for k in sorted(a.keys() | b.keys()) for row in
                differences(a.get(k), b.get(k), (path+"."+k).lstrip("."))]
    return [] if a == b else [{"setting": path, "A": a, "B": b}]


def compare_meshes(a: dict, b: dict, unit_a="mm", unit_b="mm", tolerance=1e-8, unit="mm") -> dict:
    if unit not in METRES_PER_UNIT or unit_a not in METRES_PER_UNIT or unit_b not in METRES_PER_UNIT:
        raise ValueError("unsupported coordinate unit")
    if not np.isfinite(tolerance) or tolerance <= 0:
        raise ValueError("coordinate tolerance must be finite and positive")
    pa, fa = indexed(a); pb, fb = indexed(b)
    sa, sb = METRES_PER_UNIT[unit_a]/METRES_PER_UNIT[unit], METRES_PER_UNIT[unit_b]/METRES_PER_UNIT[unit]
    pa, pb = pa*sa, pb*sb
    # Use cells only for candidate discovery; never rounded-coordinate equality.
    cells = defaultdict(list)
    origin = np.minimum(pa.min(axis=0), pb.min(axis=0))
    def cell(p):
        return tuple(int(np.floor((float(v)-float(o))/tolerance)) for v, o in zip(p, origin))
    for j, p in enumerate(pb):
        cells[cell(p)].append(j)
    candidates = [[] for _ in pa]; reverse = [[] for _ in pb]
    work = 0
    for i, p in enumerate(pa):
        key = cell(p)
        for offset in product((-1, 0, 1), repeat=3):
            near = cells.get(tuple(k+d for k, d in zip(key, offset)), [])
            work += len(near)
            if work > 5_000_000:
                raise ValueError("Too many tolerance candidates; reduce tolerance or mesh size")
            for j in near:
                if np.linalg.norm(p-pb[j]) <= tolerance:
                    candidates[i].append(j); reverse[j].append(i)
    mapping = {i: c[0] for i, c in enumerate(candidates) if len(c) == 1 and len(reverse[c[0]]) == 1}
    ambiguous_a = [i for i, c in enumerate(candidates) if c and i not in mapping]
    matched_b = set(mapping.values())
    ambiguous_b = [j for j, c in enumerate(reverse) if c and j not in matched_b]
    absent_a = [i for i, c in enumerate(candidates) if not c]
    absent_b = [i for i, c in enumerate(reverse) if not c]
    same_nodes = (False if absent_a or absent_b or len(pa) != len(pb) else
                  None if ambiguous_a or ambiguous_b else True)
    reverse_map = {j: i for i, j in mapping.items()}
    ca = Counter(tuple(sorted(map(int, row))) for row in fa if all(int(i) in mapping for i in row))
    cb = Counter(tuple(sorted(reverse_map[int(j)] for j in row)) for row in fb if all(int(j) in reverse_map for j in row))
    common = sum((ca & cb).values())
    same_connectivity = None if ambiguous_a or ambiguous_b else common == len(fa) == len(fb)
    # Triangles/edges are compared as unoriented relations. Winding remains a separate quality audit.
    edge_a = {tuple(sorted((int(row[j]), int(row[(j+1)%3])))) for row in fa for j in range(3)}
    edge_b = {tuple(sorted((int(row[j]), int(row[(j+1)%3])))) for row in fb for j in range(3)}
    comparable_b = {tuple(sorted((reverse_map[x], reverse_map[y]))) for x, y in edge_b if x in reverse_map and y in reverse_map}
    shared = edge_a & comparable_b
    raw_a, raw_b = samples(a, sa), samples(b, sb)
    distributions = {}
    for name in raw_a:
        av, bv = raw_a[name], raw_b[name]
        low, high = min(av.min(), bv.min()), max(av.max(), bv.max())
        if low == high:
            low, high = low-.5, high+.5
        bins = np.linspace(low, high, 21)
        distributions[name] = {"definition": METRICS[name], "A": summary(av), "B": summary(bv),
                               "bin_edges": bins.tolist(), "hist_A": np.histogram(av, bins)[0].tolist(),
                               "hist_B": np.histogram(bv, bins)[0].tolist()}
    return {"coordinate_unit": unit, "tolerance": tolerance, "distance": "absolute Euclidean, no translation/rotation alignment",
            "node_set_equal": same_nodes, "connectivity_equal": same_connectivity,
            "same_mesh": False if same_nodes is False or same_connectivity is False else None if same_nodes is None or same_connectivity is None else True,
            "counts": {"nodes_A": len(pa), "nodes_B": len(pb), "triangles_A": len(fa), "triangles_B": len(fb),
                       "unique_matches": len(mapping), "absent_A": len(absent_a), "absent_B": len(absent_b),
                       "ambiguous_A": len(ambiguous_a), "ambiguous_B": len(ambiguous_b), "common_triangles": common,
                       "unconfirmed_triangles_A": len(fa)-common, "unconfirmed_triangles_B": len(fb)-common},
            "note": "Unmatched nodes are set differences, not moved-node pairs. Ambiguous nodes remain unresolved. Connectivity ignores numbering, order and winding; normal checks are separate.",
            "distributions": distributions,
            "visual": {"points_A": pa.tolist(), "points_B": pb.tolist(), "faces_A": fa.tolist(), "faces_B": fb.tolist(),
                       "edges_A": [list(e) for e in sorted(edge_a)], "edges_B": [list(e) for e in sorted(edge_b)],
                       "shared_edges_A": [list(e) for e in sorted(shared)],
                       "shared_edges_B": [sorted([mapping[x], mapping[y]]) for x, y in sorted(shared)],
                       "matched_A": sorted(mapping), "matched_B": sorted(matched_b),
                       "ambiguous_A": ambiguous_a, "ambiguous_B": ambiguous_b}}


def compare_runs(a: str | Path, b: str | Path, tolerance=1e-8, unit="mm", output_dir=None) -> dict:
    ra, ma = load_run(a); rb, mb = load_run(b)
    result = compare_meshes(ma, mb, ra["configuration"]["output_unit"], rb["configuration"]["output_unit"], tolerance, unit)
    for side, mesh, report in (("A",ma,ra),("B",mb,rb)):
        bad=report["assessment"]["scores"]["element_shape"]["problem_element_ids"]
        result["visual"]["bad_faces_"+side]=np.flatnonzero(np.isin(mesh["element_ids"],bad)).tolist()
    def inputs(r):
        return {k: r["configuration"][k] for k in ("geometry", "length_unit", "output_unit", "mesh", "quality")}
    def effective(r):
        return {"output_unit": r["configuration"]["output_unit"], "geometry": r["geometry"],
                "sizing": {k: v for k, v in r["sizing"].items() if k not in {"timings", "gmsh_defaults"}},
                "environment": {k: v for k, v in r["environment"].items() if k != "code_dirty"}}
    result.update(input_differences=differences(inputs(ra), inputs(rb)),
                  effective_differences=differences(effective(ra), effective(rb)),
                  runs={"A": str(Path(a).resolve()), "B": str(Path(b).resolve())},
                  metadata={"A": ra, "B": rb},
                  experiment_kind="same_inputs_repeat" if inputs(ra) == inputs(rb) else
                  "seed_change" if differences(inputs(ra), inputs(rb)) == [{"setting": "mesh.random_seed", "A": ra["configuration"]["mesh"]["random_seed"], "B": rb["configuration"]["mesh"]["random_seed"]}] else "settings_change")
    root = Path(output_dir or Path(a).parent) / f'ab_{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}_{uuid.uuid4().hex[:8]}'
    root.mkdir(parents=True)
    write_json(root/"comparison.json", result)
    from .experiment_report import write_comparison
    write_comparison(root/"comparison.html", result)
    return {**result, "output_directory": str(root.resolve()), "html": str((root/"comparison.html").resolve())}


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description="저장된 두 실행의 메쉬 비교")
    parser.add_argument("A", type=Path); parser.add_argument("B", type=Path)
    parser.add_argument("--tolerance", type=float, default=1e-8)
    parser.add_argument("--unit", choices=METRES_PER_UNIT, default="mm")
    args = parser.parse_args(argv)
    result = compare_runs(args.A, args.B, args.tolerance, args.unit)
    print(json.dumps({k: result[k] for k in ("same_mesh", "node_set_equal", "connectivity_equal", "counts", "html")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
