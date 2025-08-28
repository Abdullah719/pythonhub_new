# pages/00_Login.py
import streamlit as st

st.set_page_config(page_title="PythonHub • Login", page_icon="🔐")
st.title("🔐 Login")

# Hard-coded users (replace with your own)
USERS = [
    {"first": "Abdullah", "last": "Memon", "password": "secret123"},
    {"first": "Test", "last": "User", "password": "pass123"},
]

# Keep logged-in user in session
if "auth_user" not in st.session_state:
    st.session_state["auth_user"] = None

with st.form("login"):
    first = st.text_input("First name")
    last  = st.text_input("Last name")
    pw    = st.text_input("Password", type="password")
    submit = st.form_submit_button("Sign in")

if submit:
    match = next((u for u in USERS if u["first"] == first and u["last"] == last and u["password"] == pw), None)
    if match:
        st.session_state["auth_user"] = {"first": match["first"], "last": match["last"]}
        st.success(f"Welcome, {match['first']} {match['last']}!")
        try: 
            st.switch_page("app.py")  # requires Streamlit >= 1.22-ish
        except Exception:
            st.rerun()  # fallback (you may still need to click the page)
    else:
        st.error("Invalid details.")

