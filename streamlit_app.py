import streamlit as st
import pandas as pd
from datetime import datetime

# Set page configuration
st.set_page_config(page_title="Scheduling Dashboard", layout="wide")

# Mock data for Teacher Availability
teacher_availability = [
    {"name": "Alice", "status": "Available", "slots": ["09:00", "10:00", "11:00"]},
    {"name": "Bob", "status": "Busy", "slots": ["09:00"]},
    {"name": "Charlie", "status": "Available", "slots": ["10:00", "12:00"]},
    {"name": "Diana", "status": "Available", "slots": ["09:00", "11:00", "13:00"]},
    {"name": "Edward", "status": "Busy", "slots": ["11:00"]}
]

# Initialize session state for Activity Log
if 'activity_log' not in st.session_state:
    st.session_state.activity_log = []

def log_activity(message):
    timestamp = datetime.now().strftime("%H:%M:%S")
    st.session_state.activity_log.insert(0, f"[{timestamp}] {message}")

def get_available_teachers(slot):
    return [t['name'] for t in teacher_availability if t['status'] == 'Available' and slot in t['slots']]

# Sidebar - User Inputs
st.sidebar.header("Configuration")

class_name = st.sidebar.text_input("Class Name", value="Physics 101")
start_time = st.sidebar.time_input("Start Time", value=datetime.strptime("09:00", "%H:%M").time())
daily_repeat = st.sidebar.toggle("Daily Repeat", value=True)

# Format time for logic
time_slot = start_time.strftime("%H:%M")

# Trigger logging on input changes (Streamlit reruns on change)
# We can use keys in session state to track changes if needed, but for this simple dashboard
# we can just log the current state.
if st.sidebar.button("Update Schedule"):
    log_activity(f"Updated schedule for {class_name} at {time_slot}")

st.sidebar.markdown("---")
st.sidebar.header("Activity Log")
log_container = st.sidebar.container(height=300)
with log_container:
    for log in st.session_state.activity_log:
        st.write(log)

# Main Panel - Output
st.title("Weekly Time Table")

# Create a sample weekly timetable
days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
slots = ["09:00", "10:00", "11:00", "12:00", "13:00", "14:00"]

# Initialize or generate the table data
data = {}
for day in days:
    day_classes = []
    for slot in slots:
        if slot == time_slot:
            if daily_repeat or day == "Monday": # Simple logic for daily vs single day
                day_classes.append(class_name)
            else:
                day_classes.append("FREE")
        else:
            day_classes.append("FREE")
    data[day] = day_classes

df = pd.DataFrame(data, index=slots)

st.subheader("Current Timetable")
st.dataframe(df, use_container_width=True)

# Replacement Section
st.markdown("---")
st.subheader("Teacher Replacement Finder")
col1, col2 = st.columns(2)

with col1:
    search_slot = st.selectbox("Select Time Slot to find Replacement", slots, index=slots.index(time_slot) if time_slot in slots else 0)

with col2:
    available = get_available_teachers(search_slot)
    if available:
        st.success(f"Available Teachers at {search_slot}:")
        for name in available:
            st.write(f"- {name}")
    else:
        st.error(f"No teachers available at {search_slot}")

# Implementation note: In Streamlit, every time an input changes, the script reruns.
# So the table and the replacement list update immediately.
