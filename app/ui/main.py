"""Run with: D:\\NEXDATA\\.venv\\Scripts\\python.exe -m app.ui.main"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import threading
import math
import json
import webbrowser
from tkinter import TclError, filedialog, messagebox

import customtkinter as ctk
import networkx as nx
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib import pyplot as plt
from fpdf import FPDF

from app.engine.coverage import STATUS_LABELS, coverage_rows, audit_is_partial, tracker_display, storage_display, chat_display

ROOT = Path(r"D:\NEXDATA")
REPORT_PATH = ROOT / "NexData_report.pdf"
BG = "#10151f"
PANEL = "#1b2432"
TEXT = "#ecf2fa"
MUTED = "#a4b2c5"
CYAN = "#56d9ed"
PRIORITIES = {"high": "#c84959", "medium": "#a97522", "low": "#536174"}
CLUSTER_COLORS = {"Shopping": "#ffa75c", "Food & delivery": "#8edc99", "Finance & payments": "#f3ce69",
                  "Travel": "#78bfff", "Social & messaging": "#56d9ed", "Education & jobs": "#f29dc6",
                  "Trackers & ads": "#cba6f7", "Other": "#a4b2c5"}
NODE_COLORS = {"user": "#ffffff", "advertiser": "#f26873", "service": "#ffa75c", "person": CYAN, "tracker": "#cba6f7"}
TAB_NAMES = ("Footprint", "Scan coverage", "What they know", "Inner circle", "Findings", "Fix first")
SCAN_MODES = {"Quick (20s)": 20, "Extended (120s)": 120}


def is_demo_path(path):
    return Path(path).resolve().is_relative_to((ROOT / "samples").resolve())


def pc_scan_paths(scan_path, profiles, loaded_paths):
    """Never carry the old demo into a live scan, and replace prior scan inputs."""
    paths = [scan_path, *profiles, *(p for p in loaded_paths if not is_demo_path(p))]
    return list(dict.fromkeys(str(Path(path).resolve()) for path in paths))


def ordered_findings(result):
    return sorted(result.get("findings") or [], key=lambda f: {"high": 0, "medium": 1, "low": 2}.get(f.get("priority"), 3))


def error_text(errors):
    if not errors:
        return ""
    if not isinstance(errors, (list, tuple)):
        errors = [errors]
    return "\n".join(
        (f"{Path(e.get('file', '')).name}: {e.get('message', '')}" if e.get("reason") else
         ": ".join(str(e[k]) for k in ("file", "code", "message") if e.get(k)))
        if isinstance(e, dict) else str(e) for e in errors
    )


def prepare_charts(result):
    """Compute expensive layout without touching Tk widgets."""
    graph = nx.Graph()
    for node in (result.get("graph") or {}).get("nodes", []):
        if node.get("id") is not None:
            graph.add_node(node["id"], **{k: v for k, v in node.items() if k != "id"})
    for edge in (result.get("graph") or {}).get("edges", []):
        if edge.get("source") in graph and edge.get("target") in graph:
            graph.add_edge(edge["source"], edge["target"], weight=max(0.01, float(edge.get("weight") or 1)))
    clusters = [n for n in graph if graph.nodes[n].get("type") == "cluster"]
    positions = {"user": (0, 0)} if graph else {}
    for i, node in enumerate(clusters):
        angle = math.pi / 2 - 2 * math.pi * i / max(len(clusters), 1)
        positions[node] = (1.8 * math.cos(angle), math.sin(angle))
    heat = [[0 for _ in range(24)] for _ in range(7)]
    for record in result.get("records") or []:
        stamp = record.get("timestamp")
        if not stamp:
            continue
        try:
            date = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
        except (ValueError, TypeError, OverflowError):
            continue
        heat[date.weekday()][date.hour] += 1
    return graph, positions, heat


def service_findings(result, service):
    ids = set(service.get("evidence") or [])
    return [f for f in result.get("findings") or [] if ids.intersection(f.get("evidence") or [])]


def report_bytes(result):
    """Use a core PDF font; unsupported characters are deliberately replaced."""
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    def line(text, size=11, bold=False):
        pdf.set_font("Helvetica", "B" if bold else "", size)
        safe = str(text).encode("latin-1", "replace").decode("latin-1")
        pdf.multi_cell(w=0, h=6 if size < 15 else 9, text=safe, new_x="LMARGIN", new_y="NEXT", wrapmode="CHAR")

    line("NexData - Personal Data Footprint Auditor", 18, True)
    line("Offline report - nothing leaves this device")
    line("Source: this PC and any user-selected imports" if result.get("sourceMode") == "pc" else "Source: user-selected imports")
    line("Social interests and relationships require actual account exports; they are not guessed from this PC.")
    line(datetime.now().strftime("Generated %Y-%m-%d %H:%M"))
    summary = result.get("summary") or {}
    line(f"Services holding your data: {summary.get('servicesFound', 0)}")
    line(f"Sensitive items in chats: {chat_display(result)}")
    line(f"People ranked: {len(summary['topPeople']) if summary.get('topPeople') else 'Not provided'}")
    if result.get("sourceMode") == "pc":
        line(f"Selected app-folder data (GB): {storage_display(result)}")
        line(f"Browser tracker indicators: {tracker_display(result)}")
    line("Coverage: partial" if audit_is_partial(result) else "Supported checks finished; unprovided sources remain unassessed")
    line("Scan coverage", 14, True)
    for row in coverage_rows(result):
        line(f"{row['name']} [{STATUS_LABELS.get(row['status'], row['status'])}]", 11, True)
        line(row["detail"])
        if row.get("source"):
            line(row["source"], 9)
    line(f"Records reviewed: {len(result.get('records') or [])}")
    pdf.ln(3)
    line("Platform coverage", 14, True)
    for platform, coverage in (result.get("coverage") or {}).items():
        line(f"{platform}: " + "; ".join(f"{key} = {value}" for key, value in coverage.items()))
    line("Findings and actions - fix first", 14, True)
    for index, finding in enumerate(ordered_findings(result), 1):
        pdf.ln(3)
        line(f"{index}. [{str(finding.get('priority', 'low')).upper()}] {finding.get('title', '')}", 12, True)
        line(finding.get("detail", ""))
        metric = finding.get("metric") or {}
        if metric:
            line(f"Metric: {metric.get('value', '')} {metric.get('unit', '')}")
        line(f"Evidence: {len(finding.get('evidence') or [])} record(s)")
        action = finding.get("action") or {}
        for step_index, step in enumerate(action.get("steps") or [], 1):
            line(f"  {step_index}. {step}")
        if action.get("link"):
            line(action["link"])
    if result.get("errors"):
        line("Import errors", 14, True)
        line(error_text(result["errors"]))
    return bytes(pdf.output())


class NexDataApp(ctk.CTk):
    def __init__(self):
        ctk.set_appearance_mode("dark")
        super().__init__()
        self.title("NexData - Personal Data Footprint Auditor | Real PC scan")
        self.geometry("1280x800")
        self.minsize(1000, 680)
        self.configure(fg_color=BG)
        self.result = {}
        self.source_mode = "pc"
        self.loaded_paths = []
        self.pending_paths = []
        self.records_by_id = {}
        self.figures = []
        self.canvases = []
        self.loading = False
        self.closing = False
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        top = ctk.CTkFrame(self, fg_color=PANEL, corner_radius=0)
        top.grid(row=0, column=0, sticky="ew")
        top.grid_columnconfigure(2, weight=1)
        ctk.CTkLabel(top, text="NexData", font=("Segoe UI", 27, "bold"), text_color=TEXT).grid(row=0, column=0, padx=(22, 18), pady=18)
        ctk.CTkLabel(top, text="Offline - nothing leaves this device", fg_color="#173e32", text_color="#87e3b1", corner_radius=8, padx=12).grid(row=0, column=1)
        self.open_button = ctk.CTkButton(top, text="Open my exports...", command=self.open_files, width=150)
        self.scan_mode = ctk.CTkOptionMenu(top, values=list(SCAN_MODES), width=145)
        self.scan_mode.set("Quick (20s)")
        self.scan_mode.grid(row=0, column=3, padx=8)
        self.open_button.grid(row=0, column=4, padx=(4, 10))
        self.scan_button = ctk.CTkButton(top, text="Scan this PC", command=self.scan_laptop, width=145, fg_color="#217989")
        self.scan_button.grid(row=0, column=5, padx=(0, 22))

        status = ctk.CTkFrame(self, fg_color="transparent")
        status.grid(row=1, column=0, sticky="ew", padx=22, pady=(10, 0))
        status.grid_columnconfigure(0, weight=1)
        self.status_label = ctk.CTkLabel(status, text="Starting a real scan of this PC...", text_color=MUTED, anchor="w")
        self.status_label.grid(row=0, column=0, sticky="ew")
        self.progress = ctk.CTkProgressBar(status, mode="indeterminate", width=220, progress_color=CYAN)
        self.progress.grid(row=0, column=1, padx=12)
        self.progress.grid_remove()
        self.resolve_button = ctk.CTkButton(status, text="Close browsers and rescan", command=self.resolve_browser_locks, width=210, fg_color="#8b5b24")
        self.resolve_button.grid(row=3, column=0, sticky="w", pady=(6, 4))
        self.resolve_button.grid_remove()
        self.error_label = ctk.CTkLabel(status, text="", text_color="#ff9b9b", justify="left", anchor="w", wraplength=1180)
        self.error_label.grid(row=1, column=0, columnspan=2, sticky="ew")
        self.error_label.grid_remove()
        self.source_label = ctk.CTkLabel(status, text="REAL PC SCAN | App folders and available browser metadata. Social accounts and phones require your own exports.", text_color=CYAN, anchor="w", justify="left", wraplength=1180)
        self.source_label.grid(row=2, column=0, columnspan=2, sticky="ew")
        self.tabs = ctk.CTkTabview(self, fg_color=PANEL, segmented_button_selected_color="#237e8e", segmented_button_selected_hover_color="#2c92a3")
        self.tabs.grid(row=2, column=0, sticky="nsew", padx=18, pady=(4, 18))
        for name in TAB_NAMES:
            page = self.tabs.add(name)
            page.grid_columnconfigure(0, weight=1)
            page.grid_rowconfigure(0, weight=1)
        self.after(150, self.scan_laptop)

    def show_errors(self, message):
        self.error_label.configure(text=message)
        if message:
            self.error_label.grid()
        else:
            self.error_label.grid_remove()

    def open_files(self):
        paths = filedialog.askopenfilenames(parent=self, title="Open personal data exports", initialdir=str(Path.home() / "Downloads"), filetypes=[("Data exports", "*.zip *.txt *.mbox *.mp4 *.mov *.mkv *.avi *.png *.jpg *.jpeg *.ndjson *.json"), ("All files", "*.*")])
        if paths:
            self.load_paths(paths)

    def scan_laptop(self):
        if self.loading or self.closing:
            return
        self.loading = True
        budget = SCAN_MODES[self.scan_mode.get()]
        self.scan_mode.configure(state="disabled")
        self.resolve_button.configure(state="disabled")
        for button in (self.open_button, self.scan_button):
            button.configure(state="disabled")
        self.show_errors("")
        self.status_label.configure(text=f"Scanning this PC with a {budget}s budget; fixed folder/log limits still apply...")
        self.progress.grid()
        self.progress.start()

        def worker():
            try:
                from scanner.scan import scan_laptop
                from app.parsers.chrome import default_profiles
                profiles = default_profiles()
                scan = {"scanned_at": datetime.now(timezone.utc).isoformat(), "laptop": scan_laptop(max_seconds=budget), "android": None}
                path = ROOT / ".cache" / "device_scan.json"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(scan, indent=2) + "\n", encoding="utf-8")
            except Exception as exc:
                self.dispatch(self.load_failed, f"Laptop scan could not finish: {exc}")
            else:
                self.dispatch(self.scan_complete, path, profiles)

        threading.Thread(target=worker, name="nexdata-device-scan", daemon=True).start()

    def scan_complete(self, path, profiles):
        paths = pc_scan_paths(path, profiles, self.loaded_paths)
        self.finish_loading()
        self.load_paths(paths, source_mode="pc")

    def resolve_browser_locks(self):
        if self.loading or self.closing:
            return
        processes = {p["pid"]: p for error in self.result.get("errors") or [] for p in error.get("blocked_by", [])}
        if not processes:
            self.scan_laptop()
            return
        if not messagebox.askyesno("Close browser background processes?",
                                  "NexData identified Chrome/Edge processes holding browser data files.\n\n"
                                  "Close visible browser windows first. NexData will try a normal exit. If Windows refuses, it may stop only the verified background browser processes.\n\n"
                                  "This can interrupt browser background apps or downloads. Allow this and scan again?", parent=self):
            return
        self.loading = True
        for button in (self.open_button, self.scan_button, self.resolve_button, self.scan_mode):
            button.configure(state="disabled")
        self.status_label.configure(text="Requesting a normal exit from the browsers holding these files...")
        self.progress.grid()
        self.progress.start()

        def worker():
            try:
                from scanner.browser_access import close_browsers
                close_browsers(list(processes.values()), allow_background_stop=True)
            except (OSError, RuntimeError) as exc:
                self.dispatch(self.load_failed, str(exc))
            else:
                self.dispatch(self.browser_locks_resolved)

        threading.Thread(target=worker, name="nexdata-browser-unlock", daemon=True).start()

    def browser_locks_resolved(self):
        self.finish_loading()
        self.scan_laptop()

    def dispatch(self, callback, *args):
        if not self.closing:
            try:
                self.after(0, callback, *args)
            except (RuntimeError, TclError):
                pass  # The window may have closed while the worker was finishing.

    def load_paths(self, paths, source_mode="imports"):
        if self.loading or self.closing:
            return
        if any(is_demo_path(path) for path in paths):
            self.show_errors("The project's samples folder contains fictional test data. Select your own exports from another folder.")
            return
        self.loading = True
        self.source_mode = source_mode
        self.source_label.configure(text="REAL PC SCAN | App folders and available browser metadata. Social accounts and phones require your own exports." if source_mode == "pc" else "YOUR SELECTED IMPORTS | Showing only the files you selected; their origin is not independently verified.")
        self.pending_paths = list(paths)
        self.scan_mode.configure(state="disabled")
        self.resolve_button.configure(state="disabled")
        self.scan_button.configure(state="disabled")
        self.open_button.configure(state="disabled")
        self.show_errors("")
        self.status_label.configure(text=f"Auditing {len(paths)} file(s) locally...")
        self.progress.grid()
        self.progress.start()

        def worker():
            try:
                from app import pipeline
                result = pipeline.run(paths)
                result["sourceMode"] = source_mode
                result["inputSources"] = [str(path) for path in paths]
                if source_mode == "pc":
                    (ROOT / ".cache" / "real_findings.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                charts = prepare_charts(result)
            except Exception as exc:
                self.dispatch(self.load_failed, f"Audit could not finish: {exc}")
            else:
                self.dispatch(self.load_complete, result, charts, len(paths))

        threading.Thread(target=worker, name="nexdata-audit", daemon=True).start()

    def finish_loading(self):
        self.loading = False
        self.progress.stop()
        self.progress.grid_remove()
        self.open_button.configure(state="normal")
        self.scan_button.configure(state="normal")
        self.resolve_button.configure(state="normal")
        self.scan_mode.configure(state="normal")

    def load_failed(self, message):
        self.finish_loading()
        self.status_label.configure(text="Audit failed. You can select files and try again.")
        self.show_errors(message)

    def load_complete(self, result, charts, count):
        try:
            self.result = result
            self.loaded_paths = list(self.pending_paths)
            self.records_by_id = {r.get("id"): r for r in result.get("records") or []}
            self.clear_figures()
            for name in TAB_NAMES:
                for child in self.tabs.tab(name).winfo_children():
                    child.destroy()
            self.render_footprint(charts)
            self.render_coverage()
            self.render_knowledge()
            self.render_circle(charts)
            self.render_findings()
            self.render_actions()
            partial = audit_is_partial(result)
            state = "Partial coverage" if partial else "Supported checks finished"
            self.status_label.configure(text=f"{state} | {count} inputs | {len(result.get('records') or [])} records | {len(result.get('findings') or [])} findings")
            self.source_label.configure(text=("REAL PC DATA" if self.source_mode == "pc" else "USER-SELECTED IMPORTS") + " | See Scan coverage for limits and unprovided sources. No missing data is guessed.")
            self.show_errors(error_text(result.get("errors")))
            if any(error.get("blocked_by") for error in result.get("errors") or []):
                self.resolve_button.grid()
            else:
                self.resolve_button.grid_remove()
            mode = "Real PC scan finished" if self.source_mode == "pc" else "User imports"
            self.title("NexData - Personal Data Footprint Auditor | " + mode + (" (partial coverage)" if partial else " (supported checks)"))
        except Exception as exc:
            self.status_label.configure(text="Some audit views could not be displayed.")
            self.show_errors(error_text(result.get("errors")) + f"\nDisplay error: {exc}")
        finally:
            self.finish_loading()

    def scroll_page(self, name):
        frame = ctk.CTkScrollableFrame(self.tabs.tab(name), fg_color="transparent")
        frame.grid(row=0, column=0, sticky="nsew")
        frame.grid_columnconfigure(0, weight=1)
        return frame

    @staticmethod
    def label(parent, text, *, bold=False, color=TEXT, size=14, **pack):
        widget = ctk.CTkLabel(parent, text=str(text), font=("Segoe UI", size, "bold" if bold else "normal"), text_color=color, anchor="w", justify="left", wraplength=1040)
        widget.bind("<Configure>", lambda event: widget.configure(wraplength=max(100, event.width - 8)))
        widget.pack(fill="x", padx=16, pady=4, **pack)
        return widget

    @staticmethod
    def card(parent):
        frame = ctk.CTkFrame(parent, fg_color="#222e3f", corner_radius=10)
        frame.pack(fill="x", padx=8, pady=8)
        return frame

    def new_figure(self, height):
        fig = Figure(figsize=(10.5, height), dpi=100, facecolor=PANEL)
        self.figures.append(fig)
        ax = fig.add_subplot(111)
        ax.set_facecolor(PANEL)
        ax.tick_params(colors=MUTED, labelsize=9)
        for spine in ax.spines.values():
            spine.set_color("#46536a")
        return fig, ax

    def mount_chart(self, parent, fig):
        canvas = FigureCanvasTkAgg(fig, master=parent)
        canvas.draw()
        canvas.get_tk_widget().pack(fill="both", expand=True, padx=6, pady=6)
        self.canvases.append(canvas)

    def render_footprint(self, charts):
        page = self.tabs.tab("Footprint")
        page.grid_rowconfigure(0, weight=0)
        page.grid_rowconfigure(1, weight=1)
        stats = ctk.CTkFrame(page, fg_color="transparent")
        stats.grid(row=0, column=0, sticky="ew", pady=8)
        summary = self.result.get("summary") or {}
        if self.source_mode == "pc":
            values = [("App folders reported", summary.get("laptopDataApps", 0)),
                      ("Selected app data (GB; + = lower bound)", storage_display(self.result)),
                      ("Browser tracker indicators (+ = partial)", tracker_display(self.result))]
        else:
            messages = any(r.get("category") == "message" for r in self.result.get("records") or [])
            values = [("Services found in imports", summary.get("servicesFound", 0)),
                      ("Sensitive items in chats", summary.get("sensitiveHits", 0) if messages else "Not imported"),
                      ("People ranked", len(summary.get("topPeople") or []) if summary.get("topPeople") else "Not available")]
        for col, (title, value) in enumerate(values):
            stats.grid_columnconfigure(col, weight=1, uniform="stats")
            card = ctk.CTkFrame(stats, fg_color="#222e3f")
            card.grid(row=0, column=col, sticky="ew", padx=6)
            self.label(card, value, bold=True, color=CYAN, size=28)
            self.label(card, title, color=MUTED, size=13)
        plot = ctk.CTkFrame(page, fg_color=PANEL)
        plot.grid(row=1, column=0, sticky="nsew")
        self.label(plot, "Your footprint by service group", bold=True, size=19)
        self.label(plot, "Larger circles contain more services. Click a group to see its services, findings and source evidence.", color=MUTED, size=14)
        graph, positions, _ = charts
        fig, ax = self.new_figure(4.0)
        node_ids = list(graph)
        if len(graph) > 1:
            largest = max(float(graph.nodes[n].get("size", 1)) for n in graph)
            nx.draw_networkx_edges(graph, positions, ax=ax, edge_color="#6b7a91", alpha=0.5, width=1.5)
            dots = nx.draw_networkx_nodes(graph, positions, ax=ax,
                node_color=[CLUSTER_COLORS.get(graph.nodes[n].get("label"), "#ffffff") for n in graph],
                node_size=[900 if n == "user" else 300 + 2400 * graph.nodes[n]["size"] / largest for n in graph],
                linewidths=1.5, edgecolors=PANEL)
            dots.set_picker(True)
            labels = {n: (graph.nodes[n]["label"].replace(" & ", " &\n") + f"\n{graph.nodes[n]['size']} services")
                      if n != "user" else "You" for n in graph}
            label_positions = {n: (x, y - 0.24) if n != "user" else (x, y) for n, (x, y) in positions.items()}
            nx.draw_networkx_labels(graph, label_positions, ax=ax, labels=labels, font_color=TEXT,
                                    font_size=14, font_weight="bold", bbox={"facecolor": PANEL, "edgecolor": "none", "alpha": 0.92, "pad": 2})
            ax.set_xlim(-2.6, 2.6)
            ax.set_ylim(-1.65, 1.35)
            def picked(event):
                if event.artist is dots and len(event.ind):
                    node = graph.nodes[node_ids[event.ind[0]]]
                    if node.get("type") == "cluster":
                        self.show_cluster(node)
            fig.canvas.mpl_connect("pick_event", picked)
        else:
            ax.text(0.5, 0.5, "No service records found in these files", ha="center", color=MUTED)
        ax.set_axis_off()
        fig.tight_layout(pad=0.5)
        self.mount_chart(plot, fig)

    def show_cluster(self, cluster):
        popup = ctk.CTkToplevel(self)
        popup.title("Services - " + cluster["label"])
        popup.geometry("900x620")
        popup.transient(self)
        popup.after(100, popup.lift)
        body = ctk.CTkScrollableFrame(popup)
        body.pack(fill="both", expand=True, padx=14, pady=14)
        self.label(body, f"{cluster['label']} | {cluster['size']} services", bold=True, size=20)
        for service in cluster.get("services", []):
            card = self.card(body)
            self.label(card, service["label"], bold=True, color=CYAN, size=18)
            findings = service_findings(self.result, service)
            self.label(card, "\n".join(f["title"] for f in findings) or "No rule finding for this service.", size=14)
            ctk.CTkButton(card, text=f"View {len(service['evidence'])} source records", width=200,
                          command=lambda s=service: self.show_evidence({"title": s["label"], "evidence": s["evidence"]})).pack(anchor="w", padx=16, pady=(6, 12))

    def render_coverage(self):
        page = self.scroll_page("Scan coverage")
        self.label(page, "What was checked, and what is missing", bold=True, size=20)
        self.label(page, "A finished scan covers supported checks only. Folder/log limits, unreadable files and missing imports remain explicit below.", color=MUTED, size=13)
        palette = {"scanned": "#206348", "partial": "#986c28", "unavailable": "#a94450",
                   "not_provided": "#536174", "not_assessed": "#536174"}
        for row in coverage_rows(self.result):
            card = self.card(page)
            status = row.get("status", "not_assessed")
            ctk.CTkLabel(card, text=STATUS_LABELS.get(status, status), fg_color=palette.get(status, "#536174"),
                         corner_radius=7, width=110, height=24, font=("Segoe UI", 11, "bold")).pack(anchor="w", padx=16, pady=(10, 3))
            self.label(card, row["name"], bold=True, size=16)
            self.label(card, row["detail"], color=MUTED, size=13)
            if row.get("source"):
                self.label(card, row["source"], color=MUTED, size=11)

    def render_knowledge(self):
        page = self.scroll_page("What they know")
        self.label(page, "What the scanned sources contain", bold=True, size=20)
        self.label(page, "Found = present in this export. Not found = checked but absent. Not assessed = unknown.", color=MUTED, size=12)
        grid = ctk.CTkFrame(page, fg_color="transparent")
        grid.pack(fill="x", padx=8, pady=12)
        categories = ("location", "interest", "contact", "activity")
        for col, text in enumerate(("Platform",) + categories):
            grid.grid_columnconfigure(col, weight=1, uniform="coverage")
            ctk.CTkLabel(grid, text=text.title(), font=("Segoe UI", 14, "bold")).grid(row=0, column=col, padx=5, pady=6, sticky="ew")
        palette = {"found": ("#206348", "#b3f1cd"), "not_found": ("#4a5361", "#e1e7ef"), "not_assessed": ("#141c29", MUTED)}
        for row, (platform, coverage) in enumerate((self.result.get("coverage") or {}).items(), 1):
            ctk.CTkLabel(grid, text=str(platform), wraplength=210).grid(row=row, column=0, padx=5, pady=5, sticky="ew")
            for col, category in enumerate(categories, 1):
                state = coverage.get(category, "not_assessed")
                bg, fg = palette.get(state, palette["not_assessed"])
                ctk.CTkLabel(grid, text=str(state).replace("_", " "), fg_color=bg, text_color=fg, corner_radius=6, height=34).grid(row=row, column=col, padx=5, pady=5, sticky="ew")
        self.label(page, "Interests and inferences", bold=True, size=18)
        interests = [r for r in self.result.get("records") or [] if r.get("category") == "interest"]
        if not interests:
            self.label(page, "No interest exports loaded. This PC scan does not determine your interests.", color=MUTED)
        for record in interests:
            card = self.card(page)
            origin = record.get("inferenceOrigin")
            tag = "Inferred by platform" if origin == "platform" else "Inferred by this app" if origin or record.get("kind") == "inferred" else "Recorded"
            self.label(card, f"{record.get('platform', 'Unknown platform')}  |  {tag}", color=CYAN, size=12)
            self.label(card, record.get("item", ""))

    def render_circle(self, charts):
        page = self.scroll_page("Inner circle")
        self.label(page, "People found in your imports", bold=True, size=20)
        self.label(page, "People require your own social/chat exports; this PC scan does not guess who your friends are.", color=MUTED, size=12)
        people = sorted((self.result.get("summary") or {}).get("topPeople") or [], key=lambda p: float(p.get("score") or 0), reverse=True)[:10]
        fig, ax = self.new_figure(2.7)
        if people:
            ax.barh([str(p.get("name", "Unknown")) for p in reversed(people)], [float(p.get("score") or 0) for p in reversed(people)], color=CYAN, height=0.65)
            ax.set_xlabel("Interaction score", color=MUTED)
            ax.grid(axis="x", alpha=0.12)
        else:
            ax.text(0.5, 0.5, "No people data imported", ha="center", color=MUTED)
            ax.set_axis_off()
        fig.tight_layout()
        self.mount_chart(page, fig)
        self.label(page, "Timestamps found in the scanned sources", bold=True, size=18)
        self.label(page, "File modification and browser record timestamps; these do not measure how long you used an app.", color=MUTED, size=12)
        fig, ax = self.new_figure(2.3)
        heat = ax.imshow(charts[2], aspect="auto", cmap="YlGnBu", interpolation="nearest")
        ax.set_yticks(range(7), ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"])
        ax.set_xticks(range(24), [str(h) for h in range(24)])
        ax.set_xlabel("Hour of day", color=MUTED)
        colorbar = fig.colorbar(heat, ax=ax, pad=0.02)
        colorbar.ax.tick_params(colors=MUTED)
        colorbar.set_label("Records", color=MUTED)
        fig.tight_layout()
        self.mount_chart(page, fig)

    def render_findings(self):
        page = self.scroll_page("Findings")
        self.label(page, "Findings, backed by your data", bold=True, size=20)
        findings = ordered_findings(self.result)
        if not findings:
            self.label(page, "No findings in these files.", color=MUTED)
        for finding in findings:
            card = self.card(page)
            priority = str(finding.get("priority") or "low")
            ctk.CTkLabel(card, text=priority.upper(), fg_color=PRIORITIES.get(priority, PRIORITIES["low"]), corner_radius=8, width=85, height=24, font=("Segoe UI", 11, "bold")).pack(anchor="w", padx=16, pady=(12, 3))
            self.label(card, finding.get("title", "Untitled finding"), bold=True, size=17)
            self.label(card, finding.get("detail", ""), color=MUTED)
            metric = finding.get("metric") or {}
            if metric:
                self.label(card, f"{metric.get('value', '')} {metric.get('unit', '')}", bold=True, color=CYAN)
            ctk.CTkButton(card, text="Show me the evidence", width=185, command=lambda f=finding: self.show_evidence(f)).pack(anchor="w", padx=16, pady=(6, 14))

    def show_evidence(self, finding):
        popup = ctk.CTkToplevel(self)
        popup.title("Evidence - " + str(finding.get("title", "Finding")))
        popup.geometry("900x620")
        popup.transient(self)
        popup.after(100, popup.lift)
        body = ctk.CTkScrollableFrame(popup)
        body.pack(fill="both", expand=True, padx=14, pady=14)
        self.label(body, finding.get("title", "Evidence"), bold=True, size=18)
        ids = finding.get("evidence") or []
        if not ids:
            self.label(body, "No source records attached to this finding.", color=MUTED)
        for record_id in ids[:50]:
            card = self.card(body)
            record = self.records_by_id.get(record_id)
            if record is None:
                self.label(card, f"{record_id}: record unavailable", color=MUTED)
                continue
            self.label(card, record.get("item", ""), bold=True)
            self.label(card, f"Timestamp: {record.get('timestamp') or 'Not recorded'}\nSource file: {record.get('sourceFile') or '-'}\nRecord reference: {record.get('recordRef') or '-'}\nKind: {record.get('kind') or '-'}", color=MUTED, size=12)
        if len(ids) > 50:
            self.label(body, f"+{len(ids) - 50} more", color=CYAN, bold=True)

    def render_actions(self):
        page = self.scroll_page("Fix first")
        self.label(page, "Your next steps, in priority order", bold=True, size=20)
        self.export_button = ctk.CTkButton(page, text="Export PDF", width=145, command=self.export_pdf, fg_color="#217989")
        self.export_button.pack(anchor="w", padx=16, pady=8)
        self.export_label = self.label(page, "Save a local report with findings and actions.", color=MUTED, size=12)
        findings = ordered_findings(self.result)
        if not findings:
            self.label(page, "No actions suggested for these files.", color=MUTED)
        for index, finding in enumerate(findings, 1):
            card = self.card(page)
            self.label(card, f"{index}. {finding.get('title', 'Review finding')}", bold=True, size=17)
            action = finding.get("action") or {}
            for step_index, step in enumerate(action.get("steps") or [], 1):
                self.label(card, f"{step_index}. {step}", color=MUTED)
            link = str(action.get("link") or "").strip()
            if link:
                button = ctk.CTkButton(card, text=link, anchor="w", fg_color="transparent", text_color=CYAN, hover_color="#30465c", command=lambda url=link: self.open_link(url))
                button.pack(fill="x", padx=10, pady=(4, 12))

    def open_link(self, url):
        try:
            if url.lower().startswith(("https://", "http://")):
                webbrowser.open(url)
        except Exception as exc:
            self.show_errors(f"Could not open link: {exc}")

    def export_pdf(self):
        self.export_button.configure(state="disabled")
        self.export_label.configure(text="Writing PDF locally...")
        snapshot = self.result

        def worker():
            try:
                REPORT_PATH.write_bytes(report_bytes(snapshot))
            except Exception as exc:
                self.dispatch(self.export_complete, f"PDF export failed: {exc}")
            else:
                self.dispatch(self.export_complete, f"Saved: {REPORT_PATH}")

        threading.Thread(target=worker, name="nexdata-pdf", daemon=True).start()

    def export_complete(self, message):
        self.export_button.configure(state="normal")
        self.export_label.configure(text=message)

    def clear_figures(self):
        for canvas in self.canvases:
            canvas.get_tk_widget().destroy()
        for figure in self.figures:
            plt.close(figure)
            figure.clear()
        self.canvases.clear()
        self.figures.clear()

    def close(self):
        self.closing = True
        self.clear_figures()
        self.destroy()


def main():
    NexDataApp().mainloop()


if __name__ == "__main__":
    main()

