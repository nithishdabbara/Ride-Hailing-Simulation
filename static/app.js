// Fetch initial state, draw map, manage UI, and animate drivers
let state = {};
let canvas = document.getElementById("mapCanvas");
let ctx = canvas.getContext("2d");
let logBox = document.getElementById("log");
let driversIcons = {}; // driverId -> {node, x,y}

async function fetchState(){
  let res = await fetch("/api/state");
  state = await res.json();
  return state;
}

function log(msg){
  let t = new Date().toLocaleTimeString();
  logBox.textContent += `[${t}] ${msg}\n`;
  logBox.scrollTop = logBox.scrollHeight;
}

function populateLocationSelects(){
  const selects = ["driverLoc","passSrc","passDst"];
  selects.forEach(id => {
    let el = document.getElementById(id);
    el.innerHTML = "";
    for (let node in state.city_coords){
      let opt = document.createElement("option");
      opt.value = node; opt.textContent = node;
      el.appendChild(opt);
    }
  });
}

function drawMap(){
  ctx.clearRect(0,0,canvas.width,canvas.height);
  // draw edges
  for (let e of state.edges){
    let [u,v,w] = e;
    let [x1,y1] = state.city_coords[u];
    let [x2,y2] = state.city_coords[v];
    ctx.strokeStyle = "#999"; ctx.lineWidth=2;
    ctx.beginPath(); ctx.moveTo(x1,y1); ctx.lineTo(x2,y2); ctx.stroke();
    // weight label
    ctx.fillStyle = "#333"; ctx.font = "12px Arial";
    ctx.fillText(w.toString(), (x1+x2)/2 + 6, (y1+y2)/2 + 6);
  }
  // nodes
  for (let node in state.city_coords){
    let [x,y] = state.city_coords[node];
    ctx.fillStyle = "#50bfe6";
    ctx.beginPath(); ctx.arc(x,y,16,0,Math.PI*2); ctx.fill();
    ctx.fillStyle = "#fff"; ctx.font="bold 12px Arial";
    ctx.fillText(node, x-6, y+5);
  }
  // drivers
  driversIcons = {};
  for (let id in state.drivers){
    drawDriver(id, state.drivers[id]);
  }
}

function drawDriver(id, info){
  let node = info.loc;
  let [x,y] = state.city_coords[node];
  driversIcons[id] = {node, x, y};
  // small rectangle
  ctx.fillStyle = (info.status==="ontrip") ? "#ffb84d" : "#f4d03f";
  ctx.fillRect(x-10,y-12,20,20);
  ctx.fillStyle = "#000"; ctx.font = "11px Arial";
  ctx.fillText(id, x-8, y+4);
}

function renderDriversList(){
  let div = document.getElementById("driversList"); div.innerHTML = "";
  for (let id in state.drivers){
    let info = state.drivers[id];
    let avgRating = info.rating_count ? (info.rating_sum / info.rating_count).toFixed(2) : "N/A";
    let el = document.createElement("div"); el.className="driverTag";
    el.innerHTML = `<b>${id}</b> @ ${info.loc} — ₹${info.earnings.toFixed(2)} — Rating: ${avgRating} — ${info.status}`;
    div.appendChild(el);
  }
}

function renderRides(){
  let div = document.getElementById("ridesList"); div.innerHTML = "";
  for (let r of state.ride_history.slice().reverse()){
    let el = document.createElement("div"); el.className="driverTag";
    el.innerHTML = `<b>Ride ${r.ride_id}</b> ${r.passenger_id}: ${r.source}→${r.destination} — ₹${r.fare.toFixed(2)} — ${r.status}`;
    div.appendChild(el);
  }
}

async function refresh(){
  await fetchState();
  populateLocationSelects();
  drawMap();
  renderDriversList();
  renderRides();
  log("Refreshed state");
}

// Add driver
document.getElementById("addDriverBtn").onclick = async ()=>{
  let id = document.getElementById("driverId").value.trim();
  let loc = document.getElementById("driverLoc").value;
  if(!id){ alert("Enter driver id"); return; }
  let res = await fetch("/api/add_driver", {
    method:"POST", headers:{"Content-Type":"application/json"},
    body: JSON.stringify({driver_id:id, location:loc})
  });
  let j = await res.json();
  if(j.ok){ log(`Driver ${id} added at ${loc}`); await refresh(); }
  else alert(j.msg || "Failed");
};

// Request ride
document.getElementById("requestBtn").onclick = async ()=>{
  let pid = document.getElementById("passId").value.trim();
  let src = document.getElementById("passSrc").value;
  let dst = document.getElementById("passDst").value;
  if(!pid){ alert("Enter passenger id"); return; }
  let res = await fetch("/api/request_ride", {
    method:"POST", headers:{"Content-Type":"application/json"},
    body: JSON.stringify({passenger_id:pid, source:src, destination:dst})
  });
  let j = await res.json();
  if(j.ok){ log(`Request ${pid}: ${src}→${dst}`); await refresh(); }
  else alert(j.msg || "Failed");
};

// Assign next
document.getElementById("assignBtn").onclick = async ()=>{
  let res = await fetch("/api/assign_next", {method:"POST"});
  let j = await res.json();
  if(!j.ok){ alert(j.msg || "No assignment"); return; }
  let ride = j.ride;
  log(`Assigned Ride ${ride.ride_id} driver ${ride.driver_id} fare ₹${ride.fare.toFixed(2)}`);
  // animate driver along path
  animateDriverPath(ride.driver_id, ride.path);
  // poll for updates while trip runs
  (async function pollDuringTrip(){
    for(let i=0;i<Math.max(6, ride.path.length*2);i++){
      await new Promise(r=>setTimeout(r,500));
      await refresh(); // update positions
    }
  })();
};

// refresh
document.getElementById("refreshBtn").onclick = refresh;

// animate driver visually moving along nodes list
async function animateDriverPath(driverId, path){
  // move driver icon step by step
  for (let node of path){
    // small transition animation
    let [xTarget,yTarget] = state.city_coords[node];
    // redraw map each frame and place driver at target node directly (simple approach)
    await new Promise(r => setTimeout(r, 300)); // pause between steps
    // update drivers location locally so drawMap shows current
    if(state.drivers[driverId]) state.drivers[driverId].loc = node;
    drawMap();
  }
  log(`Driver ${driverId} finished path ${path.join("->")}`);
  // final refresh to get earnings/rating etc
  await refresh();
}

// initial load
refresh();
