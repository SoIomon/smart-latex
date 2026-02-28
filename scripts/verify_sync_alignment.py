#!/usr/bin/env python3
"""验证双向同步高亮对齐精度的自动化脚本。

使用方式:
  1. 先启动后端 (uvicorn app.main:app --reload --port 8000)
  2. 确保有至少一个已编译的项目（有 synctex 数据）
  3. python scripts/verify_sync_alignment.py [project_id]
     如果不传 project_id，则自动选取第一个有 synctex 数据的项目

脚本流程:
  1. 获取 lineMap（step=2 的插值锚点）
  2. 对每一行调用 forwardSync 获取精确坐标
  3. 用前端同样的插值算法计算估算坐标
  4. 比较偏差，输出统计报告
"""

import asyncio
import sys
import httpx

BASE_URL = "http://localhost:8000/api/v1"


def interpolate_position(entries: list[dict], line: int) -> dict:
    """Replicate frontend interpolatePosition logic."""
    lower_idx = 0
    for i, e in enumerate(entries):
        if e["line"] <= line:
            lower_idx = i
        else:
            break

    upper_idx = len(entries) - 1
    for i in range(len(entries) - 1, -1, -1):
        if entries[i]["line"] >= line:
            upper_idx = i
        else:
            break

    lower = entries[lower_idx]
    upper = entries[upper_idx]

    if lower_idx == upper_idx or lower["page"] != upper["page"]:
        use_lower = (line - lower["line"]) <= (upper["line"] - line)
        return lower if use_lower else upper

    t = (line - lower["line"]) / (upper["line"] - lower["line"])
    return {"page": lower["page"], "y": lower["y"] + t * (upper["y"] - lower["y"])}


async def main():
    async with httpx.AsyncClient(timeout=30) as client:
        # Find project
        project_id = sys.argv[1] if len(sys.argv) > 1 else None

        if not project_id:
            r = await client.get(f"{BASE_URL}/projects")
            r.raise_for_status()
            projects = r.json()
            # Try each project for synctex data
            for p in projects:
                pid = p["id"]
                try:
                    lr = await client.get(f"{BASE_URL}/projects/{pid}/synctex/linemap")
                    if lr.status_code == 200:
                        project_id = pid
                        print(f"Using project: {p.get('name', pid)} ({pid})")
                        break
                except Exception:
                    continue
            if not project_id:
                print("No projects with synctex data found. Compile a project first.")
                sys.exit(1)

        # Fetch lineMap
        r = await client.get(f"{BASE_URL}/projects/{project_id}/synctex/linemap")
        r.raise_for_status()
        data = r.json()
        line_map = data["line_map"]
        total_lines = data["total_lines"]

        # Build sorted entries (same as frontend)
        entries = []
        for key, val in line_map.items():
            line_num = int(key)
            entries.append({"line": line_num, "page": val["page"], "y": val["y"]})
        entries.sort(key=lambda e: e["line"])

        print(f"\nlineMap entries: {len(entries)} (total source lines: {total_lines})")
        print(f"Line range in lineMap: {entries[0]['line']}–{entries[-1]['line']}")
        print(f"Pages covered: {sorted(set(e['page'] for e in entries))}")

        # Query forwardSync for every line and compare
        deviations = []
        page_mismatches = 0
        errors = 0

        print(f"\nQuerying forwardSync for lines 1–{total_lines}...")

        for line in range(1, total_lines + 1):
            try:
                r = await client.get(
                    f"{BASE_URL}/projects/{project_id}/synctex/forward",
                    params={"line": line, "column": 0},
                )
                if r.status_code == 404:
                    # No sync data for this line (e.g., blank line or comment)
                    continue
                r.raise_for_status()
                exact = r.json()

                interp = interpolate_position(entries, line)

                if exact["page"] != interp["page"]:
                    page_mismatches += 1
                    deviations.append({
                        "line": line,
                        "exact_page": exact["page"],
                        "interp_page": interp["page"],
                        "exact_y": exact["y"],
                        "interp_y": interp["y"],
                        "y_dev": None,
                        "page_mismatch": True,
                    })
                else:
                    y_dev = abs(exact["y"] - interp["y"])
                    deviations.append({
                        "line": line,
                        "exact_page": exact["page"],
                        "interp_page": interp["page"],
                        "exact_y": exact["y"],
                        "interp_y": interp["y"],
                        "y_dev": y_dev,
                        "page_mismatch": False,
                    })
            except Exception as e:
                errors += 1
                if errors <= 3:
                    print(f"  Error at line {line}: {e}")

            if line % 50 == 0:
                print(f"  ... line {line}/{total_lines}")

        # Statistics
        same_page = [d for d in deviations if not d["page_mismatch"]]
        y_devs = [d["y_dev"] for d in same_page if d["y_dev"] is not None]

        print(f"\n{'='*60}")
        print(f"ALIGNMENT VERIFICATION REPORT")
        print(f"{'='*60}")
        print(f"Total lines tested: {len(deviations)}")
        print(f"Lines with no sync data (skipped): {total_lines - len(deviations) - errors}")
        print(f"API errors: {errors}")
        print(f"Page mismatches: {page_mismatches}")

        if y_devs:
            avg_dev = sum(y_devs) / len(y_devs)
            max_dev = max(y_devs)
            median_dev = sorted(y_devs)[len(y_devs) // 2]
            within_14pt = sum(1 for d in y_devs if d <= 14)  # within one line height
            within_28pt = sum(1 for d in y_devs if d <= 28)  # within two line heights

            print(f"\nY-coordinate deviation (same page, PDF points):")
            print(f"  Average: {avg_dev:.1f} pt")
            print(f"  Median:  {median_dev:.1f} pt")
            print(f"  Max:     {max_dev:.1f} pt")
            print(f"  Within 1 line (14pt): {within_14pt}/{len(y_devs)} ({100*within_14pt/len(y_devs):.0f}%)")
            print(f"  Within 2 lines (28pt): {within_28pt}/{len(y_devs)} ({100*within_28pt/len(y_devs):.0f}%)")

            # Show worst deviations
            worst = sorted(same_page, key=lambda d: d["y_dev"] or 0, reverse=True)[:10]
            if worst:
                print(f"\nTop 10 worst deviations:")
                print(f"  {'Line':>5}  {'Page':>4}  {'Exact Y':>8}  {'Interp Y':>8}  {'Dev':>6}")
                for d in worst:
                    print(f"  {d['line']:>5}  {d['exact_page']:>4}  {d['exact_y']:>8.1f}  {d['interp_y']:>8.1f}  {d['y_dev']:>6.1f}")

        if page_mismatches > 0:
            mismatch_lines = [d for d in deviations if d["page_mismatch"]][:10]
            print(f"\nPage mismatch examples:")
            for d in mismatch_lines:
                print(f"  Line {d['line']}: exact page={d['exact_page']}, interp page={d['interp_page']}")

        print(f"\n{'='*60}")
        if y_devs and avg_dev < 14 and page_mismatches == 0:
            print("RESULT: GOOD — average deviation < 1 line height, no page mismatches")
        elif y_devs and avg_dev < 28:
            print("RESULT: ACCEPTABLE — average deviation < 2 line heights")
        else:
            print("RESULT: NEEDS IMPROVEMENT — significant deviations detected")
        print(f"{'='*60}")


if __name__ == "__main__":
    asyncio.run(main())
