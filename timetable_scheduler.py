import tkinter as tk
from tkinter import messagebox
import ttkbootstrap as tb
from ttkbootstrap.constants import *
from ttkbootstrap.scrolled import ScrolledFrame
import random
from datetime import datetime, timedelta

# ---------------- helpers ----------------
def add_time(start, minutes):
    """Adds minutes to a time string (HH:MM) and returns the new time string."""
    t = datetime.strptime(start, "%H:%M")
    t += timedelta(minutes=minutes)
    return t.strftime("%H:%M")

def to_upper_list(s):
    """Converts a comma-separated string to a list of stripped, uppercased items."""
    if isinstance(s, str):
        return [item.strip().upper() for item in s.split(",") if item.strip()]
    return []

def valid_time(s):
    """Checks if a string is a valid time format (HH:MM)."""
    try:
        datetime.strptime(s, "%H:%M")
        return True
    except ValueError:
        return False

# ---------------- Scheduler engine ----------------
def get_current_day_usage(timetable, day, sections, slots_count, teacher_data):
    """Helper to recalculate usage and booked slots for a given day."""
    usage = {t: 0 for t in teacher_data}
    booked = {t: set() for t in teacher_data}

    for sec in sections:
        for s in range(slots_count):
            val = timetable[day][sec][s]
            if "(" in val and ")" in val:
                try:
                    tname = val.split("(")[-1].split(")")[0].strip()
                    if tname in usage:
                        usage[tname] += 1
                        booked[tname].add(s)
                except:
                    pass
    return usage, booked


def build_timetable(sections, teacher_data, load_per_day, days, slot_times, tech_subject="TECH"):
    """
    Generates a randomized timetable based on constraints (including strict gap rule)
    and **respects teacher-section mapping for ALL subjects**.
    """
    slots_count = len(slot_times)
    timetable = {day: {sec: ["FREE"] * slots_count for sec in sections} for day in days}

    for day in days:
        usage = {t: 0 for t in teacher_data}
        booked = {t: set() for t in teacher_data}

        # 1) Assign TECH first (Always a double period)
        tech_teachers = [t for t in teacher_data if teacher_data[t]["subject"] == tech_subject]
        random.shuffle(tech_teachers)

        secs_order = sections.copy()
        random.shuffle(secs_order)

        for sec in secs_order:
            candidates = [t for t in tech_teachers if teacher_data[t]["allowed_sections"] and sec in teacher_data[t]["allowed_sections"]]

            if not candidates:
                continue
            random.shuffle(candidates)
            placed = False

            for cand in candidates:
                remaining = load_per_day - usage[cand]
                if remaining < 2:
                    continue

                for i in range(0, slots_count - 1):
                    if slot_times[i].upper() == "LUNCH" or slot_times[i+1].upper() == "LUNCH":
                        continue
                    if timetable[day][sec][i] != "FREE" or timetable[day][sec][i+1] != "FREE":
                        continue

                    if i in booked[cand] or (i+1) in booked[cand]:
                        continue

                    timetable[day][sec][i] = f"{tech_subject} ({cand})"
                    timetable[day][sec][i+1] = f"{tech_subject} ({cand})"

                    usage[cand] += 2
                    booked[cand].add(i); booked[cand].add(i+1)
                    placed = True
                    break
                if placed:
                    break

        for i in range(slots_count):
            if slot_times[i].upper() == "LUNCH":
                for sec in sections:
                    timetable[day][sec][i] = "LUNCH"
                continue

            usage, booked = get_current_day_usage(timetable, day, sections, slots_count, teacher_data)

            secs_slot_order = sections.copy()
            random.shuffle(secs_slot_order)

            for sec in secs_slot_order:
                if timetable[day][sec][i] != "FREE":
                    continue

                eligible = []
                for tname, info in teacher_data.items():
                    subj = info["subject"]
                    if subj == tech_subject:
                        continue

                    if info["allowed_sections"] and sec not in info["allowed_sections"]:
                        continue

                    if usage[tname] >= load_per_day:
                        continue

                    if i in booked[tname]:
                        continue

                    if any(abs(i - s) < 3 for s in booked[tname]):
                        continue

                    eligible.append(tname)

                if not eligible:
                    timetable[day][sec][i] = "FREE"
                    continue

                min_used = min(usage[t] for t in eligible)
                candidates = [t for t in eligible if usage[t] == min_used]
                chosen = random.choice(candidates)
                subj = teacher_data[chosen]["subject"]

                timetable[day][sec][i] = f"{subj} ({chosen})"
                usage[chosen] += 1
                booked[chosen].add(i)

    return timetable

def fill_remaining_free_slots(timetable, teacher_data, load_per_day, slot_times, tech_subject="TECH"):
    """
    Arrangement Pass: Attempts to fill any remaining 'FREE' slots by finding an available teacher.
    Relaxes the gap rule constraint but respects load, collision, and **section mapping** rules.
    """
    days = list(timetable.keys())
    sections = list(next(iter(timetable.values())).keys()) if timetable and next(iter(timetable.values())) else []
    slots_count = len(slot_times)

    for day in days:
        usage, booked = get_current_day_usage(timetable, day, sections, slots_count, teacher_data)

        for sec in sections:
            for i in range(slots_count):
                if timetable[day][sec][i] == "FREE":

                    eligible = []
                    for tname, info in teacher_data.items():
                        subj = info["subject"]
                        if subj == tech_subject:
                            continue

                        if info["allowed_sections"] and sec not in info["allowed_sections"]:
                            continue

                        if usage[tname] >= load_per_day:
                            continue

                        if i in booked[tname]:
                            continue

                        eligible.append(tname)

                    if eligible:
                        min_used = min(usage[t] for t in eligible)
                        candidates = [t for t in eligible if usage[t] == min_used]
                        chosen = random.choice(candidates)
                        subj = teacher_data[chosen]["subject"]

                        timetable[day][sec][i] = f"{subj} ({chosen})"
                        usage[chosen] += 1
                        booked[chosen].add(i)

    return timetable

def substitute_absent(timetable, day, absent_teacher, teacher_data, load_per_day, slot_times):
    """
    Finds slots where absent_teacher was assigned on 'day' and replaces them with an available teacher.
    """
    sections = list(timetable[day].keys())
    slots_count = len(slot_times)

    usage, booked = get_current_day_usage(timetable, day, sections, slots_count, teacher_data)

    for sec in sections:
        for i in range(slots_count):
            val = timetable[day][sec][i]
            if f"({absent_teacher})" in val:
                original_subject = val.split("(")[0].strip()
                timetable[day][sec][i] = "FREE"

                if absent_teacher in usage:
                    usage[absent_teacher] -= 1
                    booked[absent_teacher].discard(i)

                eligible = []
                for tname, info in teacher_data.items():
                    if tname == absent_teacher:
                        continue

                    if info["allowed_sections"] and sec not in info["allowed_sections"]:
                        continue

                    if usage[tname] >= load_per_day:
                        continue

                    if i in booked[tname]:
                        continue

                    eligible.append(tname)

                if eligible:
                    same_subject = [t for t in eligible if teacher_data[t]["subject"] == original_subject]
                    if same_subject:
                        chosen = random.choice(same_subject)
                    else:
                        chosen = random.choice(eligible)

                    subj = teacher_data[chosen]["subject"]
                    timetable[day][sec][i] = f"{subj} ({chosen}) [SUB]"
                    usage[chosen] += 1
                    booked[chosen].add(i)
                else:
                    timetable[day][sec][i] = "FREE"

def build_replacement_suggestions(timetable, teacher_data, load_per_day, slot_times):
    """
    Returns a list of suggestions for ALL assigned slots in the timetable.
    """
    days = list(timetable.keys())
    sections = list(next(iter(timetable.values())).keys()) if timetable else []
    slots_count = len(slot_times)

    suggestions = []

    for day in days:
        usage, booked = get_current_day_usage(timetable, day, sections, slots_count, teacher_data)

        for sec in sections:
            for i in range(slots_count):
                val = timetable[day][sec][i]
                if val == "FREE" or val == "LUNCH":
                    continue

                try:
                    parts = val.split("(")
                    subj = parts[0].strip()
                    assigned_teacher = parts[1].split(")")[0].strip()
                except:
                    continue

                candidates = []
                for tname, info in teacher_data.items():
                    if tname == assigned_teacher:
                        continue

                    if info["allowed_sections"] and sec not in info["allowed_sections"]:
                        continue

                    if i in booked[tname]:
                        continue

                    if usage[tname] < load_per_day:
                        candidates.append(tname)

                if candidates:
                    suggestions.append({
                        "day": day,
                        "slot_label": slot_times[i],
                        "section": sec,
                        "subject": subj,
                        "assigned_teacher": assigned_teacher,
                        "candidates": candidates
                    })

    return suggestions

# ---------------- UI Redesign ----------------
class App:
    def __init__(self, root):
        self.root = root
        self.style = tb.Style(theme="flatly")
        self.root.title("Modern Timetable Scheduler Pro")
        self.root.geometry("1400x900")

        # Application Colors
        self.colors = self.style.colors

        self._last_timetable = None
        self._last_teacher_data = {}
        self._last_load = 4
        self._last_slot_times = []

        self.build_ui()

    def build_ui(self):
        # Top Navigation Bar
        navbar = tb.Frame(self.root, bootstyle=PRIMARY)
        navbar.pack(side=TOP, fill=X)

        title_lbl = tb.Label(navbar, text="📅 Timetable Scheduler Pro", font=("Segoe UI", 18, "bold"), bootstyle=INVERSE)
        title_lbl.pack(side=LEFT, padx=20, pady=10)

        self.theme_btn = tb.Checkbutton(navbar, text="Dark Mode", bootstyle="round-toggle", command=self.toggle_theme)
        self.theme_btn.pack(side=RIGHT, padx=20)

        # Main Container
        main_container = tb.Frame(self.root)
        main_container.pack(fill=BOTH, expand=True)

        # Left Sidebar for Controls
        self.sidebar = tb.Frame(main_container, bootstyle=SECONDARY, width=400)
        self.sidebar.pack(side=LEFT, fill=Y, padx=0, pady=0)
        self.sidebar.pack_propagate(False)

        # Use a scrolled frame for sidebar if it gets long
        self.sidebar_scroll = ScrolledFrame(self.sidebar, bootstyle=SECONDARY, autohide=True)
        self.sidebar_scroll.pack(fill=BOTH, expand=True)

        self.build_sidebar_content()

        # Right Display Area
        self.display_area = tb.Frame(main_container)
        self.display_area.pack(side=RIGHT, fill=BOTH, expand=True, padx=10, pady=10)

        self.build_display_placeholder()

    def build_sidebar_content(self):
        # Configuration Card
        cfg_card = tb.LabelFrame(self.sidebar_scroll, text="General Configuration", padding=15)
        cfg_card.pack(fill=X, padx=10, pady=10)

        tb.Label(cfg_card, text="Sections (comma):").pack(anchor=W)
        self.sections_var = tk.StringVar(value="4A,4B,4C,4D")
        tb.Entry(cfg_card, textvariable=self.sections_var).pack(fill=X, pady=(0, 10))

        tb.Label(cfg_card, text="Days (comma):").pack(anchor=W)
        self.days_var = tk.StringVar(value="Monday,Tuesday,Wednesday,Thursday,Friday,Saturday")
        tb.Entry(cfg_card, textvariable=self.days_var).pack(fill=X, pady=(0, 10))

        # Time/Load Frame
        row2 = tb.Frame(cfg_card)
        row2.pack(fill=X)

        f1 = tb.Frame(row2)
        f1.pack(side=LEFT, fill=X, expand=True)
        tb.Label(f1, text="Duration (min):").pack(anchor=W)
        self.duration_var = tk.IntVar(value=45)
        tb.Entry(f1, textvariable=self.duration_var).pack(fill=X, padx=(0, 5))

        f2 = tb.Frame(row2)
        f2.pack(side=LEFT, fill=X, expand=True)
        tb.Label(f2, text="Load per day:").pack(anchor=W)
        self.load_var = tk.IntVar(value=4)
        tb.Entry(f2, textvariable=self.load_var).pack(fill=X, padx=(5, 0))

        row3 = tb.Frame(cfg_card)
        row3.pack(fill=X, pady=(10, 0))

        f3 = tb.Frame(row3)
        f3.pack(side=LEFT, fill=X, expand=True)
        tb.Label(f3, text="Start (HH:MM):").pack(anchor=W)
        self.start_var = tk.StringVar(value="09:00")
        tb.Entry(f3, textvariable=self.start_var).pack(fill=X, padx=(0, 5))

        f4 = tb.Frame(row3)
        f4.pack(side=LEFT, fill=X, expand=True)
        tb.Label(f4, text="Lunch (HH:MM):").pack(anchor=W)
        self.lunch_var = tk.StringVar(value="12:30")
        tb.Entry(f4, textvariable=self.lunch_var).pack(fill=X, padx=(5, 0))

        # Teacher Management Card
        teach_card = tb.LabelFrame(self.sidebar_scroll, text="Teachers Management", padding=15)
        teach_card.pack(fill=X, padx=10, pady=10)

        tb.Label(teach_card, text="Name | Subject | Sections", font=("Segoe UI", 8, "italic")).pack(anchor=W)
        self.rows_container = tb.Frame(teach_card)
        self.rows_container.pack(fill=X)

        self.teacher_vars = []

        # Initial rows
        self.add_teacher_row("SUDHAKAR","TECH","4A,4D")
        self.add_teacher_row("RITIK","TECH","4C,4B")
        self.add_teacher_row("RAHUL","APTI","4A,4D")
        self.add_teacher_row("RAJEEV","HINDI","4D,4C")

        tb.Button(teach_card, text="➕ Add Teacher", bootstyle=OUTLINE, command=lambda: self.add_teacher_row()).pack(fill=X, pady=10)

        # Actions Card
        actions_card = tb.LabelFrame(self.sidebar_scroll, text="Substitution & Actions", padding=15)
        actions_card.pack(fill=X, padx=10, pady=10)

        tb.Label(actions_card, text="Absent Teacher:").pack(anchor=W)
        self.absent_combo = tb.Combobox(actions_card, values=[])
        self.absent_combo.pack(fill=X, pady=(0, 10))

        tb.Label(actions_card, text="Absent Day:").pack(anchor=W)
        self.absent_day = tb.Combobox(actions_card, values=[])
        self.absent_day.pack(fill=X, pady=(0, 10))

        tb.Button(actions_card, text="🔄 Update Lists", bootstyle=INFO, command=self.update_absent_list).pack(fill=X, pady=5)
        tb.Button(actions_card, text="🚀 Generate Timetable", bootstyle=SUCCESS, command=self.on_generate).pack(fill=X, pady=5)
        tb.Button(actions_card, text="🔍 Show Suggestions", bootstyle=SECONDARY, command=self.on_show_replacements).pack(fill=X, pady=5)
        tb.Button(actions_card, text="🧹 Reset All", bootstyle=DANGER, command=self.reset_all).pack(fill=X, pady=5)

    def add_teacher_row(self, name="", subj="", allowed=""):
        row_frame = tb.Frame(self.rows_container)
        row_frame.pack(fill=X, pady=2)

        name_var = tk.StringVar(value=name)
        subj_var = tk.StringVar(value=subj)
        allowed_var = tk.StringVar(value=allowed)

        tb.Entry(row_frame, textvariable=name_var, width=10).pack(side=LEFT, fill=X, expand=True, padx=1)
        tb.Entry(row_frame, textvariable=subj_var, width=8).pack(side=LEFT, fill=X, expand=True, padx=1)
        tb.Entry(row_frame, textvariable=allowed_var, width=12).pack(side=LEFT, fill=X, expand=True, padx=1)

        btn = tb.Button(row_frame, text="×", bootstyle=(DANGER, OUTLINE), width=2, command=lambda: self.remove_teacher_row(row_frame, (name_var, subj_var, allowed_var)))
        btn.pack(side=LEFT, padx=2)

        self.teacher_vars.append((name_var, subj_var, allowed_var))
        self.update_absent_list()

    def remove_teacher_row(self, frame, vars_tuple):
        frame.destroy()
        if vars_tuple in self.teacher_vars:
            self.teacher_vars.remove(vars_tuple)
        self.update_absent_list()

    def reset_all(self):
        if messagebox.askyesno("Confirm Reset", "Are you sure you want to clear all data?"):
            for frame in self.rows_container.winfo_children():
                frame.destroy()
            self.teacher_vars = []
            self.build_display_placeholder()
            self._last_timetable = None

    def toggle_theme(self):
        if self.theme_btn.instate(['selected']):
            self.style.theme_use("darkly")
        else:
            self.style.theme_use("flatly")

    def build_display_placeholder(self):
        for w in self.display_area.winfo_children():
            w.destroy()

        placeholder = tb.Label(self.display_area, text="Configure inputs and click\n'Generate Timetable' to begin", font=("Segoe UI", 16), justify=CENTER, bootstyle=SECONDARY)
        placeholder.pack(expand=True)

    def update_absent_list(self):
        names = sorted(list(set([v[0].get().strip().upper() for v in self.teacher_vars if v[0].get().strip()])))
        self.absent_combo["values"] = names

        days = to_upper_list(self.days_var.get())
        self.absent_day["values"] = days

    def collect_inputs(self):
        try:
            sections = to_upper_list(self.sections_var.get())
            days = to_upper_list(self.days_var.get())

            if not sections or not days:
                messagebox.showerror("Error", "Sections and days are required.")
                return None

            duration = int(self.duration_var.get())
            load = int(self.load_var.get())
            start = self.start_var.get().strip()
            lunch = self.lunch_var.get().strip()

            if not valid_time(start) or not valid_time(lunch):
                messagebox.showerror("Error", "Start and lunch times must be HH:MM format.")
                return None

        except ValueError as e:
            messagebox.showerror("Error", f"Invalid numeric input: {e}")
            return None

        slot_times = []
        cur = start
        for _ in range(4):
            end = add_time(cur, duration)
            slot_times.append(f"{cur}-{end}")
            cur = end
        slot_times.append("LUNCH")

        try:
            lunch_dt = datetime.strptime(lunch, "%H:%M")
            next_start = (lunch_dt + timedelta(minutes=55)).strftime("%H:%M")
            cur = next_start
        except ValueError:
            return None

        for _ in range(2):
            end = add_time(cur, duration)
            slot_times.append(f"{cur}-{end}")
            cur = end

        teacher_data = {}
        for name_var, subj_var, allowed_var in self.teacher_vars:
            name = name_var.get().strip().upper()
            subj = subj_var.get().strip().upper()
            allowed = to_upper_list(allowed_var.get())
            if not name or not subj: continue
            teacher_data[name] = {"subject": subj, "allowed_sections": allowed if allowed else None}

        if not teacher_data:
            messagebox.showerror("Error", "No teacher data provided.")
            return None

        absent_name = self.absent_combo.get().strip().upper() if self.absent_combo.get().strip() else None
        absent_day = self.absent_day.get().strip() if self.absent_day.get().strip() else None
        absent_info = (absent_name, absent_day) if absent_name and absent_day in days else None

        return {
            "sections": sections,
            "teacher_data": teacher_data,
            "load": load,
            "days": days,
            "slot_times": slot_times,
            "absent": absent_info
        }

    def on_generate(self):
        inputs = self.collect_inputs()
        if not inputs: return

        timetable = build_timetable(inputs["sections"], inputs["teacher_data"], inputs["load"], inputs["days"], inputs["slot_times"])
        timetable = fill_remaining_free_slots(timetable, inputs["teacher_data"], inputs["load"], inputs["slot_times"])

        if inputs["absent"]:
            absent_name, absent_day = inputs["absent"]
            substitute_absent(timetable, absent_day, absent_name, inputs["teacher_data"], inputs["load"], inputs["slot_times"])

        self._display_timetable(timetable, inputs["sections"], inputs["days"], inputs["slot_times"])

        self._last_timetable = timetable
        self._last_teacher_data = inputs["teacher_data"]
        self._last_load = inputs["load"]
        self._last_slot_times = inputs["slot_times"]

    def _display_timetable(self, timetable, sections, days, slot_times):
        for w in self.display_area.winfo_children():
            w.destroy()

        # Container with Scrollbar
        scroll_container = ScrolledFrame(self.display_area, autohide=True)
        scroll_container.pack(fill=BOTH, expand=True)

        inner = tb.Frame(scroll_container)
        inner.pack(fill=BOTH, expand=True, padx=10, pady=10)

        # Legend Bar
        legend = tb.Frame(inner)
        legend.pack(fill=X, pady=(0, 20))

        marks = [
            ("LECTURE", "#3498db", "inverse-primary"),
            ("LUNCH", "#95a5a6", "inverse-secondary"),
            ("FREE", "#ecf0f1", "inverse-light"),
            ("SUBSTITUTE", "#2ecc71", "inverse-success")
        ]

        for text, color, bstyle in marks:
            lbl = tb.Label(legend, text=text, bootstyle=bstyle, padding=(10, 5), font=("Segoe UI", 9, "bold"))
            lbl.pack(side=LEFT, padx=5)

        for sec in sections:
            sec_card = tb.LabelFrame(inner, text=f"SECTION: {sec}", padding=10)
            sec_card.pack(fill=X, pady=10)

            # Use a Treeview for the grid
            cols = ["Day"] + slot_times
            tree = tb.Treeview(sec_card, columns=cols, show="headings", height=len(days), bootstyle=PRIMARY)
            tree.pack(fill=X)

            tree.heading("Day", text="Day")
            tree.column("Day", width=120, anchor=W)
            for slot in slot_times:
                tree.heading(slot, text=slot)
                tree.column(slot, width=150, anchor=CENTER)

            for day in days:
                row_vals = [day]
                for i, slot in enumerate(slot_times):
                    val = timetable[day][sec][i]
                    if val == "LUNCH": text = "🍱 LUNCH"
                    elif val == "FREE": text = "💨 FREE"
                    else: text = val
                    row_vals.append(text)

                # Tags for coloring
                item = tree.insert("", "end", values=row_vals)

            # Note: Ttk Treeview doesn't easily support per-cell background color
            # without complex tags. We'll rely on text indicators for now or use Labels if preferred.
            # Let's use a Grid of Labels for better color coding as requested.
            tree.destroy()

            grid_frame = tb.Frame(sec_card)
            grid_frame.pack(fill=X)

            # Header
            tb.Label(grid_frame, text="DAY", width=15, font=("Segoe UI", 10, "bold"), bootstyle=SECONDARY).grid(row=0, column=0, padx=1, pady=1, sticky=NSEW)
            for c, slot in enumerate(slot_times):
                tb.Label(grid_frame, text=slot, width=20, font=("Segoe UI", 10, "bold"), anchor=CENTER, bootstyle=SECONDARY).grid(row=0, column=c+1, padx=1, pady=1, sticky=NSEW)

            for r, day in enumerate(days):
                tb.Label(grid_frame, text=day, font=("Segoe UI", 9, "bold"), bootstyle=LIGHT).grid(row=r+1, column=0, padx=1, pady=1, sticky=NSEW)
                for c, slot in enumerate(slot_times):
                    val = timetable[day][sec][c]

                    bstyle = LIGHT
                    text = val
                    if val == "LUNCH":
                        bstyle = WARNING
                        text = "LUNCH BREAK"
                    elif val == "FREE":
                        bstyle = SECONDARY
                    elif "[SUB]" in val:
                        bstyle = SUCCESS
                    else:
                        bstyle = PRIMARY

                    lbl = tb.Label(grid_frame, text=text, anchor=CENTER, padding=10, bootstyle=bstyle, font=("Segoe UI", 9))
                    lbl.grid(row=r+1, column=c+1, padx=1, pady=1, sticky=NSEW)

            for i in range(len(slot_times) + 1):
                grid_frame.columnconfigure(i, weight=1)

    def on_show_replacements(self):
        if self._last_timetable is None:
            messagebox.showerror("Error", "Please generate a timetable first.")
            return

        rows = build_replacement_suggestions(self._last_timetable, self._last_teacher_data, self._last_load, self._last_slot_times)

        win = tb.Toplevel(self.root)
        win.title("Replacement Suggestions")
        win.geometry("1000x600")

        container = tb.Frame(win, padding=20)
        container.pack(fill=BOTH, expand=True)

        tb.Label(container, text="Available Substitutes", font=("Segoe UI", 16, "bold")).pack(anchor=W, pady=(0, 10))
        tb.Label(container, text="Filtered: Only showing slots with available candidates.", font=("Segoe UI", 10, "italic"), bootstyle=INFO).pack(anchor=W, pady=(0, 10))

        cols = ("Day", "Slot", "Section", "Subject", "Current", "Candidates")
        tree = tb.Treeview(container, columns=cols, show="headings", bootstyle=INFO)
        tree.pack(fill=BOTH, expand=True)

        tree.heading("Day", text="Day")
        tree.heading("Slot", text="Slot Time")
        tree.heading("Section", text="Section")
        tree.heading("Subject", text="Subject")
        tree.heading("Current", text="Assigned Teacher")
        tree.heading("Candidates", text="Available Candidates")

        for col in cols:
            tree.column(col, anchor=CENTER)
        tree.column("Candidates", width=350, anchor=W)

        for r in rows:
            cand_str = ", ".join(r["candidates"])
            tree.insert("", "end", values=(r["day"], r["slot_label"], r["section"], r["subject"], r["assigned_teacher"], cand_str))

# run
if __name__ == "__main__":
    root = tb.Window(themename="flatly")
    app = App(root)
    root.mainloop()
