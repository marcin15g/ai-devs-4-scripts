import os
#!/usr/bin/env python3
"""S03E05 – savethem: find optimal route for messenger to Skolwin.

Strategy:
1. Discover tools via toolsearch API
2. Get map of Skolwin from maps API
3. Get vehicle info from wehicles API
4. Get movement rules from books API
5. Find optimal path with BFS + resource analysis

Rules discovered:
- R (Rock): impassable for all
- T (Tree): passable, +0.2 fuel for powered vehicles (rocket/car)
- W (Water): only horse and walk can cross
- S = Start, G = Goal
- Vehicles: walk(0 fuel, 2.5 food), horse(0 fuel, 1.6 food), car(0.7 fuel, 1.0 food), rocket(1.0 fuel, 0.1 food)
- "dismount" command: switch from vehicle to walk mid-route

Solution: rocket to edge of water barrier (8 steps), dismount, walk across water (3 steps)
- Total food: 0.8 + 7.5 = 8.3
- Total fuel: 8.2 (includes +0.2 for tree tile at (4,2))

Answer: ["rocket", "up", "up", "up", "right", "right", "right", "right", "right", "dismount", "right", "right", "right"]
"""

import json, ssl
from collections import deque
from urllib.request import urlopen, Request

API_KEY = os.environ["AG3NTS_API_KEY"]
VERIFY_URL = "https://hub.ag3nts.org/verify"
BASE_URL = "https://hub.ag3nts.org"
SSL_CTX = ssl._create_unverified_context()


def post(url, payload):
    data = json.dumps(payload).encode()
    req = Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urlopen(req, context=SSL_CTX) as resp:
            body = resp.read().decode()
    except Exception as e:
        body = e.read().decode() if hasattr(e, "read") else str(e)
    return json.loads(body)


def toolsearch(query):
    return post(f"{BASE_URL}/api/toolsearch", {"apikey": API_KEY, "query": query})


def maps(query):
    return post(f"{BASE_URL}/api/maps", {"apikey": API_KEY, "query": query})


def wehicles(query):
    return post(f"{BASE_URL}/api/wehicles", {"apikey": API_KEY, "query": query})


def books(query):
    return post(f"{BASE_URL}/api/books", {"apikey": API_KEY, "query": query})


def bfs(grid, start, goal, blocked):
    """BFS shortest path, returns list of (row,col) or None."""
    rows, cols = len(grid), len(grid[0])
    queue = deque([(start, [start])])
    visited = {start}
    while queue:
        (r, c), path = queue.popleft()
        if (r, c) == goal:
            return path
        for dr, dc in [(-1,0),(1,0),(0,-1),(0,1)]:
            nr, nc = r+dr, c+dc
            if 0 <= nr < rows and 0 <= nc < cols and (nr,nc) not in visited and (nr,nc) not in blocked:
                visited.add((nr,nc))
                queue.append(((nr,nc), path+[(nr,nc)]))
    return None


def path_to_dirs(path):
    dirs = []
    for i in range(1, len(path)):
        pr, pc = path[i-1]
        nr, nc = path[i]
        if nr < pr: dirs.append("up")
        elif nr > pr: dirs.append("down")
        elif nc < pc: dirs.append("left")
        else: dirs.append("right")
    return dirs


def solve():
    # Get map
    map_data = maps("Skolwin")
    grid = [list(row) for row in map_data["map"]]
    ROWS, COLS = len(grid), len(grid[0])

    # Find start/goal and terrain sets
    start = goal = None
    rocks, water, trees = set(), set(), set()
    for r in range(ROWS):
        for c in range(COLS):
            cell = grid[r][c]
            if cell == 'S': start = (r, c)
            elif cell == 'G': goal = (r, c)
            elif cell == 'R': rocks.add((r, c))
            elif cell == 'W': water.add((r, c))
            elif cell == 'T': trees.add((r, c))

    print(f"Start: {start}, Goal: {goal}")

    # Check if motorized can reach goal (water barrier might block)
    rocket_path = bfs(grid, start, goal, rocks | water)
    horse_path = bfs(grid, start, goal, rocks)

    print(f"Rocket path (no water): {len(rocket_path)-1 if rocket_path else 'IMPOSSIBLE'} steps")
    print(f"Horse path (water ok): {len(horse_path)-1 if horse_path else 'IMPOSSIBLE'} steps")

    # Best strategy: rocket to last pre-water point, dismount, walk rest
    # Find split point on horse_path where rocket diverges
    if rocket_path:
        # Full rocket route
        steps = len(rocket_path) - 1
        tree_count = sum(1 for r,c in rocket_path[1:] if (r,c) in trees)
        fuel = steps * 1.0 + tree_count * 0.2
        food = steps * 0.1
        print(f"Rocket full: fuel={fuel:.1f}, food={food:.1f}")
        commands = ["rocket"] + path_to_dirs(rocket_path)
    else:
        # Rocket+dismount: find longest prefix reachable by rocket
        # Then walk the rest
        best_food = float('inf')
        best_commands = None

        for split in range(len(horse_path)):
            pre = horse_path[:split+1]
            post = horse_path[split:]

            # Check pre-path has no water (rocket safe)
            if any((r,c) in water for r,c in pre[1:]):
                break  # Can't extend rocket further

            pre_dirs = path_to_dirs(pre)
            post_dirs = path_to_dirs(post)

            tree_count = sum(1 for r,c in pre[1:] if (r,c) in trees)
            fuel = len(pre_dirs) * 1.0 + tree_count * 0.2
            food = len(pre_dirs) * 0.1 + len(post_dirs) * 2.5

            if food < best_food:
                best_food = food
                best_fuel = fuel
                if post_dirs:
                    best_commands = ["rocket"] + pre_dirs + ["dismount"] + post_dirs
                else:
                    best_commands = ["rocket"] + pre_dirs

        print(f"Best rocket+walk: fuel={best_fuel:.1f}, food={best_food:.1f}")
        commands = best_commands

    print(f"Commands: {commands}")

    # Submit
    result = post(VERIFY_URL, {
        "apikey": API_KEY,
        "task": "savethem",
        "answer": commands
    })
    print(f"Result: {result}")
    return commands


if __name__ == "__main__":
    solve()
