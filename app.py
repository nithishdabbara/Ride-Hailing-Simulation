from flask import Flask, render_template, request, jsonify
import heapq
from collections import defaultdict, deque
import time
import threading

app = Flask(__name__)

# -------------------------
# City Graph (nodes + weighted edges)
# -------------------------
graph = defaultdict(list)
nodes = set()

def add_edge(u, v, w):
    graph[u].append((v, w))
    graph[v].append((u, w))
    nodes.add(u); nodes.add(v)

# sample map (you can extend)
edges = [
    ("A","B",4),("A","C",2),("B","D",5),
    ("C","D",8),("C","E",10),("D","E",2),
    ("B","F",3),("E","G",6),("F","G",7)
]
for u,v,w in edges:
    add_edge(u,v,w)

# coordinates for front-end map (x,y relative positions)
city_coords = {
    "A": [100,100],"B":[220,80],"C":[140,200],"D":[300,150],
    "E":[420,220],"F":[200,240],"G":[480,320]
}

# -------------------------
# Dijkstra (returns dist + parent)
# -------------------------
def dijkstra(start):
    dist = {n: float('inf') for n in nodes}
    parent = {n: None for n in nodes}
    dist[start] = 0
    pq = [(0, start)]
    while pq:
        d,u = heapq.heappop(pq)
        if d>dist[u]: continue
        for v,w in graph[u]:
            if dist[v] > d + w:
                dist[v] = d + w
                parent[v] = u
                heapq.heappush(pq, (dist[v], v))
    return dist, parent

def shortest_path(parent, target):
    path=[]
    node = target
    while node is not None:
        path.append(node)
        node = parent[node]
    return path[::-1]

# -------------------------
# System State
# -------------------------
drivers = {}   # driver_id -> {loc: node, earnings:float, rating_sum:int, rating_count:int, status: "idle"/"ontrip"}
requests_q = deque()  # passenger requests: (passenger_id, source, dest)
ride_history = []     # list of dicts for completed rides
next_ride_id = 1

# fare settings
BASE_FARE = 20.0
RATE_PER_KM = 10.0

# lock for thread safety if needed
state_lock = threading.Lock()

# -------------------------
# Helper functions
# -------------------------
def compute_distance_on_graph(path):
    # path: list of nodes [u,...,v], sum edge weights
    if not path or len(path)==1: return 0
    total = 0
    for i in range(len(path)-1):
        u=path[i]; v=path[i+1]
        # find w
        for neigh,w in graph[u]:
            if neigh==v:
                total += w; break
    return total

def compute_fare(distance):
    return round(BASE_FARE + distance * RATE_PER_KM, 2)

# -------------------------
# API Endpoints
# -------------------------
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/state")
def api_state():
    # return map coords, drivers state, pending requests, history summary
    with state_lock:
        return jsonify({
            "city_coords": city_coords,
            "edges": edges,
            "drivers": drivers,
            "pending_requests": list(requests_q),
            "ride_history": ride_history[-20:]  # last 20
        })

@app.route("/api/add_driver", methods=["POST"])
def api_add_driver():
    data = request.json
    driver_id = data.get("driver_id")
    loc = data.get("location")
    if driver_id is None or loc not in city_coords:
        return jsonify({"ok":False, "msg":"Invalid driver or location"}), 400
    with state_lock:
        drivers[driver_id] = {"loc":loc, "earnings":0.0, "rating_sum":0, "rating_count":0, "status":"idle"}
    return jsonify({"ok":True})

@app.route("/api/request_ride", methods=["POST"])
def api_request_ride():
    data = request.json
    pid = data.get("passenger_id")
    src = data.get("source")
    dst = data.get("destination")
    if pid is None or src not in city_coords or dst not in city_coords:
        return jsonify({"ok":False, "msg":"Invalid request"}), 400
    with state_lock:
        requests_q.append((pid, src, dst))
    return jsonify({"ok":True})

@app.route("/api/assign_next", methods=["POST"])
def api_assign_next():
    global next_ride_id
    with state_lock:
        if not requests_q:
            return jsonify({"ok":False, "msg":"No requests"}), 400
        passenger_id, source, destination = requests_q.popleft()
        # compute distances from source
        dist_from_src, _ = dijkstra(source)
        # build heap of (distance, driver_id)
        heap=[]
        for d_id,info in drivers.items():
            # only idle drivers
            if info["status"]!="idle": continue
            loc = info["loc"]
            dist = dist_from_src.get(loc, float('inf'))
            heapq.heappush(heap, (dist, d_id, loc))
        if not heap:
            # put request back, no available driver
            requests_q.appendleft((passenger_id, source, destination))
            return jsonify({"ok":False, "msg":"No available drivers right now"}), 400
        nearest_dist, assigned_driver, driver_loc = heapq.heappop(heap)
        # compute full route: driver -> passenger -> destination
        _, parent_from_driver = dijkstra(driver_loc)
        path_to_passenger = shortest_path(parent_from_driver, source)
        _, parent_from_source = dijkstra(source)
        path_to_dest = shortest_path(parent_from_source, destination)
        # combined path for animation: path_to_passenger (excluding source duplication) + path_to_dest
        combined_path = path_to_passenger + path_to_dest[1:]
        # compute numeric distance (sum of weights)
        total_distance = compute_distance_on_graph(combined_path)
        fare = compute_fare(total_distance)

        # mark driver as ontrip
        drivers[assigned_driver]["status"] = "ontrip"
        ride_id = next_ride_id; next_ride_id += 1

        # create ride entry in history when completed; for realism we'll simulate trip with a small thread
        ride_info = {
            "ride_id": ride_id,
            "passenger_id": passenger_id,
            "driver_id": assigned_driver,
            "source": source,
            "destination": destination,
            "path": combined_path,
            "distance": total_distance,
            "fare": fare,
            "status": "ongoing",
            "timestamp": time.time()
        }
        # store temporary so front can animate
        ride_history.append(ride_info)

        # start a thread to "simulate" the trip (update driver loc and finalize)
        def run_trip():
            # simulate travel time proportional to number of steps; here a simple sleep
            for node in combined_path:
                time.sleep(0.6)  # front-end will animate; backend sleeps to mimic time passing
            with state_lock:
                # update driver location and earnings
                drivers[assigned_driver]["loc"] = destination
                drivers[assigned_driver]["earnings"] += fare
                drivers[assigned_driver]["status"] = "idle"
                # update ride entry status
                for r in ride_history:
                    if r["ride_id"] == ride_id:
                        r["status"] = "completed"
                        r["completed_at"] = time.time()
                        break
        t = threading.Thread(target=run_trip, daemon=True)
        t.start()

        return jsonify({
            "ok": True,
            "ride": {
                "ride_id": ride_id,
                "driver_id": assigned_driver,
                "driver_loc": driver_loc,
                "path": combined_path,
                "distance": total_distance,
                "fare": fare
            }
        })

@app.route("/api/rate_ride", methods=["POST"])
def api_rate_ride():
    data = request.json
    ride_id = data.get("ride_id"); rating = data.get("rating", 0)
    if ride_id is None:
        return jsonify({"ok":False}), 400
    with state_lock:
        found = None
        for r in ride_history:
            if r["ride_id"] == ride_id:
                found = r; break
        if not found or found.get("status")!="completed":
            return jsonify({"ok":False, "msg":"Ride not completed or not found"}), 400
        d_id = found["driver_id"]
        drivers[d_id]["rating_sum"] += rating
        drivers[d_id]["rating_count"] += 1
    return jsonify({"ok":True})

if __name__ == "__main__":
    app.run(debug=True)
