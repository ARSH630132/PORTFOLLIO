import tkinter as tk
from tkinter import ttk, messagebox
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
            # val format: "SUBJECT (TEACHER)" or "SUBJECT (TEACHER) [SUB]"
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
            # TECH teacher must be allowed in this section
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
                    # Check for LUNCH and current timetable status
                    if slot_times[i].upper() == "LUNCH" or slot_times[i+1].upper() == "LUNCH":
                        continue
                    if timetable[day][sec][i] != "FREE" or timetable[day][sec][i+1] != "FREE":
                        continue

                    # Collision check: Teacher 'cand' must be free at slots i and i+1 in ALL sections
                    if i in booked[cand] or (i+1) in booked[cand]:
                        continue

                    # assign
                    timetable[day][sec][i] = f"{tech_subject} ({cand})"
                    timetable[day][sec][i+1] = f"{tech_subject} ({cand})"

                    usage[cand] += 2
                    booked[cand].add(i); booked[cand].add(i+1)
                    placed = True
                    break
                if placed:
                    break

        # 2) Fill remaining slots with non-tech teachers (Strict Rules: includes Gap Rule and Section Mapping)
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

                    # 1. Section Mapping Check: Teacher must be allowed to teach this section
                    if info["allowed_sections"] and sec not in info["allowed_sections"]:
                        continue

                    # 2. capacity
                    if usage[tname] >= load_per_day:
                        continue

                    # 3. Collision check: Teacher must be free at slot 'i' (assigned nowhere else)
                    if i in booked[tname]:
                        continue

                    # 4. gap rule: (STRICT RULE) non-tech teacher should not have been assigned at a slot within 2 positions (abs diff <3)
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

                # Assign to current section and dynamically update for next sections/slots
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
                            # TECH subjects are not assigned in this pass (only Non-TECH)
                            continue

                        # 1. Section Mapping Check: Teacher must be allowed to teach this section
                        if info["allowed_sections"] and sec not in info["allowed_sections"]:
                            continue

                        # 2. Capacity check
                        if usage[tname] >= load_per_day:
                            continue

                        # 3. Collision check (Must be free at this slot, assigned nowhere else)
                        if i in booked[tname]:
                            continue

                        eligible.append(tname)

                    if eligible:
                        min_used = min(usage[t] for t in eligible)
                        candidates = [t for t in eligible if usage[t] == min_used]
                        chosen = random.choice(candidates)
                        subj = teacher_data[chosen]["subject"]

                        # Assign and update trackers
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

    # Track usage for the day to ensure we don't exceed load_per_day
    usage, booked = get_current_day_usage(timetable, day, sections, slots_count, teacher_data)

    for sec in sections:
        for i in range(slots_count):
            val = timetable[day][sec][i]
            if f"({absent_teacher})" in val:
                # Mark as FREE first so we can find a replacement
                original_subject = val.split("(")[0].strip()
                timetable[day][sec][i] = "FREE"

                # Decrement usage for the absent teacher (though they are absent, we just cleared their slot)
                if absent_teacher in usage:
                    usage[absent_teacher] -= 1
                    booked[absent_teacher].discard(i)

                # Find eligible substitutes
                eligible = []
                for tname, info in teacher_data.items():
                    if tname == absent_teacher:
                        continue

                    # Section check
                    if info["allowed_sections"] and sec not in info["allowed_sections"]:
                        continue

                    # Capacity check
                    if usage[tname] >= load_per_day:
                        continue

                    # Collision check
                    if i in booked[tname]:
                        continue

                    eligible.append(tname)

                if eligible:
                    # Prefer same subject
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

                # Find candidates who COULD have taken this slot
                candidates = []
                for tname, info in teacher_data.items():
                    if tname == assigned_teacher:
                        continue

                    # Section check
                    if info["allowed_sections"] and sec not in info["allowed_sections"]:
                        continue

                    # Capacity check (Check if they have at least 1 slot free)
                    if usage[tname] >= load_per_day:
                        # If they are already teaching at this exact slot elsewhere, they are not candidates
                        # But wait, build_replacement_suggestions usually shows who is FREE NOW.
                        pass

                    # Collision check: Must NOT be teaching at this slot i
                    if i in booked[tname]:
                        continue

                    # For suggestions, we might be a bit more relaxed about load,
                    # but let's stick to strict rules for now.
                    if usage[tname] < load_per_day:
                        candidates.append(tname)

                suggestions.append({
                    "day": day,
                    "slot_label": slot_times[i],
                    "section": sec,
                    "subject": subj,
                    "assigned_teacher": assigned_teacher,
                    "candidates": candidates
                })

    return suggestions

# ---------------- GUI ----------------
class App:
    def __init__(self, root):
        self.root = root
        root.title("Timetable Scheduler (ALL Teacher-Section Mapping Applied)")
        root.geometry("1100x750")

        self._last_timetable = None
        self._last_teacher_data = {}
        self._last_load = 0
        self._last_slot_times = []

        self.build_ui()


    def build_ui(self):
        frm = ttk.Frame(self.root, padding="10 10 10 10")
        frm.pack(fill="both", expand=True)

        top = ttk.Frame(frm)
        top.pack(fill="x", pady=4)
        top.columnconfigure(1, weight=1)
        top.columnconfigure(3, weight=1)

        ttk.Label(top, text="Sections (comma):").grid(row=0, column=0, sticky="w", padx=2, pady=2)
        self.sections_var = tk.StringVar(value="4A,4B,4C,4D")
        ttk.Entry(top, textvariable=self.sections_var, width=30).grid(row=0, column=1, sticky="ew", padx=5, pady=2)

        ttk.Label(top, text="Days (comma):").grid(row=0, column=2, sticky="w", padx=10, pady=2)
        self.days_var = tk.StringVar(value="Monday,Tuesday,Wednesday,Thursday,Friday,Saturday")
        ttk.Entry(top, textvariable=self.days_var, width=30).grid(row=0, column=3, sticky="ew", padx=5, pady=2)

        ttk.Label(top, text="Lecture duration (min):").grid(row=1, column=0, sticky="w", padx=2, pady=2)
        self.duration_var = tk.IntVar(value=45)
        ttk.Entry(top, textvariable=self.duration_var, width=8).grid(row=1, column=1, sticky="w", padx=5, pady=2)

        ttk.Label(top, text="Start time (HH:MM):").grid(row=2, column=0, sticky="w", padx=2, pady=2)
        self.start_var = tk.StringVar(value="09:00")
        ttk.Entry(top, textvariable=self.start_var, width=10).grid(row=2, column=1, sticky="w", padx=5, pady=2)

        ttk.Label(top, text="Lunch start (HH:MM):").grid(row=1, column=2, sticky="w", padx=10, pady=2)
        self.lunch_var = tk.StringVar(value="12:30")
        ttk.Entry(top, textvariable=self.lunch_var, width=10).grid(row=1, column=3, sticky="w", padx=5, pady=2)

        ttk.Label(top, text="Load per day (max slots):").grid(row=2, column=2, sticky="w", padx=10, pady=2)
        self.load_var = tk.IntVar(value=3)
        ttk.Entry(top, textvariable=self.load_var, width=6).grid(row=2, column=3, sticky="w", padx=5, pady=2)

        sep = ttk.Separator(frm, orient="horizontal")
        sep.pack(fill="x", pady=8)

        # Updated Label to reflect that all teachers need sections now
        teach_lbl = ttk.Label(frm, text="Teachers: NAME | SUBJECT | ALLOWED SECTIONS (comma, **REQUIRED for all subjects**)", font=("Arial", 10, "bold"))
        teach_lbl.pack(anchor="w")

        self.rows_frame = ttk.Frame(frm)
        self.rows_frame.pack(fill="x", pady=4)

        hdr = ttk.Frame(self.rows_frame)
        hdr.grid(row=0, column=0, columnspan=4, sticky="w")
        ttk.Label(hdr, text="Name", width=25, font=("Arial", 9, "bold")).grid(row=0, column=0)
        ttk.Label(hdr, text="Subject", width=20, font=("Arial", 9, "bold")).grid(row=0, column=1)
        ttk.Label(hdr, text="Allowed Sections (e.g., 4A,4B,4C)", width=45, font=("Arial", 9, "bold")).grid(row=0, column=2)

        self.teacher_vars = []

        abs_frame = ttk.Frame(frm)
        abs_frame.pack(fill="x", pady=6)

        ttk.Label(abs_frame, text="Absent teacher (optional):").grid(row=0, column=0, sticky="w", padx=2)
        self.absent_combo = ttk.Combobox(abs_frame, values=[], width=20)
        self.absent_combo.grid(row=0, column=1, sticky="w", padx=6)

        ttk.Label(abs_frame, text="Absent day (optional):").grid(row=0, column=2, sticky="w", padx=10)
        self.absent_day = ttk.Combobox(abs_frame, values=to_upper_list(self.days_var.get()), width=20)
        self.absent_day.grid(row=0, column=3, sticky="w", padx=6)

        # Default data updated to enforce mapping for Non-TECH too
        self.add_teacher_row("SUDHAKAR","TECH","4A,4D")
        self.add_teacher_row("RITIK","TECH","4C,4B")
        self.add_teacher_row("RAHUL","APTI","4A,4D")
        self.add_teacher_row("RAJEEV","HINDI","4D,4C")

        btn_frame = ttk.Frame(frm)
        btn_frame.pack(fill="x", pady=6)

        ttk.Button(btn_frame, text="➕ Add Teacher Row", command=lambda: self.add_teacher_row("","", "")).pack(side="left")
        ttk.Button(btn_frame, text="🔄 Update Absent List", command=self.update_absent_list).pack(side="left", padx=8)
        ttk.Button(btn_frame, text="🚀 Generate Timetable", command=self.on_generate, style='Accent.TButton').pack(side="left", padx=8)
        ttk.Button(btn_frame, text="🔍 Show Replacement Suggestions", command=self.on_show_replacements).pack(side="left", padx=8)

        out_lbl = ttk.Label(frm, text="Output (Class-wise Timetable):", font=("Arial", 10, "bold"))
        out_lbl.pack(anchor="w", pady=(6,0))

        self.canvas_frame = ttk.Frame(frm)
        self.canvas_frame.pack(fill="both", expand=True)

        self.canvas = tk.Canvas(self.canvas_frame, bg="white", height=300, borderwidth=0, highlightthickness=0)
        self.vscroll = ttk.Scrollbar(self.canvas_frame, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.vscroll.set)

        self.vscroll.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)

        self.inner = ttk.Frame(self.canvas)
        self.canvas.create_window((0,0), window=self.inner, anchor="nw")

        self.inner.bind("<Configure>", self._on_frame_configure)
        self.canvas.bind_all("<MouseWheel>", self._on_mouse_wheel)

        self.update_absent_list()


    def _on_frame_configure(self, event):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        self.canvas.configure(width=event.width)

    def _on_mouse_wheel(self, event):
        self.canvas.yview_scroll(int(-1*(event.delta/120)), "units")


    def add_teacher_row(self, name="", subj="", allowed=""):
        row = len(self.teacher_vars) + 1
        name_var = tk.StringVar(value=name)
        subj_var = tk.StringVar(value=subj)
        allowed_var = tk.StringVar(value=allowed)

        e1 = ttk.Entry(self.rows_frame, textvariable=name_var, width=25)
        e2 = ttk.Entry(self.rows_frame, textvariable=subj_var, width=20)
        e3 = ttk.Entry(self.rows_frame, textvariable=allowed_var, width=45)

        e1.grid(row=row, column=0, padx=2, pady=2, sticky="w")
        e2.grid(row=row, column=1, padx=2, pady=2, sticky="w")
        e3.grid(row=row, column=2, padx=2, pady=2, sticky="w")

        self.teacher_vars.append((name_var, subj_var, allowed_var))
        self.update_absent_list()


    def update_absent_list(self):
        names = sorted(list(set([v[0].get().strip().upper() for v in self.teacher_vars if v[0].get().strip()])))

        if hasattr(self, 'absent_combo'):
            self.absent_combo["values"] = names

        days = to_upper_list(self.days_var.get())
        if hasattr(self, 'absent_day'):
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

            if duration <= 0 or load <= 0:
                messagebox.showerror("Error", "Duration and Load must be positive numbers.")
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
            messagebox.showerror("Error", "Invalid lunch time format for calculation.")
            return None

        for _ in range(2):
            end = add_time(cur, duration)
            slot_times.append(f"{cur}-{end}")
            cur = end

        teacher_data = {}
        no_mapping_teachers = []
        for name_var, subj_var, allowed_var in self.teacher_vars:
            name = name_var.get().strip().upper()
            subj = subj_var.get().strip().upper()
            allowed = to_upper_list(allowed_var.get())

            if not name or not subj:
                continue
            if name in teacher_data:
                messagebox.showwarning("Warning", f"Duplicate teacher name '{name}' found. Using the first entry.")
                continue

            if not allowed:
                no_mapping_teachers.append(name)

            teacher_data[name] = {"subject": subj, "allowed_sections": allowed if allowed else None}

        if not teacher_data:
            messagebox.showerror("Error", "No teacher data provided.")
            return None

        if no_mapping_teachers:
            messagebox.showwarning("Warning", f"No sections allotted for teachers: {', '.join(no_mapping_teachers)}. They will not be assigned any class.")

        absent_name = self.absent_combo.get().strip().upper() if self.absent_combo.get().strip() else None
        absent_day = self.absent_day.get().strip() if self.absent_day.get().strip() else None

        if absent_name and absent_day and absent_day not in days:
             messagebox.showwarning("Warning", f"Absent day '{absent_day}' is not one of the selected schedule days. Skipping substitution.")
             absent_info = None
        elif absent_name and absent_day:
            absent_info = (absent_name, absent_day)
        else:
            absent_info = None

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
        if not inputs:
            return

        sections = inputs["sections"]
        teacher_data = inputs["teacher_data"]
        load = inputs["load"]
        days = inputs["days"]
        slot_times = inputs["slot_times"]
        absent_info = inputs["absent"]

        # Check for unassigned sections (optional warning)
        all_allowed_sections = set()
        for t, info in teacher_data.items():
            if info["allowed_sections"]:
                all_allowed_sections.update(info["allowed_sections"])

        unassigned_sections = [s for s in sections if s not in all_allowed_sections]
        if unassigned_sections:
            res = messagebox.askyesno("Warning",
                f"No teacher is allotted to sections: {', '.join(unassigned_sections)}. These sections will have FREE slots. Continue?")
            if not res:
                return

        timetable = build_timetable(sections, teacher_data, load, days, slot_times, tech_subject="TECH")

        timetable = fill_remaining_free_slots(timetable, teacher_data, load, slot_times, tech_subject="TECH")

        if absent_info:
            absent_name, absent_day = absent_info
            if absent_name not in teacher_data:
                messagebox.showwarning("Absent", f"Absent teacher '{absent_name}' not found in teacher list. Skipping substitution.")
            else:
                substitute_absent(timetable, absent_day, absent_name, teacher_data, load, slot_times)
                messagebox.showinfo("Substitution Complete",
                    f"Substitution attempted for **{absent_name}** on **{absent_day}**.")

        self._display_timetable(timetable, sections, days, slot_times)

        self._last_timetable = timetable
        self._last_teacher_data = teacher_data
        self._last_load = load
        self._last_slot_times = slot_times


    def _display_timetable(self, timetable, sections, days, slot_times):
        for w in self.inner.winfo_children():
            w.destroy()

        r = 0

        legend_frame = ttk.Frame(self.inner)
        legend_frame.grid(row=r, column=0, sticky="w", pady=4, padx=5)
        ttk.Label(legend_frame, text="Legend: ", font=("Arial", 10, "bold")).pack(side="left")

        tk.Label(legend_frame, text="Lecture (Subj/Teacher)", font=("Arial",10), bg="#fff3bf", padx=5).pack(side="left", padx=5)
        tk.Label(legend_frame, text="LUNCH", font=("Arial",10), bg="#ffb86b", padx=5).pack(side="left", padx=5)
        tk.Label(legend_frame, text="FREE Slot", font=("Arial",10), bg="#e9ecef", padx=5).pack(side="left", padx=5)
        r += 1

        for sec in sections:
            colspan = len(slot_times) + 1
            sec_lbl = tk.Label(self.inner, text=f"SECTION: {sec}", font=("Arial", 14, "bold"), bg="#d1f7c4", anchor="w")
            sec_lbl.grid(row=r, column=0, sticky="ew", pady=(10,4), padx=2, columnspan=colspan)
            r += 1

            hdr_frame = ttk.Frame(self.inner)
            hdr_frame.grid(row=r, column=0, sticky="ew", columnspan=colspan)

            ttk.Label(hdr_frame, text="DAY ➡️", width=15, font=("Arial", 10, "bold"), anchor="w", background="#e6f2ff").grid(row=0, column=0, padx=2, sticky="ew")
            for col, slot in enumerate(slot_times):
                ttk.Label(hdr_frame, text=slot, width=15, font=("Arial", 10, "bold"), anchor="center", background="#e6f2ff").grid(row=0, column=col+1, padx=1, sticky="ew")
            r += 1

            for day_idx, day in enumerate(days):
                row_frame = ttk.Frame(self.inner)
                row_frame.grid(row=r + day_idx, column=0, sticky="ew", columnspan=colspan)

                tk.Label(row_frame, text=day, font=("Arial", 10, "bold"), width=15, anchor="w", background="#e6f2ff", relief="raised").grid(row=0, column=0, padx=2, pady=1, sticky="ew")

                for col, slot in enumerate(slot_times):
                    val = timetable[day][sec][col]

                    if val == "LUNCH":
                        bg = "#ffb86b"
                        text = "LUNCH BREAK"
                    elif val == "FREE":
                        bg = "#e9ecef"
                        text = "FREE"
                    else:
                        bg = "#fff3bf"
                        text = val

                    tk.Label(row_frame, text=text, bg=bg, width=15, anchor="center", borderwidth=1, relief="solid").grid(row=0, column=col+1, padx=1, pady=1, sticky="ew")

                row_frame.columnconfigure(0, weight=0)
                for c in range(1, colspan):
                    row_frame.columnconfigure(c, weight=1)

            r += len(days)

            sep = ttk.Separator(self.inner, orient="horizontal")
            sep.grid(row=r, column=0, sticky="ew", pady=8, columnspan=colspan)
            r += 1

        self.inner.update_idletasks()
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))


    def on_show_replacements(self):
        if self._last_timetable is None:
            messagebox.showerror("Error", "Generate timetable first.")
            return

        rows = build_replacement_suggestions(self._last_timetable, self._last_teacher_data, self._last_load, self._last_slot_times)

        win = tk.Toplevel(self.root)
        win.title("Replacement Suggestions")
        win.geometry("900x500")

        cols = ("Day", "Slot", "Section", "Subject", "Assigned", "Candidates")
        tree_frame = ttk.Frame(win, padding=5)
        tree_frame.pack(fill="both", expand=True)

        tree = ttk.Treeview(tree_frame, columns=cols, show="headings", height=20)

        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=tree.yview)
        hsb = ttk.Scrollbar(tree_frame, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        vsb.pack(side="right", fill="y")
        hsb.pack(side="bottom", fill="x")
        tree.pack(side="left", fill="both", expand=True)

        tree.heading("Day", text="Day")
        tree.column("Day", width=100, anchor="w")
        tree.heading("Slot", text="Slot Time")
        tree.column("Slot", width=120, anchor="center")
        tree.heading("Section", text="Section")
        tree.column("Section", width=80, anchor="center")
        tree.heading("Subject", text="Subject")
        tree.column("Subject", width=80, anchor="center")
        tree.heading("Assigned", text="Assigned Teacher")
        tree.column("Assigned", width=120, anchor="w")
        tree.heading("Candidates", text="Available Candidates (Teachers)")
        tree.column("Candidates", width=350, anchor="w")

        for r in rows:
            cand_str = ", ".join(r["candidates"]) if r["candidates"] else "No available substitute"
            tree.insert("", "end", values=(r["day"], r["slot_label"], r["section"], r["subject"], r["assigned_teacher"], cand_str))

        ttk.Label(win, text="* Candidates are teachers who teach the same subject, have capacity, are not teaching another section at that time, and generally satisfy the time gap rule.", font=("Arial", 9)).pack(pady=5)


# run
if __name__ == "__main__":
    root = tk.Tk()

    style = ttk.Style(root)
    style.theme_use('clam')
    style.configure('Accent.TButton', background='#4CAF50', foreground='black', font=('Arial', 10, 'bold'))
    style.map('Accent.TButton',
        background=[('active', '#66BB6A'), ('!disabled', '#4CAF50')],
        foreground=[('active', 'white'), ('!disabled', 'black')]
    )

    app = App(root)
    root.mainloop()
