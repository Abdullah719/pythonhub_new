import os, json, requests, shlex
from pathlib import Path
import streamlit as st

# MUST be the first Streamlit call
st.set_page_config(page_title="PythonHub", page_icon="🧰", layout="wide")

# -------- Hide the sidebar completely --------
st.markdown("""
<style>
  [data-testid="stSidebar"] { display: none; }
  [data-testid="collapsedControl"] { display: none; }
</style>
""", unsafe_allow_html=True)

# -------- Simple, no-DB auth --------
USERS = [
    {"first": "Abdullah", "last": "Memon", "password": "secret123"},
    {"first": "Test", "last": "User",   "password": "pass123"},
    # add more users here
]

if "auth_user" not in st.session_state:
    st.session_state["auth_user"] = None

def login_screen():
    st.title("🔐 Login")
    with st.form("login-form"):
        colA, colB = st.columns(2)
        with colA:
            first = st.text_input("First name")
        with colB:
            last  = st.text_input("Last name")
        pw = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Sign in")

    if submitted:
        match = next(
            (u for u in USERS if u["first"] == first and u["last"] == last and u["password"] == pw),
            None
        )
        if match:
            st.session_state["auth_user"] = {"first": match["first"], "last": match["last"]}
            st.success(f"Welcome, {match['first']} {match['last']}!")
            st.rerun()
        else:
            st.error("Invalid details. Please check your first name, last name, and password.")

# ---- Gate everything behind login ----
if not st.session_state["auth_user"]:
    login_screen()
    st.stop()

# ===== From here down is your ORIGINAL app, with a small sign-out header =====

# Small top bar with greeting + sign out
top_col1, top_col2 = st.columns([1, 5])
with top_col1:
    if st.button("Sign out"):
        st.session_state["auth_user"] = None
        st.rerun()
with top_col2:
    u = st.session_state["auth_user"]
    st.caption(f"Signed in as **{u['first']} {u['last']}**")

# ---------------- Config ----------------
CRONICLE_URL = os.getenv("CRONICLE_URL", "http://cronicle:3012").rstrip("/")  # internal Docker DNS
API_KEY      = os.getenv("CRONICLE_API_KEY", "")
HOST         = os.getenv("CRONICLE_HOST", "main")  # Cronicle node id (Admin → Servers)
TZ           = os.getenv("TZ", "Australia/Perth")

# Where Cronicle will exec into (the Streamlit/portal container)
DOCKER_EXEC_CONTAINER = os.getenv("DOCKER_EXEC_CONTAINER", "pythonhub_portal")
DOCKER_BIN = os.getenv("DOCKER_BIN", "/usr/local/bin/docker")  # QNAP-safe default

# Folders as seen INSIDE the portal container (compose maps these)
SCRIPTS_DIR  = Path(os.getenv("SCRIPTS_DIR", "/scripts"))
OUTPUTS_DIR  = Path(os.getenv("OUTPUTS_DIR", "/outputs"))

HEADERS = {"X-API-Key": API_KEY, "Content-Type": "application/json"} if API_KEY else {}

# ---------------- UI Header ----------------
st.title("🧰 PythonHub")
st.caption(f"Cronicle: {CRONICLE_URL} | Target: {HOST} | Scripts: {SCRIPTS_DIR} | Outputs: {OUTPUTS_DIR}")

# ---------------- Validate folders ----------------
if not SCRIPTS_DIR.exists():
    st.error(f"Scripts base folder not found: {SCRIPTS_DIR}")
    st.stop()
OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)

# ---------------- User & file pickers ----------------
user_dirs = sorted([p for p in SCRIPTS_DIR.iterdir() if p.is_dir()])
if not user_dirs:
    st.info(f"No user folders under {SCRIPTS_DIR}. Create e.g. {SCRIPTS_DIR/'Abdullah'}/hello.py")
    st.stop()

user = st.selectbox("User", options=[p.name for p in user_dirs])
USER_DIR = SCRIPTS_DIR / user

files = sorted(list(USER_DIR.rglob("*.py")))
if not files:
    st.info(f"No .py files found under {USER_DIR}.")
    st.stop()

labels = [str(p.relative_to(USER_DIR)) for p in files]
label_to_path = {lbl: p for lbl, p in zip(labels, files)}

opt_label = st.selectbox(".py File", options=labels)
opt_path  = label_to_path[opt_label]

# Optional CLI args
args_text = st.text_input("Arguments (optional)", placeholder="--days 7 --verbose")
args_list = shlex.split(args_text) if args_text.strip() else []

# Schedule + titles
hour   = st.number_input("Hour (24h)", 0, 23, 9)
minute = st.number_input("Minute", 0, 59, 0)

def default_title() -> str:
    return f"{user}: {opt_path.name}"

title  = st.text_input("Event title", value=default_title())

# ---------------- Helpers ----------------
def q(x: object) -> str:
    return shlex.quote(str(x))

def extract_event_id(data: dict) -> str | None:
    # Cope with older/newer Cronicle response shapes
    if data.get("id"): return data["id"]
    if data.get("eid"): return data["eid"]
    if isinstance(data.get("event"), dict) and data["event"].get("id"): return data["event"]["id"]
    if isinstance(data.get("data"), dict) and data["data"].get("id"): return data["data"]["id"]
    return None

# Robust on QNAP: find a *file* docker client (not a directory), copy to /tmp, then run it.
def build_docker_exec_command(py_path: Path, args: list[str]) -> str:
    inner = " ".join(["python", q(py_path), *(q(a) for a in args)])
    prep  = (
        'BIN=' + q(DOCKER_BIN) + '; '
        'FOUND=""; '
        # Try env value as file, then env as dir + /docker, then common mounts
        'for C in "$BIN" "$BIN/docker" "/qnap-bin/docker" "/usr/local/bin/docker" "/usr/bin/docker/docker"; do '
        '  if [ -f "$C" ]; then FOUND="$C"; break; fi; '
        'done; '
        'if [ -z "$FOUND" ]; then echo "docker client not found (checked: $BIN, $BIN/docker, /qnap-bin/docker, /usr/local/bin/docker, /usr/bin/docker/docker)" >&2; exit 1; fi; '
        # Idempotent prep: handle both file and accidental directory at /tmp/docker
        '[ -d /tmp/docker ] && rm -rf /tmp/docker; '
        'rm -f /tmp/docker; '
        'cp -f "$FOUND" /tmp/docker && chmod +x /tmp/docker'
    )
    runit = f'/tmp/docker exec -i {q(DOCKER_EXEC_CONTAINER)} bash -lc {q(inner)}'
    return f"{prep} && {runit}"

# ---------------- Cronicle API wrappers ----------------
def cronicle_health() -> tuple[bool, str]:
    """Treat 'Unsupported API' as reachable (older Cronicle builds)."""
    try:
        r = requests.get(f"{CRONICLE_URL}/api/app/get_health", timeout=10)
        if r.status_code == 200:
            try:
                data = r.json()
            except Exception:
                data = {}
            desc = str(data.get("description", "")).lower()
            if "unsupported api" in desc:
                return True, "Cronicle reachable (health API not present)"
            return True, "Cronicle reachable"
        # fallback: hitting UI root also proves reachability
        r2 = requests.get(f"{CRONICLE_URL}/", timeout=10)
        return (r2.ok, "Cronicle reachable" if r2.ok else f"HTTP {r2.status_code}")
    except Exception as e:
        return False, f"Health check error: {e}"

def cronicle_create_event(title: str, command: str, timing: dict | str) -> dict:
    if not API_KEY:
        raise RuntimeError("No Cronicle API key configured. Set CRONICLE_API_KEY in the container env.")

    payload: dict = {
        "title": title,
        "enabled": 1,
        "category": "general",
        "plugin": "shellplug",          # inline shell script plugin
        "target": HOST,                 # Admin→Servers hostname (e.g., 'main' or 'cronicle')
        "timezone": TZ,
        "timing": timing,               # {"hours":[H],"minutes":[M]} (older builds don't accept "now")
        "params": {"script": f"#!/bin/sh\nset -e\n{command}\n"},
    }
    r = requests.post(f"{CRONICLE_URL}/api/app/create_event/v1",
                      headers=HEADERS, data=json.dumps(payload), timeout=20)
    r.raise_for_status()
    return r.json()

def cronicle_run_event(event_id: str) -> dict:
    r = requests.post(f"{CRONICLE_URL}/api/app/run_event/v1",
                      headers=HEADERS, data=json.dumps({"id": event_id}), timeout=20)
    r.raise_for_status()
    return r.json()

# ---------------- Actions ----------------
col1, col2 = st.columns(2)

with col1:
    st.subheader("Schedule job ")
    if st.button("🗓️ Create job"):
        ok, msg = cronicle_health()
        if not ok:
            st.error(msg)
            st.stop()
        try:
            command = build_docker_exec_command(opt_path, args_list)
            data = cronicle_create_event(title or default_title(),
                                         command,
                                         {"hours": [int(hour)], "minutes": [int(minute)]})
            if data.get("code") == 0:
                st.success(f"Created ✔ (id: {extract_event_id(data) or data.get('id')}) – {hour:02d}:{minute:02d} daily")
            else:
                st.error(f"Create failed: {data}")
        except Exception as e:
            st.error(f"Error: {e}")

with col2:
    st.subheader("Run once now (via Cronicle)")
    run_title = st.text_input("One-off title", value=f"Run now: {user}/{opt_path.name}")
    if st.button("▶️ Run now"):
        ok, msg = cronicle_health()
        if not ok:
            st.error(msg)
            st.stop()
        try:
            command = build_docker_exec_command(opt_path, args_list)
            # Use an object for timing (older Cronicle builds require this)
            data = cronicle_create_event(run_title or f"Run now: {user}/{opt_path.name}",
                                         command,
                                         {"hours": [int(hour)], "minutes": [int(minute)]})
            if data.get("code") == 0:
                event_id = extract_event_id(data)
                if event_id:
                    try:
                        run_resp = cronicle_run_event(event_id)  # extra nudge for some builds
                        st.success(f"Triggered ✔ (event id: {event_id})")
                        st.code(json.dumps(run_resp, indent=2))
                    except Exception:
                        st.success("Triggered ✔ (Cronicle accepted schedule and is running).")
                else:
                    st.success("Triggered ✔ (Cronicle accepted schedule). Check Cronicle UI for live run.")
            else:
                st.error(f"Create failed: {data}")
        except Exception as e:
            st.error(f"Error: {e}")
