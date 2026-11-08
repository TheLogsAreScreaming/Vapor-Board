"""Vapor Board desktop: local boards and private messages, plus opt-in receive-only radio TCP.

Screens are drawn only with the components in ui_theme; wording comes from ui_format.
"""
import queue
import sqlite3
import threading
from datetime import timezone
import subprocess
import sys
import time
import tkinter as tk
from tkinter import ttk
from pathlib import Path
from .config import ShopConfig, load_shop_config
from .status import StatusSnapshot
from .tcp import TcpSettings, ConnectionState
from . import serial_link
from .radio_worker import RadioWorker
from .radio_event_state import RadioDisplayState, reduce_event
from .board_browser import BoardBrowser
from .bbs import BulletinBoard
from .ui_format import friendly_time, radio_presentation, first_line, plural, parse_local_time, local_time_text, schedule_state
from . import ui_theme as theme
from .ui_theme import XS, SM, MD, LG, XL
from tkinter import messagebox, filedialog
from . import alerts
from . import updates
from . import backup as backups
from .export import export_csv
from . import demo as demo_mode
from .radio_replies import RadioReplies
from . import VERSION_LABEL
from . import accounts as staff_accounts
from .customers import CustomerBook, CustomerError

# Sidebar order, grouped so everyday work sits above shop administration.
NAVIGATION = (
    ("WORKSPACE", (("Overview", "◧"), ("Boards", "▤"), ("Messages", "✉"))),
    ("SHOP", (("Customers", "◉"), ("Staff", "⚑"), ("Settings", "⚙"))),
)
DATA_ERRORS = (OSError, ValueError, sqlite3.DatabaseError)


def read_config(path):
    """Shop settings plus a message when shop.json is unreadable (defaults are used instead)."""
    try:
        return load_shop_config(path), None
    except (OSError, ValueError) as exc:  # json.JSONDecodeError is a ValueError
        return ShopConfig(), str(exc)


def short_path(path):
    """~/... form of a path under the home folder, for display."""
    try:
        return "~/" + str(Path(path).relative_to(Path.home()))
    except ValueError:
        return str(path)


def main(argv=None):
    demo = "--demo" in (sys.argv[1:] if argv is None else argv)
    if demo:  # sample shop in its own folder; real data is never opened
        home, demo_account = demo_mode.prepare()
        config, config_error = demo_mode.CONFIG, None
        config_path = home / "shop.json"
    else:
        home, demo_account = Path.home() / ".vapor-board", None
        config_path = home / "shop.json"
        config, config_error = read_config(config_path)
    database = home / "bbs.sqlite"
    transmit = config.transmissions_enabled and not demo  # replies to approved customers' direct messages
    mailbox = config.operator_name.strip()
    # Staff accounts sit in their own database: restoring a backup changes them only if an admin chooses that.
    staff = staff_accounts.StaffDirectory(database.parent / "staff.sqlite")
    session = [None]  # the signed-in staff Account; None while the sign-in screen is up

    def record(action, detail=""):
        """Add a line to the activity log as the signed-in staff member."""
        if session[0] is not None:
            try:
                staff.log(session[0].username, action, detail)
            except DATA_ERRORS:
                pass
    root = tk.Tk()
    root.title(config.shop_name if config.shop_name == "Vapor Board" else f"{config.shop_name} — Vapor Board")
    if demo:
        root.title("Vapor Board demo — sample data, radio off")
    t = theme.apply_theme(root, config.accent_color, config.appearance, config.text_size)
    p = t.palette
    width = min(t.px(1040), root.winfo_screenwidth() - 40)
    height = min(t.px(680), root.winfo_screenheight() - 80)
    root.geometry(f"{width}x{height}")
    root.minsize(min(t.px(900), width), min(t.px(600), height))  # smallest size where every control fits
    mod, key = t.shortcut, t.shortcut_label
    # Space and Return both press a focused button, as on every Mac dialog.
    root.bind_class("TButton", "<Return>", lambda e: e.widget.invoke())

    # ---- frame: sidebar | main area (pages over a status bar) ----------------------------
    sidebar = ttk.Frame(root, style="Sidebar.TFrame", width=t.px(224))
    sidebar.pack(side="left", fill="y")
    sidebar.pack_propagate(False)
    tk.Frame(root, bg=p.border, width=1).pack(side="left", fill="y")
    main_area = ttk.Frame(root)
    main_area.pack(side="left", fill="both", expand=True)

    brand = ttk.Frame(sidebar, style="Sidebar.TFrame", padding=(t.px(LG), t.px(XL), t.px(LG), t.px(LG)))
    brand.pack(fill="x")
    tk.Label(brand, text=config.shop_name.strip()[:1].upper(), bg=p.accent_fill, fg=p.on_accent,
             font=t.fonts["monogram"], width=2, pady=t.px(4)).pack(side="left", anchor="n")
    names = ttk.Frame(brand, style="Sidebar.TFrame")
    names.pack(side="left", fill="x", expand=True, padx=(t.px(MD), 0))
    ttk.Label(names, text=config.shop_name, style="Sidebar.Brand.TLabel", wraplength=t.px(140)).pack(anchor="w")
    ttk.Label(names, text="Local bulletin board", style="Sidebar.Caption.TLabel").pack(anchor="w")

    page_host = ttk.Frame(main_area)
    page_host.rowconfigure(0, weight=1)
    page_host.columnconfigure(0, weight=1)
    pages, nav_buttons, nav_icons, on_show, current = {}, {}, {}, {}, ["Overview"]
    toast = theme.Toast(main_area, t)

    def notify(kind, title, message=""):
        """Non-blocking feedback: success fades on its own, problems stay until dismissed."""
        toast.show(kind, title, message)

    def show_page(name):
        current[0] = name
        for other, button in nav_buttons.items():
            button.configure(style="NavActive.TButton" if other == name else "Nav.TButton")
            nav_icons[other].configure(bg=t.nav_colours["active" if other == name else "idle"],
                                       fg=p.accent_text if other == name else p.muted)
        # Every page sits in the same grid cell and the selected one is raised.
        # Swapping with pack_forget/pack left grid-managed widgets unpainted on macOS Tk.
        pages[name].tkraise()
        if name in on_show:
            on_show[name]()

    def add_page(name, glyph, subtitle):
        page = ttk.Frame(page_host, padding=(t.px(28), t.px(24), t.px(28), t.px(LG)))
        page.page_name = name
        page.grid(row=0, column=0, sticky="nsew")
        header = ttk.Frame(page)
        header.pack(fill="x", pady=(0, t.px(18)))
        actions = ttk.Frame(header)
        actions.pack(side="right", anchor="s")
        heading = ttk.Frame(header)
        heading.pack(side="left", fill="x", expand=True)
        ttk.Label(heading, text=name, style="Title.TLabel").pack(anchor="w")
        ttk.Label(heading, text=subtitle, style="Muted.TLabel", wraplength=t.px(520), justify="left").pack(anchor="w", pady=(2, 0))
        pages[name] = page
        button = ttk.Button(sidebar, text=name, style="Nav.TButton", command=lambda: show_page(name))
        button.page_name = name
        button.pack(fill="x", padx=t.px(SM), pady=1)
        # The icon sits in a fixed-width slot so labels line up whatever the glyph's width.
        icon = tk.Label(button, text=glyph, bg=p.sidebar, fg=p.muted, font=t.fonts["glyph"], width=2, cursor="hand2")
        icon.place(x=t.px(12), rely=0.5, anchor="w")
        icon.bind("<Button-1>", lambda _e: button.invoke())
        button.bind("<Enter>", lambda _e: icon.configure(bg=t.nav_colours["active" if current[0] == name else "hover"]), add="+")
        button.bind("<Leave>", lambda _e: icon.configure(bg=t.nav_colours["active" if current[0] == name else "idle"]), add="+")
        nav_icons[name] = icon
        nav_buttons[name] = button
        return page, actions

    subtitles = {
        "Overview": "What's happening at your shop, at a glance.",
        "Boards": "Notices and discussions for your shop. Stored on this Mac only.",
        "Messages": f"Private messages for {mailbox}. Kept on this Mac and never sent over the radio.",
        "Customers": "Approve customers after checking ID in person, and choose which boards they can read.",
        "Staff": "Who can sign in to this Mac, and what they have done.",
        "Settings": "How this copy of Vapor Board is set up.",
    }
    # Search box under the shop name; results open on their own page (not in the sidebar list).
    search_text = tk.StringVar()
    search_box = ttk.Frame(sidebar, style="Sidebar.TFrame", padding=(t.px(LG), 0, t.px(LG), 0))
    search_box.pack(fill="x")
    search_entry = ttk.Entry(search_box, name="search", textvariable=search_text, width=10)
    search_entry.pack(fill="x")
    ttk.Label(search_box, text=f"Search posts and messages  ·  {key}F", style="Sidebar.Caption.TLabel").pack(anchor="w", pady=(t.px(XS), 0))

    # Pages are built in navigation order so each section label sits above its pages.
    page_parts = {}
    for section, entries in NAVIGATION:
        ttk.Label(sidebar, text=section, style="Sidebar.Section.TLabel").pack(anchor="w", padx=t.px(20), pady=(t.px(LG), t.px(XS)))
        for name, glyph in entries:
            page_parts[name] = add_page(name, glyph, subtitles[name])
    overview_page, overview_actions = page_parts["Overview"]
    board_page, board_actions = page_parts["Boards"]
    messages_page, messages_actions = page_parts["Messages"]
    customers_page, _ = page_parts["Customers"]
    staff_page, staff_actions = page_parts["Staff"]
    settings_page, settings_actions = page_parts["Settings"]

    messages_badge = tk.Label(nav_buttons["Messages"], name="messages_badge", bg=p.accent_fill, fg=p.on_accent,
                              font=t.fonts["label"], padx=t.px(7), pady=0, cursor="hand2")
    messages_badge.bind("<Button-1>", lambda _e: show_page("Messages"))

    # Radio summary pinned to the bottom of the sidebar.
    sidebar_status = ttk.Frame(sidebar, style="Sidebar.TFrame", padding=(t.px(20), t.px(LG)))
    sidebar_status.pack(side="bottom", fill="x")
    signed_in_row = ttk.Frame(sidebar_status, style="Sidebar.TFrame")
    signed_in_row.pack(fill="x", pady=(0, t.px(MD)))
    signed_in_name = tk.StringVar(value="")
    ttk.Label(signed_in_row, name="signed_in", textvariable=signed_in_name, style="Sidebar.Caption.TLabel").pack(side="left")
    lock_button = ttk.Button(signed_in_row, text="Lock", style="Sidebar.Link.TButton")
    lock_button.pack(side="right")
    ttk.Label(sidebar_status, text="RADIO", style="Sidebar.Section.TLabel").pack(anchor="w")
    sidebar_pill = theme.Pill(sidebar_status, t, p.sidebar, "neutral", "Not connected")
    sidebar_pill.label.pack(anchor="w", pady=(t.px(6), t.px(XS)))
    ttk.Label(sidebar_status, text="Replies to approved customers" if transmit else "Listen-only · transmit off",
              style="Sidebar.Caption.TLabel").pack(anchor="w")

    # ---- shared state ---------------------------------------------------------------------
    counters = tk.StringVar(value="0")
    board_count = tk.StringVar(value="0")
    unread_count = tk.StringVar(value="0")
    selected_boards, shown_posts, shown_mail = [], [], []
    has_posts, has_mail = [False], [False]

    # ==== Boards ===========================================================================
    # Trusted local operator view only. Do not expose this to remote customers.
    board_body = ttk.Frame(board_page)
    board_body.pack(fill="both", expand=True)
    board_body.columnconfigure(1, weight=1)
    board_body.rowconfigure(0, weight=1)
    board_column = ttk.Frame(board_body, width=t.px(268))
    board_column.grid(row=0, column=0, sticky="ns", padx=(0, t.px(LG)))
    board_column.pack_propagate(False)
    editor_column = ttk.Frame(board_body)
    editor_column.grid(row=0, column=1, sticky="nsew")

    boards_card = theme.Card(board_column, t, "Boards").pack(fill="x")
    board_list = theme.ListView(boards_card.body, t, height=4, placeholder="No boards yet")
    board_list.frame.pack(fill="x")
    ttk.Label(boards_card.body, text="NEW BOARD", style="Card.Field.TLabel").pack(anchor="w", pady=(t.px(MD), t.px(XS)))
    operator_controls = ttk.Frame(boards_card.body, style="Card.TFrame")
    operator_controls.pack(fill="x")
    board_name = tk.StringVar()
    board_entry = ttk.Entry(operator_controls, textvariable=board_name, width=10)
    board_entry.pack(side="left", fill="x", expand=True)

    posts_card = theme.Card(board_column, t, "Posts", "Choose a board to see its posts.").pack(fill="both", expand=True, pady=(t.px(LG), 0))
    post_list = theme.ListView(posts_card.body, t, height=4, placeholder="Nothing to show")
    post_list.frame.pack(fill="both", expand=True)

    reading_card = theme.Card(editor_column, t, "Select a board", "Posts appear here, newest first.").pack(fill="both", expand=True)
    _holder, posts = theme.text_area(reading_card.body, t, height=5, readonly=True)
    _holder.pack(fill="both", expand=True)

    composer = theme.Card(editor_column, t, "New post", f"Write a notice, then publish it ({key}↩).").pack(fill="x", pady=(t.px(LG), 0))
    author_row = ttk.Frame(composer.body, style="Card.TFrame")
    author_row.pack(fill="x", pady=(0, t.px(SM)))
    ttk.Label(author_row, text="AUTHOR", style="Card.Field.TLabel").pack(side="left")
    author_name = tk.StringVar(value=mailbox)
    author_entry = ttk.Entry(author_row, textvariable=author_name)
    author_entry.pack(side="left", fill="x", expand=True, padx=(t.px(MD), 0))
    # Optional schedule: customers (kiosk, radio) see the post only between these local times.
    schedule_row = ttk.Frame(composer.body, style="Card.TFrame")
    schedule_row.pack(fill="x", pady=(0, t.px(SM)))
    show_from, show_until = tk.StringVar(), tk.StringVar()
    ttk.Label(schedule_row, text="SHOW FROM", style="Card.Field.TLabel").pack(side="left")
    from_entry = ttk.Entry(schedule_row, name="publish_at", textvariable=show_from, width=9)
    from_entry.pack(side="left", fill="x", expand=True, padx=(t.px(SM), t.px(MD)))
    ttk.Label(schedule_row, text="UNTIL", style="Card.Field.TLabel").pack(side="left")
    until_entry = ttk.Entry(schedule_row, name="expires_at", textvariable=show_until, width=9)
    until_entry.pack(side="left", fill="x", expand=True, padx=(t.px(SM), 0))
    _holder, post_editor = theme.text_area(composer.body, t, height=4)
    _holder.pack(fill="x")

    def schedule_values():
        """(publish_at, expires_at) in UTC from the schedule fields; raises ValueError for unreadable dates."""
        return parse_local_time(show_from.get()), parse_local_time(show_until.get(), end_of_day=True)
    composer.outer.pack_configure(side="bottom", before=reading_card.outer)
    editing = [None]  # post being edited, or None when writing a new one
    new_author = [mailbox]  # author typed for new posts, restored after an edit
    composer_hint = tk.StringVar(value=f"{key}↩ publish")

    def current_board():
        index = board_list.selected()
        return selected_boards[index] if index is not None and index < len(selected_boards) else None

    def set_composer_mode(entry=None):
        """Switch the composer between writing a new post and editing an existing one."""
        editing[0] = entry
        board = current_board()
        if entry is not None:
            composer.title_var.set(f'Editing post #{entry["id"]}')
            composer.subtitle_var.set(f'By {entry["author"]} · Save to update it, or Cancel to discard changes.')
            publish_button.configure(text="Save changes")
            cancel_button.state(["!disabled"])
            author_name.set(entry["author"])  # edits keep the original author
            show_from.set(local_time_text(entry.get("publish_at")))
            show_until.set(local_time_text(entry.get("expires_at")))
            author_entry.state(["disabled"])
            composer_hint.set(f"{key}↩ save  ·  Esc cancel")
        else:
            composer.title_var.set(f'New post in {board["name"]}' if board else "New post")
            composer.subtitle_var.set(f"Write a notice, then publish it ({key}↩)." if board else "Choose a board first, then write your post.")
            publish_button.configure(text="Publish post")
            cancel_button.state(["disabled"])
            if author_entry.instate(["disabled"]):
                author_name.set(new_author[0])
                show_from.set("")
                show_until.set("")
            author_entry.state(["!disabled"])
            composer_hint.set(f"{key}↩ publish")
        publish_button.state(["!disabled"] if board else ["disabled"])

    def update_post_actions():
        entry = selected_post()
        for button in (pin_button, edit_button, delete_button):
            button.state(["!disabled"] if entry is not None else ["disabled"])
        pin_button.configure(text="Unpin" if entry is not None and entry.get("pinned_at") else "Pin")

    def update_board_actions():
        index = board_list.selected()
        last = len(selected_boards) - 1
        up_button.state(["!disabled"] if index is not None and 0 < index <= last else ["disabled"])
        down_button.state(["!disabled"] if index is not None and index < last else ["disabled"])

    def show_posts(_event=None, keep=None):
        nonlocal shown_posts
        board = current_board()
        if board is None:
            return
        error = None
        try:
            shown_posts = BoardBrowser(database).posts(board["id"])
        except DATA_ERRORS as exc:
            shown_posts = []
            error = f"Couldn't read posts: {exc}"
        reading_card.title_var.set(board["name"])
        order = " · pinned first, then newest" if any(entry.get("pinned_at") for entry in shown_posts) else " · newest first"
        reading_card.subtitle_var.set(plural(len(shown_posts), "post") + order if shown_posts else "No posts yet")
        posts_card.subtitle_var.set(plural(len(shown_posts), "post") if shown_posts else "Nothing posted yet")
        posts.configure(state="normal")
        posts.delete("1.0", "end")
        for index, entry in enumerate(shown_posts):
            if index:
                posts.insert("end", "\n\n")
            start = posts.index("end-1c")
            posts.insert("end", entry["author"], "author")
            pinned = "  ·  Pinned" if entry.get("pinned_at") else ""
            state = schedule_state(entry)
            timing = (f'  ·  Shows from {friendly_time(entry["publish_at"])}' if state == "scheduled"
                      else "  ·  Expired, hidden from customers" if state == "expired"
                      else f'  ·  Until {friendly_time(entry["expires_at"])}' if entry.get("expires_at") else "")
            posts.insert("end", f'  ·  #{entry["id"]}  ·  {friendly_time(entry["created_at"])}{pinned}{timing}\n', "meta")
            posts.insert("end", entry["body"])
            posts.mark_set(f"post{index}", start)
            posts.mark_gravity(f"post{index}", "left")
        if not shown_posts:
            posts.insert("1.0", error or "No posts yet.", "placeholder")
        posts.configure(state="disabled")
        post_list.set_rows([(f'{"◆  " if entry.get("pinned_at") else ""}{"◷  " if schedule_state(entry) != "live" else ""}'
                             f'{entry["author"]} — {first_line(entry["body"], 40)}',
                             ("placeholder",) if schedule_state(entry) == "expired" else ())
                            for entry in shown_posts],
                           placeholder=error or "No posts yet")
        if keep is not None:
            index = next((i for i, entry in enumerate(shown_posts) if entry["id"] == keep), None)
            if index is not None:
                post_list.select(index)
                highlight_post(index)
        if editing[0] is None or all(entry["id"] != editing[0]["id"] for entry in shown_posts):
            set_composer_mode(None)
        update_post_actions()

    def highlight_post(index):
        posts.tag_remove("selected", "1.0", "end")
        if f"post{index}" in posts.mark_names():
            end = f"post{index + 1}" if f"post{index + 1}" in posts.mark_names() and index + 1 < len(shown_posts) else "end"
            posts.tag_add("selected", f"post{index}", end)
            posts.see(f"post{index}")

    def refresh_boards(keep=None):
        nonlocal selected_boards
        previous = current_board()
        keep = keep if keep is not None else (previous["id"] if previous else None)
        error = None
        if not database.exists():  # nothing written yet; don't create the database just to read it
            selected_boards = []
        else:
            try:
                selected_boards = BoardBrowser(database).boards()
            except DATA_ERRORS as exc:
                selected_boards, error = [], f"Couldn't open the local database: {exc}"
        board_list.set_rows([(board["name"], ()) for board in selected_boards],
                            placeholder=error or "No boards yet — add one below", tag="error" if error else "placeholder")
        board_count.set(str(len(selected_boards)))
        index = next((i for i, board in enumerate(selected_boards) if board["id"] == keep), None)
        if index is None and selected_boards:
            index = 0
        if index is not None:
            board_list.select(index)
            show_posts()
        update_board_actions()
        if index is None:
            reading_card.title_var.set("No boards yet")
            reading_card.subtitle_var.set("Create a board on the left to start posting notices.")
            post_list.set_rows([], placeholder="No posts yet")
            posts.configure(state="normal")
            posts.delete("1.0", "end")
            posts.insert("1.0", "Boards hold notices such as opening hours, closures and news.", "placeholder")
            posts.configure(state="disabled")
            set_composer_mode(None)
            update_post_actions()

    # Local operator actions only: do not expose these to network customers.
    def create_local_board():
        try:
            database.parent.mkdir(parents=True, exist_ok=True)
            board_id = BulletinBoard(database).create_board(board_name.get())
        except DATA_ERRORS as exc:
            notify("danger", "Board not created", str(exc))
            board_entry.focus_set()
            return
        notify("success", "Board created", f"“{board_name.get().strip()}” is ready for posts.")
        record("board created", board_name.get().strip())
        board_name.set("")
        refresh_boards(keep=board_id)
        post_editor.focus_set()

    ttk.Button(operator_controls, text="Add board", command=create_local_board).pack(side="left", padx=(t.px(SM), 0))

    def move_selected_board(offset):
        board = current_board()
        if board is None:
            return "break"
        try:
            moved = BulletinBoard(database).move_board(board["id"], offset)
        except DATA_ERRORS as exc:
            notify("danger", "Board not moved", str(exc))
            return "break"
        if moved:
            record("board moved", f'{board["name"]} {"up" if offset < 0 else "down"}')
            refresh_boards(keep=board["id"])
        return "break"

    def toggle_pin(_event=None):
        entry = selected_post()
        board = current_board()
        if entry is None or board is None:
            return
        pin = not entry.get("pinned_at")
        try:
            BulletinBoard(database).pin_post(entry["id"], pin)
        except DATA_ERRORS as exc:
            notify("danger", "Post not pinned" if pin else "Post not unpinned", str(exc))
            return
        show_posts(keep=entry["id"])
        record("post pinned" if pin else "post unpinned", f'#{entry["id"]} in {board["name"]}')
        notify("success", "Post pinned" if pin else "Post unpinned",
               f'It stays at the top of {board["name"]}.' if pin else "It's back in date order.")
    board_entry.bind("<Return>", lambda _e: create_local_board())

    def save_local_post():
        board = current_board()
        if board is None:
            notify("warning", "Choose a board first", "Pick the board this post belongs to.")
            return
        try:
            BulletinBoard(database).post(board["id"], author_name.get(), post_editor.get("1.0", "end-1c"), *schedule_values())
        except DATA_ERRORS as exc:
            notify("danger", "Post not published", str(exc))
            return
        post_editor.delete("1.0", "end")
        show_from.set("")
        show_until.set("")
        has_posts[0] = True
        show_posts()
        notify("success", "Post published", f'Added to {board["name"]}.')
        record("post published", board["name"])

    def selected_post():
        index = post_list.selected()
        return shown_posts[index] if index is not None and index < len(shown_posts) else None

    def post_chosen(index):
        highlight_post(index)
        update_post_actions()

    post_list.on_select = post_chosen

    def edit_selected_post(_event=None):
        entry = selected_post()
        if entry is None:
            return
        if editing[0] is None:
            new_author[0] = author_name.get()
        set_composer_mode(entry)
        post_editor.delete("1.0", "end")
        post_editor.insert("1.0", entry["body"])
        post_editor.focus_set()

    def update_selected_post():
        entry = editing[0]
        if entry is None:
            return
        try:
            publish_at, expires_at = BulletinBoard._schedule(*schedule_values())  # check before changing anything
            bbs = BulletinBoard(database)
            bbs.edit_post(entry["id"], post_editor.get("1.0", "end-1c"))
            bbs.set_schedule(entry["id"], publish_at, expires_at)
        except DATA_ERRORS as exc:
            notify("danger", "Post not updated", str(exc))
            return
        post_editor.delete("1.0", "end")
        set_composer_mode(None)
        show_posts(keep=entry["id"])
        record("post edited", f'#{entry["id"]}')
        notify("success", "Post updated")

    def cancel_edit(_event=None):
        if editing[0] is not None:
            post_editor.delete("1.0", "end")
            set_composer_mode(None)

    def delete_selected_post(_event=None):
        entry = selected_post()
        if entry is None:
            return
        board = current_board()
        if not messagebox.askyesno("Delete this post?",
                                   f'Post #{entry["id"]} by {entry["author"]} will be removed from '
                                   f'{board["name"] if board else "this board"}. This can’t be undone.',
                                   icon="warning", default="no", parent=root):
            return
        try:
            BulletinBoard(database).delete_post(entry["id"])
        except DATA_ERRORS as exc:
            notify("danger", "Post not deleted", str(exc))
            return
        if editing[0] is not None and editing[0]["id"] == entry["id"]:
            post_editor.delete("1.0", "end")
            set_composer_mode(None)
        show_posts()
        record("post deleted", f'#{entry["id"]} by {entry["author"]}')
        notify("success", "Post deleted")

    def publish_or_save(_event=None):
        update_selected_post() if editing[0] is not None else save_local_post()
        return "break"

    pin_button = ttk.Button(reading_card.actions, text="Pin", command=toggle_pin)
    pin_button.pack(side="left")
    edit_button = ttk.Button(reading_card.actions, text="Edit", command=edit_selected_post)
    edit_button.pack(side="left", padx=(t.px(SM), 0))
    delete_button = ttk.Button(reading_card.actions, text="Delete", style="Danger.TButton", command=delete_selected_post)
    delete_button.pack(side="left", padx=(t.px(SM), 0))
    # Move the chosen board up or down the list (also Option-↑ / Option-↓ in the list).
    up_button = ttk.Button(boards_card.actions, text="↑", style="Ghost.TButton", command=lambda: move_selected_board(-1))
    up_button.pack(side="left")
    down_button = ttk.Button(boards_card.actions, text="↓", style="Ghost.TButton", command=lambda: move_selected_board(1))
    down_button.pack(side="left")
    ttk.Button(boards_card.actions, text="Refresh", style="Ghost.TButton", command=refresh_boards).pack(side="left", padx=(t.px(XS), 0))
    for modifier in ("Option", "Alt"):
        try:
            board_list.tree.bind(f"<{modifier}-Up>", lambda _e: move_selected_board(-1))
            board_list.tree.bind(f"<{modifier}-Down>", lambda _e: move_selected_board(1))
        except tk.TclError:  # "Option" only exists on macOS
            pass

    post_actions = ttk.Frame(composer.body, style="Card.TFrame")
    post_actions.pack(fill="x", pady=(t.px(MD), 0))
    publish_button = ttk.Button(post_actions, text="Publish post", style="Accent.TButton", command=publish_or_save)
    publish_button.pack(side="right")
    cancel_button = ttk.Button(post_actions, text="Cancel", style="Ghost.TButton", command=cancel_edit)
    cancel_button.pack(side="right", padx=(0, t.px(SM)))
    ttk.Label(post_actions, textvariable=composer_hint, style="Card.Caption.TLabel").pack(side="left")
    board_list.on_select = lambda _index: (show_posts(), update_board_actions())
    post_list.tree.bind("<Double-1>", edit_selected_post)
    post_list.tree.bind("<Return>", edit_selected_post)
    post_list.tree.bind("<BackSpace>", delete_selected_post)
    post_list.tree.bind("<Delete>", delete_selected_post)
    post_editor.bind(f"<{mod}-Return>", publish_or_save)
    post_editor.bind("<Escape>", cancel_edit)

    def new_post():
        show_page("Boards")
        cancel_edit()
        (post_editor if current_board() else board_entry).focus_set()

    ttk.Button(board_actions, text="New post", style="Accent.TButton", command=new_post).pack()

    # ==== Messages =========================================================================
    # Private messages for the shared shop mailbox named in shop.json. Every signed-in staff
    # member reads and sends as that mailbox; the sender is never typed in.
    mail_view = ["threads"]  # threads (one row per person) | inbox | sent
    EMPTY_MAIL = {"threads": "No conversations yet", "inbox": "No messages yet", "sent": "Nothing sent yet"}
    mail_body = ttk.Frame(messages_page)
    mail_body.pack(fill="both", expand=True)
    mail_body.columnconfigure(1, weight=1)
    mail_body.rowconfigure(0, weight=1)
    mail_column = ttk.Frame(mail_body, width=t.px(290))
    mail_column.grid(row=0, column=0, sticky="ns", padx=(0, t.px(LG)))
    mail_column.pack_propagate(False)
    mail_reader_column = ttk.Frame(mail_body)
    mail_reader_column.grid(row=0, column=1, sticky="nsew")

    mail_card = theme.Card(mail_column, t).pack(fill="both", expand=True)
    mail_tabs = ttk.Frame(mail_card.body, style="Card.TFrame")
    mail_tabs.pack(fill="x")
    mail_list = theme.ListView(mail_card.body, t, height=8, placeholder="No messages yet")
    mail_list.frame.pack(fill="both", expand=True, pady=(t.px(MD), 0))

    reader_card = theme.Card(mail_reader_column, t, "Select a message", "Pick one from the list to read it.").pack(fill="both", expand=True)
    _holder, reader = theme.text_area(reader_card.body, t, height=5, readonly=True)
    _holder.pack(fill="both", expand=True)

    def show_in_reader(entry=None, note="Select a message to read it.", thread=None):
        reader.configure(state="normal")
        reader.delete("1.0", "end")
        if entry is None:
            empty = {"threads": "No conversations yet", "inbox": "Inbox is empty", "sent": "Nothing sent yet"}[mail_view[0]]
            reader_card.title_var.set(("No conversation selected" if mail_view[0] == "threads" else "No message selected") if shown_mail else empty)
            reader_card.subtitle_var.set("Messages stay on this Mac.")
            reader.insert("1.0", note, "placeholder")
        elif thread is not None:
            reader_card.title_var.set(f'Conversation with {entry["other"]}')
            reader_card.subtitle_var.set(f'{plural(len(thread), "message")}  ·  last {friendly_time(entry["last_at"])}')
            for number, message in enumerate(thread):
                if number:
                    reader.insert("end", "\n\n")
                reader.insert("end", "You" if message["sender"] == mailbox else message["sender"], "author")
                reader.insert("end", f'  ·  {friendly_time(message["created_at"])}\n', "meta")
                reader.insert("end", message["body"])
            reader.see("end")  # newest at the bottom, as in any chat
        else:
            incoming = mail_view[0] == "inbox"
            reader_card.title_var.set(("From " if incoming else "To ") + (entry["sender"] if incoming else entry["recipient"]))
            reader_card.subtitle_var.set(("Received " if incoming else "Sent ") + friendly_time(entry["created_at"]))
            reader.insert("end", entry["body"])
        reader.configure(state="disabled")
        reply_button.state(["!disabled"] if entry is not None and mail_view[0] != "sent" else ["disabled"])

    def refresh_mail():
        nonlocal shown_mail
        error = None
        if not database.exists():  # nothing written yet; don't create the database just to read it
            shown_mail, unread = [], 0
        else:
            try:
                bbs = BulletinBoard(database)
                shown_mail = {"threads": bbs.conversations, "inbox": bbs.inbox, "sent": bbs.sent}[mail_view[0]](mailbox)
                unread = bbs.unread_count(mailbox)
                has_mail[0] = has_mail[0] or bool(shown_mail)
            except DATA_ERRORS as exc:
                shown_mail, unread, error = [], 0, f"Couldn't read messages: {exc}"
        rows = []
        for entry in shown_mail:
            if mail_view[0] == "threads":
                fresh = entry["unread"] > 0
                count = f' ({entry["unread"]})' if fresh else ""
                preview = ("You: " if entry["last_from_user"] else "") + first_line(entry["last_body"], 26)
                rows.append((f'{"●  " if fresh else "    "}{entry["other"]}{count} — {preview}', ("strong",) if fresh else ()))
            elif mail_view[0] == "inbox":
                fresh = entry["read_at"] is None
                rows.append((f'{"●  " if fresh else "    "}{entry["sender"]} — {first_line(entry["body"], 32)}', ("strong",) if fresh else ()))
            else:
                rows.append((f'To {entry["recipient"]} — {first_line(entry["body"], 32)}', ()))
        mail_list.set_rows(rows, placeholder=error or EMPTY_MAIL[mail_view[0]],
                           tag="error" if error else "placeholder")
        unread_count.set(str(unread))
        if unread:
            messages_badge.configure(text=str(unread))
            messages_badge.place(relx=1.0, x=-t.px(10), rely=0.5, anchor="e")
        else:
            messages_badge.place_forget()
        inbox_tab.configure(text=f"Inbox  {unread}" if unread else "Inbox")
        if not shown_mail:
            show_in_reader(note=error or EMPTY_MAIL[mail_view[0]] + ".")
        elif mail_list.selected() is None:
            show_in_reader()  # nothing chosen yet: prompt to pick a message; Reply waits for one

    def switch_mail_view(view):
        mail_view[0] = view
        for name, tab in mail_tabs_by_view.items():
            tab.configure(style="SegmentActive.TButton" if view == name else "Segment.TButton")
        refresh_mail()
        show_in_reader()

    def open_thread(index):
        other = shown_mail[index]["other"]
        try:
            bbs = BulletinBoard(database)
            if shown_mail[index]["unread"]:
                bbs.mark_conversation_read(mailbox, other)
            thread = bbs.conversation(mailbox, other)
        except DATA_ERRORS as exc:
            notify("danger", "Couldn't open the conversation", str(exc))
            return
        if shown_mail[index]["unread"]:
            refresh_mail()
            index = next((i for i, row in enumerate(shown_mail) if row["other"] == other), None)
            if index is None:
                return
            mail_list.select(index)
        show_in_reader(shown_mail[index], thread=thread)

    def open_message(index):
        if index >= len(shown_mail):
            return
        if mail_view[0] == "threads":
            open_thread(index)
            return
        entry = shown_mail[index]
        show_in_reader(entry)
        if mail_view[0] == "inbox" and entry["read_at"] is None:
            try:
                BulletinBoard(database).mark_read(mailbox, entry["id"])
            except DATA_ERRORS as exc:
                notify("danger", "Couldn't mark the message read", str(exc))
                return
            refresh_mail()
            mail_list.select(index)
            show_in_reader(shown_mail[index] if index < len(shown_mail) else None)

    mail_list.on_select = open_message
    mail_tabs_by_view = {}
    for view, label in (("threads", "Threads"), ("inbox", "Inbox"), ("sent", "Sent")):
        tab = ttk.Button(mail_tabs, text=label, style="SegmentActive.TButton" if view == mail_view[0] else "Segment.TButton",
                         command=lambda view=view: switch_mail_view(view))
        tab.pack(side="left", fill="x", expand=True)
        mail_tabs_by_view[view] = tab
    inbox_tab = mail_tabs_by_view["inbox"]
    ttk.Button(mail_card.body, text="Refresh", style="Link.TButton", command=refresh_mail).pack(anchor="w", pady=(t.px(SM), 0))

    mail_composer = theme.Card(mail_reader_column, t, "New message", f"From {mailbox}. Messages never leave this Mac.").pack(fill="x", pady=(t.px(LG), 0))
    to_row = ttk.Frame(mail_composer.body, style="Card.TFrame")
    to_row.pack(fill="x", pady=(0, t.px(SM)))
    ttk.Label(to_row, text="TO", style="Card.Field.TLabel", width=7).pack(side="left")
    recipient_name = tk.StringVar()
    to_entry = ttk.Entry(to_row, textvariable=recipient_name)
    to_entry.pack(side="left", fill="x", expand=True)
    _holder, mail_editor = theme.text_area(mail_composer.body, t, height=4)
    _holder.pack(fill="x")
    mail_composer.outer.pack_configure(side="bottom", before=reader_card.outer)

    def send_message(_event=None):
        recipient = recipient_name.get().strip()
        try:
            database.parent.mkdir(parents=True, exist_ok=True)
            BulletinBoard(database).send_mail(mailbox, recipient_name.get(), mail_editor.get("1.0", "end-1c"))
        except DATA_ERRORS as exc:
            notify("danger", "Message not sent", str(exc))
            return "break"
        recipient_name.set("")
        mail_editor.delete("1.0", "end")
        mail_composer.title_var.set("New message")
        has_mail[0] = True
        if mail_view[0] == "threads":  # stay in the conversation and show the new message in it
            refresh_mail()
            index = next((i for i, row in enumerate(shown_mail) if row["other"] == recipient), None)
            if index is not None:
                mail_list.select(index)
                open_thread(index)
        else:
            switch_mail_view("sent")
        record("message sent", f"to {recipient}")
        notify("success", "Message sent", f"Delivered to {recipient}'s inbox on this Mac.")
        return "break"

    def reply_to_message():
        index = mail_list.selected()
        if mail_view[0] == "sent" or index is None or index >= len(shown_mail):
            return
        sender = shown_mail[index]["other" if mail_view[0] == "threads" else "sender"]
        recipient_name.set(sender)
        mail_composer.title_var.set(f"Reply to {sender}")
        mail_editor.focus_set()

    reply_button = ttk.Button(reader_card.actions, text="Reply", command=reply_to_message)
    reply_button.pack()
    mail_actions = ttk.Frame(mail_composer.body, style="Card.TFrame")
    mail_actions.pack(fill="x", pady=(t.px(MD), 0))
    ttk.Button(mail_actions, text="Send message", style="Accent.TButton", command=send_message).pack(side="right")
    ttk.Label(mail_actions, text=f"{key}↩ send", style="Card.Caption.TLabel").pack(side="left")
    mail_editor.bind(f"<{mod}-Return>", send_message)
    to_entry.bind("<Return>", lambda _e: (mail_editor.focus_set(), "break")[1])

    def new_message():
        show_page("Messages")
        mail_composer.title_var.set("New message")
        recipient_name.set("")
        to_entry.focus_set()

    ttk.Button(messages_actions, text="New message", style="Accent.TButton", command=new_message).pack()
    on_show["Messages"] = refresh_mail

    # ==== Customers ========================================================================
    # Customer records and the boards customers may read. Staff approve each customer only
    # after checking a government ID in person; no ID details are stored.
    customer_book = CustomerBook(database)
    cust_body = ttk.Frame(customers_page)
    cust_body.pack(fill="both", expand=True)
    cust_body.columnconfigure(0, weight=3, uniform="customers")
    cust_body.columnconfigure(1, weight=2, uniform="customers")
    cust_body.rowconfigure(0, weight=1)
    cust_card = theme.Card(cust_body, t).grid(row=0, column=0, sticky="nsew", padx=(0, t.px(LG)))
    cust_tabs = ttk.Frame(cust_card.body, style="Card.TFrame")
    cust_tabs.pack(fill="x")
    cust_view = ["customers"]  # customers | boards
    cust_list = theme.ListView(cust_card.body, t, height=6, placeholder="No customers yet — add one on the right")
    cust_list.frame.pack(fill="both", expand=True, pady=(t.px(MD), 0))
    cust_detail = tk.StringVar(value="")
    ttk.Label(cust_card.body, textvariable=cust_detail, style="Card.Caption.TLabel", wraplength=t.px(330),
              justify="left").pack(anchor="w", pady=(t.px(SM), 0))
    cust_actions = ttk.Frame(cust_card.body, style="Card.TFrame")
    cust_actions.pack(fill="x", pady=(t.px(SM), 0))
    shown_customers, shown_visibility = [], []

    def selected_customer():
        index = cust_list.selected()
        return shown_customers[index] if cust_view[0] == "customers" and index is not None and index < len(shown_customers) else None

    def selected_visibility():
        index = cust_list.selected()
        return shown_visibility[index] if cust_view[0] == "boards" and index is not None and index < len(shown_visibility) else None

    def update_customer_actions(_index=None):
        customer = selected_customer()
        if cust_view[0] == "customers":
            for button in (approve_button, revoke_button, remove_button):
                button.pack(side="left", padx=(0, t.px(SM)))
            visibility_button.pack_forget()
            approve_button.state(["!disabled"] if customer is not None and not customer.approved else ["disabled"])
            revoke_button.state(["!disabled"] if customer is not None and customer.status != "revoked" else ["disabled"])
            remove_button.state(["!disabled"] if customer is not None else ["disabled"])
            if customer is None:
                cust_detail.set("Select a customer to approve them or remove their access.")
            else:
                parts = [customer.status_label]
                if customer.approved:
                    parts.append(f"ID checked by {customer.verified_by} {friendly_time(customer.verified_at)}")
                parts.append(f"Radio {customer.node_id}" if customer.node_id else "No radio node")
                if customer.contact:
                    parts.append(customer.contact)
                cust_detail.set("  ·  ".join(parts))
        else:
            for button in (approve_button, revoke_button, remove_button):
                button.pack_forget()
            visibility_button.pack(side="left")
            entry = selected_visibility()
            visibility_button.state(["!disabled"] if entry is not None else ["disabled"])
            visibility_button.configure(text="Hide from customers" if entry is None or entry[1] else "Show to customers")
            cust_detail.set("Customers see only the boards marked Visible, in the kiosk and in radio replies. "
                            "Staff always see every board.")

    cust_list.on_select = update_customer_actions

    def refresh_customers(keep=None):
        nonlocal shown_customers, shown_visibility
        for name, tab in cust_tab_buttons.items():
            tab.configure(style="SegmentActive.TButton" if name == cust_view[0] else "Segment.TButton")
        try:
            if cust_view[0] == "customers":
                shown_customers = customer_book.customers()
                cust_list.set_rows([(f"{c.name}  ·  {c.status_label}" + (f"  ·  {c.node_id}" if c.node_id else ""),
                                     ("strong",) if c.status == "pending" else ("placeholder",) if c.status == "revoked" else ())
                                    for c in shown_customers], placeholder="No customers yet — add one on the right")
                index = next((i for i, c in enumerate(shown_customers) if c.id == keep), None)
            else:
                bbs = BulletinBoard(database) if database.exists() else None
                visible = bbs.board_visibility() if bbs else {}
                shown_visibility = [(b, visible.get(b["id"], True)) for b in (bbs.list_boards() if bbs else [])]
                cust_list.set_rows([(f"{'Visible' if shown else 'Staff only'}  ·  {b['name']}", () if shown else ("placeholder",))
                                    for b, shown in shown_visibility], placeholder="No boards yet")
                index = next((i for i, (b, _shown) in enumerate(shown_visibility) if b["id"] == keep), None)
            if index is not None:
                cust_list.select(index)
        except DATA_ERRORS as exc:
            cust_list.set_rows([], placeholder=f"Couldn't read customers: {exc}", tag="error")
        update_customer_actions()

    def switch_customer_view(view):
        cust_view[0] = view
        refresh_customers()

    cust_tab_buttons = {}
    for view, label in (("customers", "Customers"), ("boards", "Visible boards")):
        tab = ttk.Button(cust_tabs, text=label, style="Segment.TButton", command=lambda v=view: switch_customer_view(v))
        tab.pack(side="left", padx=(0, t.px(XS)))
        cust_tab_buttons[view] = tab

    def approve_customer():
        customer = selected_customer()
        if customer is None:
            return
        if not messagebox.askyesno(
                f"Approve {customer.name}?",
                f"Only approve after you have checked a government photo ID in person showing {customer.name} is "
                f"{config.minimum_customer_age} or older.\n\nVapor Board records that you checked it, not the ID itself.",
                icon="warning", default="no", parent=root):
            return
        try:
            done = customer_book.approve(customer.id, session[0], id_checked_21_plus=True)
        except (CustomerError, *DATA_ERRORS) as exc:
            notify("danger", "Customer not approved", str(exc))
            return
        record("customer approved", f"{done.name} (ID checked in person)")
        refresh_customers(keep=done.id)
        notify("success", "Customer approved", f"{done.name} can now read the visible boards.")

    def revoke_customer():
        customer = selected_customer()
        if customer is None:
            return
        try:
            done = customer_book.revoke(customer.id, session[0])
        except (CustomerError, *DATA_ERRORS) as exc:
            notify("danger", "Access not removed", str(exc))
            return
        record("customer access removed", done.name)
        refresh_customers(keep=done.id)
        notify("success", "Access removed", f"{done.name} can no longer read the boards.")

    def remove_customer():
        customer = selected_customer()
        if customer is None:
            return
        if not messagebox.askyesno(f"Delete {customer.name}?",
                                   f"{customer.name}'s customer record is removed from this Mac. This can't be undone.",
                                   icon="warning", default="no", parent=root):
            return
        try:
            customer_book.remove(customer.id, session[0])
        except (CustomerError, *DATA_ERRORS) as exc:
            notify("danger", "Customer not deleted", str(exc))
            return
        record("customer deleted", customer.name)
        refresh_customers()
        notify("success", "Customer deleted")

    def toggle_visibility():
        entry = selected_visibility()
        if entry is None:
            return
        board, shown = entry
        try:
            BulletinBoard(database).set_customer_visible(board["id"], not shown)
        except DATA_ERRORS as exc:
            notify("danger", "Board not changed", str(exc))
            return
        record("board shown to customers" if not shown else "board hidden from customers", board["name"])
        refresh_customers(keep=board["id"])
        notify("success", "Board visible to customers" if not shown else "Board is staff only",
               f"Customers can read {board['name']}." if not shown else f"Customers no longer see {board['name']}.")

    approve_button = ttk.Button(cust_actions, text="Approve…", style="Accent.TButton", command=approve_customer)
    revoke_button = ttk.Button(cust_actions, text="Remove access", command=revoke_customer)
    remove_button = ttk.Button(cust_actions, text="Delete", style="Danger.TButton", command=remove_customer)
    visibility_button = ttk.Button(cust_actions, text="Hide from customers", command=toggle_visibility)

    new_cust_card = theme.Card(cust_body, t, "Add a customer", "Approve them once you've checked their ID.").grid(row=0, column=1, sticky="new")
    new_cust_card.subtitle.configure(wraplength=t.px(230))
    new_cust = {name: tk.StringVar() for name in ("name", "contact", "node")}
    cust_entries = {}
    for label, name in (("NAME", "name"), ("PHONE OR EMAIL (OPTIONAL)", "contact"), ("RADIO NODE ID (OPTIONAL)", "node")):
        ttk.Label(new_cust_card.body, text=label, style="Card.Field.TLabel").pack(anchor="w", pady=(0 if not cust_entries else t.px(SM), t.px(XS)))
        cust_entries[name] = ttk.Entry(new_cust_card.body, name=f"customer_{name}", textvariable=new_cust[name], width=10)
        cust_entries[name].pack(fill="x")
    ttk.Label(new_cust_card.body, text="Like !a1b2c3d4. Needed only for radio replies.", style="Card.Caption.TLabel",
              wraplength=t.px(230), justify="left").pack(anchor="w", pady=(t.px(XS), 0))

    def add_customer(_event=None):
        try:
            made = customer_book.add(new_cust["name"].get(), new_cust["contact"].get(), new_cust["node"].get(), actor=session[0])
        except (CustomerError, *DATA_ERRORS) as exc:
            notify("danger", "Customer not added", str(exc))
            return "break"
        for variable in new_cust.values():
            variable.set("")
        record("customer added", made.name)
        cust_view[0] = "customers"
        refresh_customers(keep=made.id)
        notify("success", "Customer added", f"{made.name} is waiting for approval.")
        return "break"

    ttk.Button(new_cust_card.body, text="Add customer", style="Accent.TButton", command=add_customer).pack(anchor="w", pady=(t.px(MD), 0))
    cust_entries["node"].bind("<Return>", add_customer)
    on_show["Customers"] = refresh_customers

    # ==== Staff ============================================================================
    # Accounts that may sign in on this Mac, plus the activity log. Only admins change accounts.
    new_code_button = ttk.Button(staff_actions, text="New recovery code…")
    new_code_button.pack(side="left")
    staff_body = ttk.Frame(staff_page)
    staff_body.pack(fill="both", expand=True)
    staff_body.columnconfigure(0, weight=3, uniform="staff")
    staff_body.columnconfigure(1, weight=2, uniform="staff")
    staff_body.rowconfigure(0, weight=1)
    team_card = theme.Card(staff_body, t).grid(row=0, column=0, sticky="nsew", padx=(0, t.px(LG)))
    team_tabs = ttk.Frame(team_card.body, style="Card.TFrame")
    team_tabs.pack(fill="x")
    team_view = ["team"]  # team | activity
    team_list = theme.ListView(team_card.body, t, height=6, placeholder="No staff accounts")
    team_list.frame.pack(fill="both", expand=True, pady=(t.px(MD), 0))
    team_actions = ttk.Frame(team_card.body, style="Card.TFrame")
    team_actions.pack(fill="x", pady=(t.px(MD), 0))
    ttk.Label(team_actions, text="NEW PASSWORD FOR THE SELECTED ACCOUNT", style="Card.Field.TLabel").pack(anchor="w", pady=(0, t.px(XS)))
    password_row = ttk.Frame(team_actions, style="Card.TFrame")
    password_row.pack(fill="x")
    new_password = tk.StringVar()
    new_password_entry = ttk.Entry(password_row, name="new_password", textvariable=new_password, show="•", width=10)
    new_password_entry.pack(side="left", fill="x", expand=True)
    team = []

    def selected_account():
        index = team_list.selected()
        return team[index] if team_view[0] == "team" and index is not None and index < len(team) else None

    def update_staff_actions(_index=None):
        account, me = selected_account(), session[0]
        admin = me is not None and me.is_admin
        can_toggle = admin and account is not None and account.username != me.username
        toggle_button.configure(text="Enable" if account is not None and not account.active else "Disable")
        toggle_button.state(["!disabled"] if can_toggle else ["disabled"])
        mine = account is not None and me is not None and (admin or account.username == me.username)
        set_password_button.state(["!disabled"] if mine else ["disabled"])
        new_password_entry.state(["!disabled"] if mine else ["disabled"])

    team_list.on_select = update_staff_actions

    def refresh_staff(keep=None):
        nonlocal team
        for name, tab in team_tab_buttons.items():
            tab.configure(style="SegmentActive.TButton" if name == team_view[0] else "Segment.TButton")
        try:
            if team_view[0] == "team":
                team = staff.accounts()
                me = session[0].username if session[0] else None
                team_list.set_rows([(f"{a.display_name}{' (you)' if a.username == me else ''}  ·  {a.username}  ·  "
                                     f"{a.role_label}{'' if a.active else '  ·  Disabled'}",
                                     () if a.active else ("placeholder",)) for a in team])
                index = next((i for i, a in enumerate(team) if a.username == keep), None)
                if index is not None:
                    team_list.select(index)
                team_actions.pack(fill="x", pady=(t.px(MD), 0))
                toggle_button.pack(side="right")
            else:
                entries = staff.activity(200)
                team_list.set_rows([(f'{friendly_time(e["at"])}  ·  {e["actor"]}  ·  {e["action"]}'
                                     + (f'  ·  {e["detail"]}' if e["detail"] else ""), ()) for e in entries],
                                   placeholder="Nothing recorded yet")
                team_actions.pack_forget()
                toggle_button.pack_forget()
        except DATA_ERRORS as exc:
            team_list.set_rows([], placeholder=f"Couldn't read staff accounts: {exc}", tag="error")
        update_staff_actions()

    def switch_team_view(view):
        team_view[0] = view
        refresh_staff()

    team_tab_buttons = {}
    for view, label in (("team", "Team"), ("activity", "Activity log")):
        tab = ttk.Button(team_tabs, text=label, style="Segment.TButton", command=lambda v=view: switch_team_view(v))
        tab.pack(side="left", padx=(0, t.px(XS)))
        team_tab_buttons[view] = tab

    def toggle_account():
        account = selected_account()
        if account is None:
            return
        try:
            changed = staff.set_active(account.username, not account.active, session[0])
        except (staff_accounts.AccountError, *DATA_ERRORS) as exc:
            notify("danger", "Account not changed", str(exc))
            return
        refresh_staff(keep=changed.username)
        notify("success", "Account enabled" if changed.active else "Account disabled",
               f"{changed.display_name} can sign in again." if changed.active else f"{changed.display_name} can no longer sign in.")

    def set_selected_password(_event=None):
        account = selected_account()
        if account is None:
            return "break"
        try:
            staff.set_password(account.username, new_password.get(), session[0])
        except (staff_accounts.AccountError, *DATA_ERRORS) as exc:
            notify("danger", "Password not changed", str(exc))
            return "break"
        new_password.set("")
        notify("success", "Password changed", f"{account.display_name} signs in with the new password from now on.")
        return "break"

    set_password_button = ttk.Button(password_row, text="Set password", command=set_selected_password)
    set_password_button.pack(side="left", padx=(t.px(SM), 0))
    new_password_entry.bind("<Return>", set_selected_password)
    toggle_button = ttk.Button(team_tabs, text="Disable", command=toggle_account)

    add_card = theme.Card(staff_body, t, "Add a staff member", "They sign in with their own username and password.").grid(row=0, column=1, sticky="new")
    add_card.subtitle.configure(wraplength=t.px(230))
    add_name, add_user, add_pass = tk.StringVar(), tk.StringVar(), tk.StringVar()
    add_entries = {}
    for label, variable, name, secret in (("NAME", add_name, "add_name", False), ("USERNAME", add_user, "add_username", False),
                                          ("PASSWORD", add_pass, "add_password", True)):
        ttk.Label(add_card.body, text=label, style="Card.Field.TLabel").pack(anchor="w", pady=(0 if not add_entries else t.px(SM), t.px(XS)))
        add_entries[name] = ttk.Entry(add_card.body, name=name, textvariable=variable, show="•" if secret else "", width=10)
        add_entries[name].pack(fill="x")
    add_role = [staff_accounts.STAFF]
    role_row = ttk.Frame(add_card.body, style="Card.TFrame")
    role_row.pack(fill="x", pady=(t.px(MD), 0))
    role_buttons = {}

    def choose_role(role):
        add_role[0] = role
        for name, button in role_buttons.items():
            button.configure(style="SegmentActive.TButton" if name == role else "Segment.TButton")

    for role, label in ((staff_accounts.STAFF, "Staff"), (staff_accounts.ADMIN, "Admin")):
        role_buttons[role] = ttk.Button(role_row, text=label, command=lambda r=role: choose_role(r))
        role_buttons[role].pack(side="left", padx=(0, t.px(XS)))
    choose_role(staff_accounts.STAFF)

    def add_staff_member(_event=None):
        try:
            made = staff.create(add_user.get(), add_name.get(), add_pass.get(), add_role[0], actor=session[0])
        except (staff_accounts.AccountError, *DATA_ERRORS) as exc:
            notify("danger", "Staff member not added", str(exc))
            return "break"
        for variable in (add_name, add_user, add_pass):
            variable.set("")
        choose_role(staff_accounts.STAFF)
        team_view[0] = "team"
        refresh_staff(keep=made.username)
        notify("success", "Staff member added", f"{made.display_name} can now sign in as “{made.username}”.")
        return "break"

    add_button = ttk.Button(add_card.body, text="Add staff member", style="Accent.TButton", command=add_staff_member)
    add_button.pack(anchor="w", pady=(t.px(MD), 0))
    add_entries["add_password"].bind("<Return>", add_staff_member)
    add_note = ttk.Label(add_card.body, text="", style="Card.Caption.TLabel", wraplength=t.px(230), justify="left")

    def show_staff():
        admin = session[0] is not None and session[0].is_admin
        for widget in (*add_entries.values(), *role_buttons.values(), add_button, new_code_button):
            widget.state(["!disabled"] if admin else ["disabled"])
        if admin:
            add_note.pack_forget()
        else:
            add_note.configure(text="Only an owner or admin can add staff or disable accounts.")
            add_note.pack(anchor="w", pady=(t.px(SM), 0))
        refresh_staff()

    on_show["Staff"] = show_staff

    # ==== Settings =========================================================================
    # One tab at a time, so every card keeps its room at the smallest window and largest text size.
    settings_tabs = ttk.Frame(settings_page)
    settings_tabs.pack(fill="x", pady=(0, t.px(MD)))
    ttk.Label(settings_page, text="To change a setting, edit shop.json and restart Vapor Board.",
              style="Caption.TLabel", wraplength=t.px(520), justify="left").pack(side="bottom", anchor="w", pady=(t.px(MD), 0))
    settings_body = ttk.Frame(settings_page)
    settings_body.pack(fill="both", expand=True)
    settings_body.columnconfigure(0, weight=1)
    settings_panes, settings_tab_buttons = {}, {}

    def show_settings_tab(name):
        for key, pane in settings_panes.items():
            pane.grid() if key == name else pane.grid_remove()
            settings_tab_buttons[key].configure(style="SegmentActive.TButton" if key == name else "Segment.TButton")

    for key, label in (("shop", "Shop"), ("storage", "Storage"), ("radio", "Radio"), ("customers", "Customer access")):
        settings_panes[key] = ttk.Frame(settings_body)
        settings_panes[key].grid(row=0, column=0, sticky="nsew")
        settings_tab_buttons[key] = ttk.Button(settings_tabs, text=label, style="Segment.TButton", command=lambda k=key: show_settings_tab(k))
        settings_tab_buttons[key].pack(side="left", padx=(0, t.px(XS)))
    show_settings_tab("radio" if config_error else "shop")  # a settings problem is reported on the radio tab

    if config_error:
        problem = theme.Card(settings_panes["radio"], t, "Settings file couldn't be read",
                             f"{config_error}. Vapor Board is using its default settings until shop.json is fixed.").pack(fill="x", pady=(0, t.px(LG)))
        problem.outer.configure(highlightbackground=p.warning)
        problem.subtitle.configure(wraplength=t.px(320))

    def settings_card(parent, title, rows, **pack):
        section = theme.Card(parent, t, title).pack(fill="x", **pack)
        grid = section.body
        grid.columnconfigure(0, weight=1)
        row = 0
        for index, (label, value, note) in enumerate(rows):
            if index:
                ttk.Separator(grid).grid(row=row, column=0, columnspan=2, sticky="ew", pady=t.px(SM))
                row += 1
            ttk.Label(grid, text=label, style="Card.TLabel").grid(row=row, column=0, sticky="w")
            if isinstance(value, tk.StringVar):
                ttk.Label(grid, textvariable=value, style="Card.Strong.TLabel", wraplength=t.px(200), justify="right").grid(row=row, column=1, sticky="e")
            elif isinstance(value, tuple) and value[0] == "swatch":
                tk.Label(grid, text=f"■  {value[1]}", bg=p.card, fg=readable_accent, font=t.fonts["body_bold"]).grid(row=row, column=1, sticky="e")
            elif isinstance(value, tuple):
                kind, text = value
                pill = theme.Pill(grid, t, p.card, kind, text, dot=False)
                pill.label.grid(row=row, column=1, sticky="e")
            else:
                ttk.Label(grid, text=value, style="Card.Strong.TLabel", wraplength=t.px(200), justify="right").grid(row=row, column=1, sticky="e")
            row += 1
            if isinstance(note, tk.StringVar):
                ttk.Label(grid, textvariable=note, style="Card.Caption.TLabel", wraplength=t.px(330), justify="left").grid(
                    row=row, column=0, columnspan=2, sticky="w", pady=(2, 0))
                row += 1
            elif note:
                ttk.Label(grid, text=note, style="Card.Caption.TLabel", wraplength=t.px(330), justify="left").grid(
                    row=row, column=0, columnspan=2, sticky="w", pady=(2, 0))
                row += 1
        return section

    appearance = {"system": f"Match macOS ({theme.resolve_appearance('system').title()})", "light": "Light", "dark": "Dark"}[config.appearance]
    readable_accent = p.accent_text
    settings_card(settings_panes["shop"], "Shop", (
        ("Shop name", config.shop_name, None),
        ("Hours", config.shop_hours or "Not set", None),
        ("Contact", config.shop_contact or "Not set", None),
        ("Operator mailbox", mailbox, "The name this Mac reads and sends private messages as."),
        ("Accent colour", ("swatch", config.accent_color.upper()), None),
        ("Appearance", appearance, None),
        ("Text size", config.text_size.title(), None),
    ))
    backup_folder = database.parent / "backups"
    database_state = tk.StringVar()
    last_backup = tk.StringVar()

    def refresh_storage():
        database_state.set("Found" if database.exists() else "Not created yet")
        latest = next((b for b in backups.list_backups(backup_folder) if not b.label), None)
        when = friendly_time(latest.created.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")) if latest else "none yet"
        last_backup.set(f"{short_path(database)}  ·  Last backup: {when}")
        backup_now.state(["!disabled"] if database.exists() else ["disabled"])

    settings_card(settings_panes["storage"], "Storage", (
        ("Settings file", "Found" if config_path.exists() else "Not created (defaults)", short_path(config_path)),
        ("Database", database_state, last_backup),
        ("Update check", ("success", "On") if config.check_for_updates else ("neutral", "Off"),
         "Asks GitHub for newer releases at launch. Sends no shop data." if config.check_for_updates
         else "Vapor Board doesn't contact the internet. Set check_for_updates in shop.json, or use File ▸ Check for Updates."),
    ))

    def back_up_now():
        try:
            made = backups.create_backup(database, backup_folder, staff_database=staff.path)
        except backups.BackupError as exc:
            notify("danger", "Backup not made", str(exc))
            return
        refresh_storage()
        record("backup made", made.path.name)
        extra = " Staff accounts included." if backups.staff_file(made.path).is_file() else ""
        notify("success", "Backup saved", f"{made.summary} copied to {short_path(made.path)}.{extra}")

    def restore_from_backup():
        chosen = filedialog.askopenfilename(
            parent=root, title="Choose a Vapor Board backup", initialdir=str(backup_folder if backup_folder.is_dir() else database.parent),
            filetypes=[("Vapor Board backup", "*.sqlite"), ("All files", "*")])
        if not chosen:
            return
        try:
            info = backups.inspect(chosen)
        except backups.BackupError as exc:
            notify("danger", "Can't restore that file", str(exc))
            return
        if not messagebox.askyesno(
                "Restore this backup?",
                f"Replace everything on this Mac with the backup from {info.created:%-d %b %Y at %-I:%M %p} ({info.summary})?\n\n"
                "Your current boards and messages are saved as a backup first, so you can undo this.",
                icon="warning", default="no", parent=root):
            return
        saved_staff = backups.staff_in_backup(chosen) if session[0] is not None and session[0].is_admin else None
        restore_staff = saved_staff is not None and messagebox.askyesno(
            "Restore staff accounts too?",
            f"This backup also has {saved_staff.accounts} staff account{'' if saved_staff.accounts == 1 else 's'} and the activity log.\n\n"
            "Restoring them replaces everyone's sign-in and passwords with the ones from the backup, and you'll need to sign in again. "
            "Choose No to keep today's accounts.",
            icon="warning", default="no", parent=root)
        try:
            safety = backups.restore_backup(chosen, database, backup_folder, staff_database=staff.path, restore_staff=restore_staff)
        except backups.BackupError as exc:
            notify("danger", "Restore failed", str(exc))
            return
        cancel_edit()
        refresh_boards()
        refresh_mail()
        refresh_overview()
        refresh_storage()
        record("backup restored", f"{info.path.name} ({info.summary})")
        notify("success", "Backup restored",
               f"{info.summary} restored." + (f" Previous data saved as {safety.path.name}." if safety else ""))
        if restore_staff:
            lock(reason="signed out after restoring staff accounts")

    backup_now = ttk.Button(settings_actions, text="Back up now", command=back_up_now)
    backup_now.pack(side="left")
    ttk.Button(settings_actions, text="Restore…", command=restore_from_backup).pack(side="left", padx=(t.px(SM), 0))
    refresh_storage()
    settings_card(settings_panes["radio"], "Radio & network", (
        ("Radio transmit", ("warning", "On") if transmit else ("neutral", "Off"),
         "Replies only to direct messages from approved customers, with rate limits. Never broadcasts." if transmit
         else "Vapor Board only listens. Set transmissions_enabled in shop.json to reply to approved customers."),
        ("MQTT bridge", ("success", "On") if config.mqtt_enabled else ("neutral", "Off"),
         "No internet bridge. Nothing leaves your local network."),
    ))
    settings_card(settings_panes["customers"], "Customer access", (
        ("Approval before joining", ("success", "Required") if config.customer_access_requires_approval else ("warning", "Not required"), None),
        ("Minimum age", f"{config.minimum_customer_age}+", None),
        ("Staff auto-lock", f"After {plural(config.auto_lock_minutes, 'minute')}" if config.auto_lock_minutes else "Off", None),
        ("New-message alerts", ("success", "On") if config.message_alerts else ("neutral", "Off"), None),
    ))

    def reveal_settings():
        target = config_path if config_path.exists() else config_path.parent
        if not target.exists():
            notify("info", "No settings file yet", f"Vapor Board is using its defaults. Create {config_path} to customise it.")
            return
        try:
            subprocess.run(["open", "-R", str(target)] if target.is_file() else ["open", str(target)], check=False, timeout=5)
        except (OSError, subprocess.SubprocessError) as exc:
            notify("danger", "Couldn't open Finder", str(exc))

    if sys.platform == "darwin":
        ttk.Button(settings_actions, text="Show in Finder", command=reveal_settings).pack(side="left", padx=(t.px(SM), 0))

    # ==== Overview =========================================================================
    # Radio connections are explicit and receive-only.
    radio_page = overview_page
    worker = RadioWorker()
    stats = ttk.Frame(radio_page)
    stats.pack(fill="x", pady=(0, t.px(LG)))
    for column in range(3):
        stats.columnconfigure(column, weight=1, uniform="stats")
    unread_note = tk.StringVar(value="You're all caught up")
    for column, (label, variable, note, link, target) in enumerate((
        ("UNREAD MESSAGES", unread_count, unread_note, "Open Messages  →", "Messages"),
        ("BOARDS", board_count, "Stored on this Mac", "Open Boards  →", "Boards"),
        ("RADIO PACKETS", counters, "Received while connected", None, None),
    )):
        tile = theme.Card(stats, t).grid(row=0, column=column, sticky="nsew", padx=(0, t.px(LG)) if column < 2 else 0)
        ttk.Label(tile.body, text=label, style="Card.Field.TLabel").pack(anchor="w")
        ttk.Label(tile.body, textvariable=variable, style="Card.Stat.TLabel").pack(anchor="w", pady=(t.px(2), 0))
        if isinstance(note, tk.StringVar):
            ttk.Label(tile.body, textvariable=note, style="Card.Muted.TLabel").pack(anchor="w")
        else:
            ttk.Label(tile.body, text=note, style="Card.Muted.TLabel").pack(anchor="w")
        if link:
            ttk.Button(tile.body, text=link, style="Link.TButton", command=lambda name=target: show_page(name)).pack(anchor="w", pady=(t.px(SM), 0))

    lower = ttk.Frame(radio_page)
    lower.pack(fill="both", expand=True)
    lower.columnconfigure(0, weight=1, uniform="overview")
    lower.columnconfigure(1, weight=1, uniform="overview")
    lower.rowconfigure(0, weight=1)
    start_card = theme.Card(lower, t, "Getting started", "A few steps to set up your board.").grid(row=0, column=0, sticky="nsew", padx=(0, t.px(LG)))
    checklist = ttk.Frame(start_card.body, style="Card.TFrame")
    recent = theme.ListView(start_card.body, t, height=5, placeholder="No posts yet")
    recent_posts = []

    def open_recent(index):
        if index < len(recent_posts):
            board_id, post_id = recent_posts[index]
            show_page("Boards")
            refresh_boards(keep=board_id)
            show_posts(keep=post_id)

    recent.on_select = open_recent

    def refresh_overview():
        nonlocal recent_posts
        has_posts[0] = has_posts[0] or bool(shown_posts)
        steps = (
            (bool(selected_boards), "Create a board", "Boards hold notices like opening hours and closures.", "Go to Boards", lambda: (show_page("Boards"), board_entry.focus_set())),
            (has_posts[0], "Write your first post", "Posts appear on a board for staff to read.", "Write a post", new_post),
            (has_mail[0], "Send a private message", f"Messages are kept on this Mac for {mailbox}.", "Open Messages", new_message),
            (display_state[0].tcp == ConnectionState.CONNECTED, "Connect a radio (optional)", "Answers approved customers' direct messages." if transmit else "Listen in on your mesh. Nothing is transmitted.", None, None),
        )
        if selected_boards and has_posts[0]:
            checklist.pack_forget()
            start_card.title_var.set("Recent posts")
            start_card.subtitle_var.set("The latest notices across your boards. Select one to open it.")
            items = []
            try:
                for board in selected_boards[:20]:
                    items += [(board, entry) for entry in BoardBrowser(database).posts(board["id"])]  # pinned-first, so take all
            except DATA_ERRORS as exc:
                recent.set_rows([], placeholder=f"Couldn't read posts: {exc}", tag="error")
                recent.frame.pack(fill="both", expand=True)
                return
            items.sort(key=lambda pair: pair[1]["id"], reverse=True)
            items = items[:5]
            recent_posts = [(board["id"], entry["id"]) for board, entry in items]
            recent.set_rows([(f'{board["name"]}  ·  {entry["author"]} — {first_line(entry["body"], 24)}', ()) for board, entry in items])
            recent.frame.pack(fill="both", expand=True)
            return
        recent.frame.pack_forget()
        start_card.title_var.set("Getting started")
        start_card.subtitle_var.set("A few steps to set up your board.")
        for child in checklist.winfo_children():
            child.destroy()
        next_step = next((step for step in steps if not step[0]), None)  # only this one gets its detail and link, so all four fit the smallest window
        for step in steps:
            done, title, detail, action, command = step
            row = ttk.Frame(checklist, style="Card.TFrame")
            row.pack(fill="x", pady=(0, t.px(6)))
            tk.Label(row, text="✓" if done else "○", bg=p.card, fg=p.success if done else p.subtle,
                     font=t.fonts["body_bold"], width=2).pack(side="left", anchor="n")
            words = ttk.Frame(row, style="Card.TFrame")
            words.pack(side="left", fill="x", expand=True)
            ttk.Label(words, text=title, style="Card.Muted.TLabel" if done else "Card.Strong.TLabel").pack(anchor="w")
            if step is not next_step:
                continue
            ttk.Label(words, text=detail, style="Card.Caption.TLabel", wraplength=t.px(270), justify="left").pack(anchor="w")
            if action:
                ttk.Button(words, text=f"{action}  →", style="Link.TButton", command=command).pack(anchor="w")
        checklist.pack(fill="both", expand=True)

    on_show["Overview"] = refresh_overview

    radio_card = theme.Card(lower, t, "Meshtastic radio", "Wi-Fi or USB · replies on" if transmit else "Listen-only connection over Wi-Fi or USB.").grid(row=0, column=1, sticky="nsew")
    radio_pill = theme.Pill(radio_card.actions, t, p.card, "neutral", "Not connected")
    radio_pill.label.pack()
    fields = ttk.Frame(radio_card.body, style="Card.TFrame")
    fields.pack(fill="x")
    fields.columnconfigure(0, weight=1)
    host_var = tk.StringVar(value="127.0.0.1")
    port_var = tk.StringVar(value="4403")
    host_box = ttk.Frame(fields, style="Card.TFrame")
    host_box.grid(row=0, column=0, sticky="ew")
    port_box = ttk.Frame(fields, style="Card.TFrame")
    port_box.grid(row=0, column=1, sticky="ew", padx=(t.px(MD), 0))
    host_entry, _note = theme.field(host_box, t, "RADIO ADDRESS", host_var)
    port_entry, _note = theme.field(port_box, t, "PORT", port_var, width=6)
    ttk.Label(radio_card.body, text="IP address or USB device. The port is usually 4403.",
              style="Card.Caption.TLabel", wraplength=t.px(330), justify="left").pack(anchor="w", pady=(t.px(6), 0))

    def find_usb_radio():
        found = serial_link.list_ports()
        if not found:
            notify("warning", "No USB radio found", "Plug the radio in with a data cable and try again.")
            return
        host_var.set(found[0])
        notify("info", "USB radio found", found[0] if len(found) == 1 else f"{found[0]}, one of {len(found)} USB devices. Type another if this isn't the radio.")

    ttk.Button(radio_card.body, text="Find USB radio", style="Link.TButton", command=find_usb_radio).pack(anchor="w")
    settings_error = ttk.Label(radio_card.body, text="", style="Card.Danger.TLabel", wraplength=t.px(330), justify="left")
    radio_status = tk.StringVar(value=radio_presentation(RadioDisplayState())[2])
    ttk.Label(radio_card.body, textvariable=radio_status, style="Card.TLabel", wraplength=t.px(330), justify="left").pack(anchor="w", pady=(t.px(MD), 0))
    display_state = [RadioDisplayState()]
    pulse_job = [None]

    def connect_radio(_event=None):
        if demo:
            notify("info", "The radio is off in demo mode", "Quit and open Vapor Board normally to connect a radio.")
            return
        try:
            address = host_var.get().strip()
            settings = (serial_link.SerialSettings(path=address, transmissions_enabled=transmit) if address.startswith("/dev/")
                        else TcpSettings(host=address, port=int(port_var.get()), timeout=3.0, transmissions_enabled=transmit))
        except (ValueError, TypeError) as exc:
            bad = port_entry if "port" in str(exc).lower() or not port_var.get().strip().isdigit() else host_entry
            bad.state(["invalid"])
            settings_error.configure(text=f"Check the connection settings: {exc}")
            settings_error.pack(anchor="w", pady=(t.px(6), 0), before=controls)
            bad.focus_set()
            return
        for entry in (host_entry, port_entry):
            entry.state(["!invalid"])
        settings_error.pack_forget()
        if worker.start(settings):
            display_state[0] = reduce_event(display_state[0], ('connecting', None))
            update_footer()

    def disconnect_radio():
        worker.stop()
        display_state[0] = reduce_event(display_state[0], ('disconnected', None))
        update_footer()
        notify("info", "Radio disconnected")

    controls = ttk.Frame(radio_card.body, style="Card.TFrame")
    controls.pack(anchor="w", pady=(t.px(MD), 0))
    connect_button = ttk.Button(controls, text="Connect", style="Accent.TButton", command=connect_radio)
    connect_button.pack(side="left", padx=(0, t.px(SM)))
    disconnect_button = ttk.Button(controls, text="Disconnect", command=disconnect_radio)
    disconnect_button.pack(side="left")
    detail_shown = [False]
    technical = ttk.Label(radio_card.body, text="", style="Card.Caption.TLabel", wraplength=t.px(330), justify="left")

    def toggle_details():
        detail_shown[0] = not detail_shown[0]
        details_button.configure(text="Hide details" if detail_shown[0] else "Show details")
        if detail_shown[0]:
            technical.pack(anchor="w", pady=(t.px(XS), 0))
        else:
            technical.pack_forget()

    details_button = ttk.Button(controls, text="Show details", style="Ghost.TButton", command=toggle_details)
    details_button.pack(side="left", padx=(t.px(SM), 0))
    for entry in (host_entry, port_entry):
        entry.bind("<Return>", connect_radio)

    def pulse(bright=False):
        """Gently blink the pill while connecting; skipped when macOS Reduce Motion is on."""
        pulse_job[0] = None
        if display_state[0].tcp != ConnectionState.CONNECTING:
            return
        for pill in (radio_pill, sidebar_pill):
            pill.set("warning", "Connecting…", dim=not bright)
        pulse_job[0] = root.after(650, pulse, not bright)

    def update_footer():
        snapshot = StatusSnapshot(tcp_state=display_state[0].tcp, protocol_verified=display_state[0].protocol_verified)
        footer.configure(text=snapshot.footer)
        kind, label, explanation = radio_presentation(display_state[0])
        radio_pill.set(kind, label)
        sidebar_pill.set(kind, label)
        radio_status.set(explanation)
        technical.configure(text=f"Technical detail: {display_state[0].detail} · {snapshot.radio_label}")
        busy = display_state[0].tcp in (ConnectionState.CONNECTING, ConnectionState.CONNECTED)
        connect_button.state(["disabled"] if busy or demo else ["!disabled"])
        if demo:
            radio_status.set("Demo mode: radio connections are switched off.")
        disconnect_button.state(["!disabled"] if busy else ["disabled"])
        for entry in (host_entry, port_entry):
            entry.state(["disabled"] if busy or demo else ["!disabled"])
        if display_state[0].tcp == ConnectionState.CONNECTING and not t.reduce_motion and pulse_job[0] is None:
            pulse_job[0] = root.after(650, pulse, False)

    replies = RadioReplies(database, config.shop_name, mailbox, hours=config.shop_hours, contact=config.shop_contact)
    alert_gate = alerts.AlertGate()

    def alert_new_message(customer):
        """Tell staff a customer wrote in. The name stays off the kiosk and out of the Mac banner."""
        if not config.message_alerts:
            return
        if session[0] is not None:
            notify("info", "New customer message", f"From {customer}. Open Messages to reply.")
        if alert_gate.ready():
            root.bell()
            alerts.show_banner(config.shop_name, "New customer message")

    def answer_radio(message):
        """Route a decoded packet: learn our node number, and answer approved customers when transmit is on."""
        if message.get("variant") == "my_info" or transmit:
            try:
                outcome = replies.handle(message)
            except DATA_ERRORS as exc:
                notify("danger", "Radio message not handled", str(exc))
                return
            sent = sum(1 for text in outcome.replies if worker.send_text(message["from"], text, message.get("channel", 0)))
            if outcome.note:
                detail = outcome.note + (f" ({sent} of {len(outcome.replies)} replies sent)" if outcome.replies else "")
                try:
                    staff.log("radio", "radio message", detail)
                except DATA_ERRORS:
                    pass
            if outcome.replies and "message to the shop" in outcome.note:
                refresh_mail()
                alert_new_message(outcome.customer)

    def poll_radio():
        if not root.winfo_exists():
            return
        for _ in range(100):
            event = worker.poll()
            if event is None:
                break
            kind, data = event
            if kind == "protobuf" and isinstance(data, dict):
                answer_radio(data)
            before = display_state[0].tcp
            display_state[0] = reduce_event(display_state[0], event)
            counters.set(str(display_state[0].decoded))
            update_footer()
            if display_state[0].tcp == ConnectionState.ERROR and before != ConnectionState.ERROR:
                notify("danger", "Radio connection problem", display_state[0].detail)
        root.after(100, poll_radio)

    def on_close():
        worker.stop()
        root.destroy()

    # ==== Search ===========================================================================
    # Not in the sidebar list: reached from the search box. Only the operator's own messages are searched.
    search_page = ttk.Frame(page_host, padding=(t.px(28), t.px(24), t.px(28), t.px(LG)))
    search_page.page_name = "Search"
    search_page.grid(row=0, column=0, sticky="nsew")
    pages["Search"] = search_page
    search_header = ttk.Frame(search_page)
    search_header.pack(fill="x", pady=(0, t.px(18)))
    ttk.Label(search_header, text="Search", style="Title.TLabel").pack(anchor="w")
    search_summary = tk.StringVar(value="Type in the search box and press Return.")
    ttk.Label(search_header, textvariable=search_summary, style="Muted.TLabel", wraplength=t.px(520), justify="left").pack(anchor="w", pady=(2, 0))
    search_body = ttk.Frame(search_page)
    search_body.pack(fill="both", expand=True)
    search_body.columnconfigure(1, weight=1)
    search_body.rowconfigure(0, weight=1)
    results_column = ttk.Frame(search_body, width=t.px(320))
    results_column.grid(row=0, column=0, sticky="ns", padx=(0, t.px(LG)))
    results_column.pack_propagate(False)
    results_card = theme.Card(results_column, t, "Results").pack(fill="both", expand=True)
    result_list = theme.ListView(results_card.body, t, height=8, placeholder="No search yet")
    result_list.frame.pack(fill="both", expand=True)
    preview_card = theme.Card(search_body, t, "Nothing selected", "Pick a result to preview it.").grid(row=0, column=1, sticky="nsew")
    _holder, preview = theme.text_area(preview_card.body, t, height=5, readonly=True)
    _holder.pack(fill="both", expand=True)
    preview.tag_configure("match", background=p.selection)
    found = []

    def describe(result):
        if result["kind"] == "post":
            return f'▤  {result["board_name"]}  ·  {result["author"]} — {first_line(result["body"], 26)}'
        outgoing = result["sender"] == mailbox
        return f'✉  {"To " + result["recipient"] if outgoing else result["sender"]} — {first_line(result["body"], 26)}'

    def show_preview(index=None):
        preview.configure(state="normal")
        preview.delete("1.0", "end")
        if index is None or index >= len(found):
            preview_card.title_var.set("Nothing selected")
            preview_card.subtitle_var.set("Pick a result to preview it.")
            preview.insert("1.0", "Results show posts on every board and your own messages.", "placeholder")
            open_button.state(["disabled"])
        else:
            result = found[index]
            if result["kind"] == "post":
                preview_card.title_var.set(f'Post in {result["board_name"]}')
                preview_card.subtitle_var.set(f'By {result["author"]}  ·  {friendly_time(result["created_at"])}')
            else:
                outgoing = result["sender"] == mailbox
                preview_card.title_var.set(f'Message {"to " + result["recipient"] if outgoing else "from " + result["sender"]}')
                preview_card.subtitle_var.set(("Sent " if outgoing else "Received ") + friendly_time(result["created_at"]))
            preview.insert("1.0", result["body"])
            term = search_text.get().strip()
            if term:
                start = "1.0"
                while True:
                    start = preview.search(term, start, stopindex="end", nocase=True)
                    if not start:
                        break
                    end = f"{start}+{len(term)}c"
                    preview.tag_add("match", start, end)
                    start = end
            open_button.state(["!disabled"])
        preview.configure(state="disabled")

    def run_search(_event=None):
        nonlocal found
        term = search_text.get().strip()
        if not term:
            search_entry.focus_set()
            return "break"
        error = None
        if not database.exists():
            found = []
        else:
            try:
                found = BulletinBoard(database).search(mailbox, term)
            except DATA_ERRORS as exc:
                found, error = [], f"Couldn't search: {exc}"
        result_list.set_rows([(describe(result), ()) for result in found],
                             placeholder=error or "No matches", tag="error" if error else "placeholder")
        posts_found = sum(1 for result in found if result["kind"] == "post")
        search_summary.set(f"{plural(len(found), 'result')} for “{term}”" +
                           (f"  ·  {plural(posts_found, 'post')}, {plural(len(found) - posts_found, 'message')}" if found else ""))
        results_card.title_var.set("Results" if found else "No matches")
        show_page("Search")
        show_preview()
        return "break"

    def open_result(_event=None):
        index = result_list.selected()
        if index is None or index >= len(found):
            return "break"
        result = found[index]
        if result["kind"] == "post":
            show_page("Boards")
            refresh_boards(keep=result["board_id"])
            show_posts(keep=result["id"])
        else:
            other = result["recipient"] if result["sender"] == mailbox else result["sender"]
            show_page("Messages")
            switch_mail_view("threads")
            row = next((i for i, entry in enumerate(shown_mail) if entry["other"] == other), None)
            if row is not None:
                mail_list.select(row)
                open_thread(row)
        return "break"

    open_button = ttk.Button(preview_card.actions, text="Open", style="Accent.TButton", command=open_result)
    open_button.pack()
    result_list.on_select = show_preview
    result_list.tree.bind("<Return>", open_result)
    result_list.tree.bind("<Double-1>", open_result)
    search_entry.bind("<Return>", run_search)
    search_entry.submit = run_search  # what Return does; tests call it since synthetic keys need window focus
    search_entry.bind("<Escape>", lambda _e: (search_text.set(""), "break")[1])
    search_entry.bind("<Down>", lambda _e: (result_list.tree.focus_set(), "break")[1] if found and current[0] == "Search" else None)

    def focus_search(_event=None):
        search_entry.focus_set()
        search_entry.select_range(0, "end")
        return "break"

    show_preview()

    # ==== Sign-in ==========================================================================
    # Covers the whole window until a staff member signs in. The first launch creates the owner account.
    gate = ttk.Frame(root, name="gate")
    gate_card = theme.Card(gate, t, padding=XL)
    gate_card.outer.place(relx=0.5, rely=0.5, anchor="center", width=t.px(400))
    gate_vars = {name: tk.StringVar() for name in ("name", "username", "password", "confirm", "code")}
    gate_error = [None]
    last_activity = [time.monotonic()]
    lock_job = [None]

    def gate_field(label, name, secret=False):
        ttk.Label(gate_card.body, text=label, style="Card.Field.TLabel").pack(anchor="w", pady=(t.px(MD), t.px(XS)))
        entry = ttk.Entry(gate_card.body, name=f"gate_{name}", textvariable=gate_vars[name], show="•" if secret else "")
        entry.pack(fill="x")
        return entry

    def gate_problem(message):
        gate_error[0].configure(text=message)
        gate_error[0].pack(anchor="w", pady=(t.px(MD), 0), before=gate_submit[0].master)

    gate_submit = [None]

    def open_gate(recovering=False):
        """Show the owner set-up form on first launch, otherwise the sign-in or password-recovery form."""
        try:
            first = not recovering and not staff.exists()
        except DATA_ERRORS as exc:
            first = False
            notify("danger", "Staff accounts couldn't be read", str(exc))
        for child in gate_card.body.winfo_children():
            child.destroy()
        for variable in gate_vars.values():
            variable.set("")
        tk.Label(gate_card.body, text=config.shop_name.strip()[:1].upper(), bg=p.accent_fill, fg=p.on_accent,
                 font=t.fonts["monogram"], width=2, pady=t.px(4)).pack(anchor="w")
        ttk.Label(gate_card.body, text="Set up Vapor Board" if first else "Reset an owner password" if recovering else f"Sign in to {config.shop_name}",
                  style="Card.Headline.TLabel").pack(anchor="w", pady=(t.px(MD), 0))
        ttk.Label(gate_card.body, style="Card.Muted.TLabel", wraplength=t.px(330), justify="left",
                  text="Create the owner account. You can add staff afterwards on the Staff page." if first
                  else "Enter an owner or admin username and the recovery code you saved." if recovering
                  else "Use your staff username and password.").pack(anchor="w", pady=(t.px(2), 0))
        if first:
            first_entry = gate_field("YOUR NAME", "name")
            gate_field("USERNAME", "username")
            gate_field("PASSWORD", "password", secret=True)
            last = gate_field("CONFIRM PASSWORD", "confirm", secret=True)
        elif recovering:
            first_entry = gate_field("USERNAME", "username")
            gate_field("RECOVERY CODE", "code")
            gate_field("NEW PASSWORD", "password", secret=True)
            last = gate_field("CONFIRM NEW PASSWORD", "confirm", secret=True)
        else:
            first_entry = gate_field("USERNAME", "username")
            last = gate_field("PASSWORD", "password", secret=True)
        gate_error[0] = ttk.Label(gate_card.body, text="", style="Card.Danger.TLabel", wraplength=t.px(330), justify="left")
        gate_row = ttk.Frame(gate_card.body, style="Card.TFrame")
        gate_row.pack(fill="x", pady=(t.px(LG), 0))
        gate_submit[0] = ttk.Button(gate_row, text="Create owner account" if first else "Reset and sign in" if recovering else "Sign in",
                                    style="Accent.TButton", command=create_owner if first else recover_account if recovering else sign_in)
        gate_submit[0].pack(side="right")
        if recovering:
            ttk.Button(gate_row, text="Back", style="Ghost.TButton", command=open_gate).pack(side="left")
        elif not first:
            ttk.Button(gate_row, text="Forgot password?", style="Ghost.TButton",
                       command=lambda: open_gate(recovering=True)).pack(side="left")
        if kiosk_on[0] and not recovering:
            ttk.Button(gate_card.body, text="Back to kiosk", style="Ghost.TButton",
                       command=lambda: back_to_kiosk()).pack(anchor="e", pady=(t.px(SM), 0))
        last.bind("<Return>", lambda _e: (gate_submit[0].invoke(), "break")[1])
        gate.place(x=0, y=0, relwidth=1, relheight=1)
        gate.lift()
        first_entry.focus_set()

    # ---- recovery code: shown once, and stored only after the owner says it has been saved ----
    recovery_screen = ttk.Frame(root, name="recovery")
    recovery_card = theme.Card(recovery_screen, t, padding=XL)
    recovery_card.outer.place(relx=0.5, rely=0.5, anchor="center", width=t.px(420))
    recovery_code = tk.StringVar()

    def hide_recovery_code():
        recovery_code.set("")
        recovery_screen.place_forget()

    def save_recovery_code():
        try:
            staff.save_recovery_code(recovery_code.get(), session[0])
        except (staff_accounts.AccountError, *DATA_ERRORS) as exc:
            notify("danger", "Recovery code not saved", str(exc))
            return
        hide_recovery_code()
        notify("success", "Recovery code saved", "Keep it somewhere safe, away from this Mac.")

    def show_recovery_code(replacing=False):
        for child in recovery_card.body.winfo_children():
            child.destroy()
        recovery_code.set(staff.new_recovery_code())
        ttk.Label(recovery_card.body, text="Save your recovery code", style="Card.Headline.TLabel").pack(anchor="w")
        ttk.Label(recovery_card.body, style="Card.Muted.TLabel", wraplength=t.px(350), justify="left",
                  text="If an owner password is ever forgotten, this code resets it. It's shown only now and works once. "
                  "Write it down and keep it away from this Mac."
                  + (" Your old code stops working when you save this one." if replacing else "")).pack(anchor="w", pady=(t.px(2), t.px(MD)))
        ttk.Entry(recovery_card.body, name="recovery_code", textvariable=recovery_code, state="readonly", justify="center").pack(fill="x")
        row = ttk.Frame(recovery_card.body, style="Card.TFrame")
        row.pack(fill="x", pady=(t.px(LG), 0))
        ttk.Button(row, text="I've saved it", style="Accent.TButton", command=save_recovery_code).pack(side="right")
        if replacing:
            ttk.Button(row, text="Keep current code", style="Ghost.TButton", command=hide_recovery_code).pack(side="left")
        recovery_screen.place(x=0, y=0, relwidth=1, relheight=1)
        recovery_screen.lift()

    new_code_button.configure(command=lambda: show_recovery_code(replacing=True))

    def enter(account):
        hide_recovery_code()
        session[0] = account
        signed_in_name.set(f"{account.display_name}  ·  {account.role_label}")
        if editing[0] is None:
            author_name.set(account.display_name)
        new_author[0] = account.display_name
        gate.place_forget()
        if kiosk_on[0]:
            record("kiosk stopped")
            stop_kiosk()
        last_activity[0] = time.monotonic()
        schedule_lock()
        show_page(current[0])
        try:
            needs_code = account.is_admin and not demo and not staff.has_recovery_code()
        except DATA_ERRORS:
            needs_code = False
        if needs_code:
            show_recovery_code()

    def create_owner():
        if gate_vars["password"].get() != gate_vars["confirm"].get():
            gate_problem("The passwords don't match.")
            return
        try:
            account = staff.create(gate_vars["username"].get(), gate_vars["name"].get(), gate_vars["password"].get())
        except (staff_accounts.AccountError, *DATA_ERRORS) as exc:
            gate_problem(f"{exc}.")
            return
        staff.log(account.username, "signed in")
        enter(account)
        notify("success", "Owner account created", "Add your staff on the Staff page.")

    def sign_in():
        try:
            account = staff.authenticate(gate_vars["username"].get(), gate_vars["password"].get())
        except (staff_accounts.AccountError, *DATA_ERRORS) as exc:
            gate_problem(f"{exc}.")
            return
        if account is None:
            gate_vars["password"].set("")
            gate_problem("That username and password don't match an active account.")
            return
        enter(account)

    def recover_account():
        if gate_vars["password"].get() != gate_vars["confirm"].get():
            gate_problem("The passwords don't match.")
            return
        try:
            account = staff.recover(gate_vars["username"].get(), gate_vars["code"].get(), gate_vars["password"].get())
        except (staff_accounts.AccountError, *DATA_ERRORS) as exc:
            gate_problem(f"{exc}.")
            return
        if account is None:
            gate_problem("That username and recovery code don't match an active owner or admin.")
            return
        enter(account)  # the old code is used up, so this shows a new one
        notify("success", "Password reset", "You're signed in with your new password.")

    def lock(_event=None, reason="signed out"):
        if session[0] is None:
            return "break"
        hide_recovery_code()
        record(reason)
        session[0] = None
        signed_in_name.set("")
        if lock_job[0] is not None:
            root.after_cancel(lock_job[0])
            lock_job[0] = None
        open_gate()
        return "break"

    lock_button.configure(command=lock)

    def schedule_lock():
        """Lock after config.auto_lock_minutes without a key press or click (0 turns it off)."""
        if lock_job[0] is not None:
            root.after_cancel(lock_job[0])
            lock_job[0] = None
        if not config.auto_lock_minutes or session[0] is None:
            return
        idle = time.monotonic() - last_activity[0]
        if idle >= config.auto_lock_minutes * 60:
            lock(reason="locked after inactivity")
            return
        lock_job[0] = root.after(int(min(30, config.auto_lock_minutes * 60 - idle) * 1000) + 50, schedule_lock)

    def touched(_event=None):
        last_activity[0] = time.monotonic()

    root.bind_all("<KeyPress>", touched, add="+")
    root.bind_all("<ButtonPress>", touched, add="+")

    # ==== Kiosk ============================================================================
    # A read-only, customer-facing notice screen for a Mac on the shop counter. Starting it
    # signs staff out; leaving it needs a staff sign-in. Only boards marked visible are shown.
    kiosk = ttk.Frame(root, name="kiosk", padding=(t.px(36), t.px(28)))
    kiosk_on = [False]
    kiosk_boards, kiosk_job = [], [None]
    kiosk_head = tk.Frame(kiosk, bg=p.accent_fill, padx=t.px(LG), pady=t.px(MD))
    kiosk_head.pack(fill="x", pady=(0, t.px(LG)))

    def load_kiosk_logo():
        """The shop's logo scaled to fit the header, or None (no logo set, or the file can't be read)."""
        if not config.kiosk_logo.strip():
            return None
        path = Path(config.kiosk_logo.strip()).expanduser()
        try:
            image = tk.PhotoImage(master=root, file=str(path if path.is_absolute() else database.parent / path))
        except tk.TclError:
            return None
        most = t.px(72)
        factor = max(1, -(-image.height() // most), -(-image.width() // (most * 4)))
        return image.subsample(factor) if factor > 1 else image

    kiosk_logo = load_kiosk_logo()  # also keeps the image alive; Tk doesn't hold a reference
    if kiosk_logo is not None:
        tk.Label(kiosk_head, name="kiosk_logo", image=kiosk_logo, bg=p.accent_fill, borderwidth=0).pack(side="left", anchor="center")
    else:
        tk.Label(kiosk_head, text=config.shop_name.strip()[:1].upper(), bg=p.on_accent, fg=p.accent_fill,
                 font=t.fonts["monogram"], width=2, pady=t.px(4)).pack(side="left", anchor="center")
    kiosk_names = tk.Frame(kiosk_head, bg=p.accent_fill)
    kiosk_names.pack(side="left", fill="x", expand=True, padx=(t.px(MD), 0))
    tk.Label(kiosk_names, text=config.shop_name, bg=p.accent_fill, fg=p.on_accent, font=t.fonts["title"]).pack(anchor="w")
    tk.Label(kiosk_names, text=config.kiosk_tagline.strip() or "Shop notices  ·  Touch a board to read it", bg=p.accent_fill, fg=p.on_accent,
             font=t.fonts["body"], wraplength=t.px(620), justify="left").pack(anchor="w")
    kiosk_staff = ttk.Button(kiosk_head, text="Staff sign-in", command=lambda: open_gate())
    kiosk_staff.pack(side="right", anchor="n")
    kiosk_details = "   ·   ".join(part.strip() for part in (config.shop_hours, config.shop_contact) if part.strip())
    if kiosk_details:
        ttk.Label(kiosk, name="kiosk_info", text=kiosk_details, style="Muted.TLabel", wraplength=t.px(760), justify="center").pack(side="bottom", pady=(t.px(MD), 0))
    kiosk_body = ttk.Frame(kiosk)
    kiosk_body.pack(fill="both", expand=True)
    kiosk_body.columnconfigure(1, weight=1)
    kiosk_body.rowconfigure(0, weight=1)
    kiosk_list_card = theme.Card(kiosk_body, t, "Boards").grid(row=0, column=0, sticky="nsw", padx=(0, t.px(LG)))
    kiosk_list = theme.ListView(kiosk_list_card.body, t, height=8, placeholder="No notices right now")
    kiosk_list.frame.pack(fill="both", expand=True)
    kiosk_list.tree.column("#0", width=t.px(200))
    kiosk_read_card = theme.Card(kiosk_body, t, "").grid(row=0, column=1, sticky="nsew")
    _holder, kiosk_text = theme.text_area(kiosk_read_card.body, t, height=6, readonly=True)
    _holder.pack(fill="both", expand=True)
    reading_font = (t.fonts["body"][0], round(t.fonts["headline"][1] * {"standard": 1.0, "large": 1.3, "larger": 1.6}[config.kiosk_text_size]))
    kiosk_text.configure(font=reading_font, padx=t.px(LG), pady=t.px(LG))
    kiosk_text.tag_configure("meta", foreground=p.muted, font=t.fonts["small"])
    kiosk_text.tag_configure("pinned", foreground=p.accent_text, font=t.fonts["body_bold"])

    def kiosk_show(index):
        if not 0 <= index < len(kiosk_boards):
            return
        board = kiosk_boards[index]
        kiosk_read_card.title_var.set(board["name"])
        kiosk_text.configure(state="normal")
        kiosk_text.delete("1.0", "end")
        try:
            entries = BulletinBoard(database).customer_posts(board["id"])
        except DATA_ERRORS as exc:
            entries = []
            kiosk_text.insert("end", f"This board can't be shown right now ({exc}).", "placeholder")
        for number, entry in enumerate(entries):
            if number:
                kiosk_text.insert("end", "\n\n")
            if entry.get("pinned_at"):
                kiosk_text.insert("end", "◆  Pinned\n", "pinned")
            kiosk_text.insert("end", entry["body"])
            kiosk_text.insert("end", f'\nPosted {friendly_time(entry["created_at"])}', "meta")
        if not entries and not kiosk_text.get("1.0", "end-1c"):
            kiosk_text.insert("end", "Nothing posted here yet.", "placeholder")
        kiosk_text.configure(state="disabled")
        kiosk_text.yview_moveto(0)

    def kiosk_pick(index):
        last_activity[0] = time.monotonic()
        kiosk_show(index)

    kiosk_list.on_select = kiosk_pick

    def kiosk_rotate():
        """Move to the next board after kiosk_rotate_seconds with nobody touching the screen."""
        kiosk_job[0] = None
        if not kiosk_on[0] or not config.kiosk_rotate_seconds:
            return
        if len(kiosk_boards) > 1 and session[0] is None and time.monotonic() - last_activity[0] >= config.kiosk_rotate_seconds:
            index = ((kiosk_list.selected() or 0) + 1) % len(kiosk_boards)
            kiosk_list.select(index)
            kiosk_show(index)
        kiosk_job[0] = root.after(config.kiosk_rotate_seconds * 1000, kiosk_rotate)

    def start_kiosk():
        nonlocal kiosk_boards
        try:
            kiosk_boards = BulletinBoard(database).customer_boards() if database.exists() else []
        except DATA_ERRORS as exc:
            notify("danger", "Kiosk not started", str(exc))
            return
        if not kiosk_boards:
            notify("warning", "Nothing for customers to read",
                   "Add a board, or mark one Visible on the Customers page, before starting the kiosk.")
            return
        record("kiosk started")
        session[0] = None  # leaving the kiosk needs a staff sign-in
        signed_in_name.set("")
        if lock_job[0] is not None:
            root.after_cancel(lock_job[0])
            lock_job[0] = None
        toast.hide()
        kiosk_on[0] = True
        kiosk_list.set_rows([(b["name"], ()) for b in kiosk_boards])
        kiosk_list.select(0)
        kiosk_show(0)
        kiosk.place(x=0, y=0, relwidth=1, relheight=1)
        kiosk.lift()
        if config.kiosk_fullscreen:
            try:
                root.attributes("-fullscreen", True)
            except tk.TclError:
                pass
        last_activity[0] = time.monotonic()
        if config.kiosk_rotate_seconds:
            kiosk_job[0] = root.after(config.kiosk_rotate_seconds * 1000, kiosk_rotate)

    def stop_kiosk():
        if not kiosk_on[0]:
            return
        kiosk_on[0] = False
        if kiosk_job[0] is not None:
            root.after_cancel(kiosk_job[0])
            kiosk_job[0] = None
        kiosk.place_forget()
        if config.kiosk_fullscreen:
            try:
                root.attributes("-fullscreen", False)
            except tk.TclError:
                pass

    def back_to_kiosk():
        gate.place_forget()
        last_activity[0] = time.monotonic()

    ttk.Button(overview_actions, text="Start kiosk", command=start_kiosk).pack(side="left")

    def signed_in(handler):
        """Keyboard shortcuts do nothing while the sign-in screen is up."""
        return lambda event: handler(event) if session[0] is not None else "break"

    # ---- status bar, keyboard, start-up ---------------------------------------------------
    root.protocol("WM_DELETE_WINDOW", on_close)
    status_bar = tk.Frame(main_area, bg=p.background)
    status_bar.pack(side="bottom", fill="x")
    tk.Frame(main_area, bg=p.border, height=1).pack(side="bottom", fill="x")
    footer = tk.Label(status_bar, text=StatusSnapshot().footer, bg=p.background, fg=p.muted,
                      font=t.fonts["caption"], padx=t.px(28), pady=t.px(7), anchor="w")
    footer.pack(side="left")
    tk.Label(status_bar, text=f"{key}1–6 switch pages  ·  {key}N new  ·  {key}R refresh  ·  {key}L lock", bg=p.background, fg=p.subtle,
             font=t.fonts["caption"], padx=t.px(28)).pack(side="right")
    page_host.pack(fill="both", expand=True)

    order = [name for _section, entries in NAVIGATION for name, _glyph in entries]
    for number, name in enumerate(order, start=1):
        root.bind_all(f"<{mod}-Key-{number}>", signed_in(lambda _e, name=name: show_page(name)))
    root.bind_all(f"<{mod}-n>", signed_in(lambda _e: new_message() if current[0] == "Messages" else new_post()))
    root.bind_all(f"<{mod}-r>", signed_in(lambda _e: {"Boards": refresh_boards, "Messages": refresh_mail, "Search": run_search,
                                                       "Staff": refresh_staff}.get(current[0], refresh_overview)()))
    root.bind_all(f"<{mod}-f>", signed_in(focus_search))
    root.bind_all(f"<{mod}-l>", lock)
    root.bind_all("<Escape>", lambda _e: toast.hide(), add="+")

    # ---- menu bar (macOS shows it at the top of the screen) -------------------------------
    def export_now():
        folder = home / "exports" if demo else Path.home() / "Documents" / "Vapor Board Exports"
        try:
            made, counts = export_csv(database, staff.path, folder)
        except DATA_ERRORS as exc:
            notify("danger", "Export failed", str(exc))
            return
        record("exported spreadsheets", made.name)
        notify("success", "Spreadsheets exported",
               f'{plural(counts["posts.csv"], "post")}, {plural(counts["messages.csv"], "message")} and '
               f'{plural(counts["customers.csv"], "customer")} saved to {short_path(made)}.')

    def when_signed_in(command):
        return lambda: command() if session[0] is not None else None

    def report_update(tag, problem, asked):
        if tag:
            notify("info", "Update available", f"{tag} is on the Vapor-Board-Releases page.")
        elif asked:
            notify("danger", "Update check failed", problem) if problem else notify("success", "You're up to date", f"This is {VERSION_LABEL}.")

    def check_updates(asked=False):
        """Runs off the main thread; a failure at launch is silent, a failure when asked is reported."""
        results = queue.Queue()

        def work():
            try:
                results.put((updates.check(), ""))
            except (OSError, ValueError) as exc:
                results.put((None, str(exc)))

        def collect():
            try:
                tag, problem = results.get_nowait()
            except queue.Empty:
                root.after(300, collect)
                return
            report_update(tag, problem, asked)

        threading.Thread(target=work, daemon=True).start()
        root.after(300, collect)

    menubar = tk.Menu(root, name="menubar")
    file_menu = tk.Menu(menubar, name="file", tearoff=0)
    for label, command, accelerator in (("Back Up Now", back_up_now, None), ("Restore From Backup…", restore_from_backup, None),
                                        (None, None, None), ("Export as Spreadsheets (CSV)", export_now, None),
                                        (None, None, None), ("Check for Updates…", lambda: check_updates(asked=True), None),
                                        (None, None, None), ("Start Kiosk", start_kiosk, None), ("Lock", lock, f"{key}L")):
        if label is None:
            file_menu.add_separator()
        else:
            file_menu.add_command(label=label, command=when_signed_in(command), accelerator=accelerator or "")
    menubar.add_cascade(label="File", menu=file_menu)
    root.configure(menu=menubar)

    def show_about():
        messagebox.showinfo("About Vapor Board",
                            f"Vapor Board {VERSION_LABEL}\n\nA local bulletin board for one shop. "
                            "Data stays on this Mac. Radio transmit is off unless you turn it on.", parent=root)

    try:
        root.createcommand("tk::mac::ShowAbout", show_about)  # macOS app menu ▸ About Vapor Board
    except tk.TclError:
        pass

    unread_count.trace_add("write", lambda *_: unread_note.set(
        "You're all caught up" if unread_count.get() == "0" else f"Waiting in the {mailbox} inbox"))
    refresh_boards()
    refresh_mail()
    if config_error:
        notify("warning", "Settings file couldn't be read", "Using default settings. See Settings for details.")
    update_footer()
    show_page("Overview")
    if demo_account is not None:
        enter(demo_account)
        notify("info", "Demo mode", "Sample shop data. Changes are thrown away next time. The radio is off.")
    else:
        open_gate()
    root.after(100, poll_radio)
    if config.check_for_updates and not demo:
        check_updates()
    root.mainloop()


if __name__ == "__main__":
    main()
