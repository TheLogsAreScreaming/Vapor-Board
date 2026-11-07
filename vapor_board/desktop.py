"""Vapor Board desktop: local boards and private messages, plus opt-in receive-only radio TCP.

Screens are drawn only with the components in ui_theme; wording comes from ui_format.
"""
import sqlite3
from datetime import timezone
import subprocess
import sys
import tkinter as tk
from tkinter import ttk
from pathlib import Path
from .config import ShopConfig, load_shop_config
from .status import StatusSnapshot
from .tcp import TcpSettings, ConnectionState
from .radio_worker import RadioWorker
from .radio_event_state import RadioDisplayState, reduce_event
from .board_browser import BoardBrowser
from .bbs import BulletinBoard
from .ui_format import friendly_time, radio_presentation, first_line, plural
from . import ui_theme as theme
from .ui_theme import XS, SM, MD, LG, XL
from tkinter import messagebox, filedialog
from . import backup as backups

# Sidebar order, grouped so everyday work sits above shop administration.
NAVIGATION = (
    ("WORKSPACE", (("Overview", "◧"), ("Boards", "▤"), ("Messages", "✉"))),
    ("SHOP", (("Customers", "◉"), ("Settings", "⚙"))),
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


def main():
    config_path = Path.home() / ".vapor-board" / "shop.json"
    config, config_error = read_config(config_path)
    database = Path.home() / ".vapor-board" / "bbs.sqlite"
    mailbox = config.operator_name.strip()
    root = tk.Tk()
    root.title(config.shop_name if config.shop_name == "Vapor Board" else f"{config.shop_name} — Vapor Board")
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
        "Customers": "Customer approvals and age verification.",
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
    settings_page, settings_actions = page_parts["Settings"]

    messages_badge = tk.Label(nav_buttons["Messages"], name="messages_badge", bg=p.accent_fill, fg=p.on_accent,
                              font=t.fonts["label"], padx=t.px(7), pady=0, cursor="hand2")
    messages_badge.bind("<Button-1>", lambda _e: show_page("Messages"))

    # Radio summary pinned to the bottom of the sidebar.
    sidebar_status = ttk.Frame(sidebar, style="Sidebar.TFrame", padding=(t.px(20), t.px(LG)))
    sidebar_status.pack(side="bottom", fill="x")
    ttk.Label(sidebar_status, text="RADIO", style="Sidebar.Section.TLabel").pack(anchor="w")
    sidebar_pill = theme.Pill(sidebar_status, t, p.sidebar, "neutral", "Not connected")
    sidebar_pill.label.pack(anchor="w", pady=(t.px(6), t.px(XS)))
    ttk.Label(sidebar_status, text="Listen-only · transmit off", style="Sidebar.Caption.TLabel").pack(anchor="w")

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
    _holder, post_editor = theme.text_area(composer.body, t, height=4)
    _holder.pack(fill="x")
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
            author_entry.state(["disabled"])
            composer_hint.set(f"{key}↩ save  ·  Esc cancel")
        else:
            composer.title_var.set(f'New post in {board["name"]}' if board else "New post")
            composer.subtitle_var.set(f"Write a notice, then publish it ({key}↩)." if board else "Choose a board first, then write your post.")
            publish_button.configure(text="Publish post")
            cancel_button.state(["disabled"])
            if author_entry.instate(["disabled"]):
                author_name.set(new_author[0])
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
            posts.insert("end", f'  ·  #{entry["id"]}  ·  {friendly_time(entry["created_at"])}{pinned}\n', "meta")
            posts.insert("end", entry["body"])
            posts.mark_set(f"post{index}", start)
            posts.mark_gravity(f"post{index}", "left")
        if not shown_posts:
            posts.insert("1.0", error or "No posts yet.", "placeholder")
        posts.configure(state="disabled")
        post_list.set_rows([(f'{"◆  " if entry.get("pinned_at") else ""}{entry["author"]} — {first_line(entry["body"], 40)}', ())
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
        notify("success", "Post pinned" if pin else "Post unpinned",
               f'It stays at the top of {board["name"]}.' if pin else "It's back in date order.")
    board_entry.bind("<Return>", lambda _e: create_local_board())

    def save_local_post():
        board = current_board()
        if board is None:
            notify("warning", "Choose a board first", "Pick the board this post belongs to.")
            return
        try:
            BulletinBoard(database).post(board["id"], author_name.get(), post_editor.get("1.0", "end-1c"))
        except DATA_ERRORS as exc:
            notify("danger", "Post not published", str(exc))
            return
        post_editor.delete("1.0", "end")
        has_posts[0] = True
        show_posts()
        notify("success", "Post published", f'Added to {board["name"]}.')

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
            BulletinBoard(database).edit_post(entry["id"], post_editor.get("1.0", "end-1c"))
        except DATA_ERRORS as exc:
            notify("danger", "Post not updated", str(exc))
            return
        post_editor.delete("1.0", "end")
        set_composer_mode(None)
        show_posts(keep=entry["id"])
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
    # Private messages for the operator mailbox named in shop.json. Until operator
    # sign-in exists (Phase 5) the sender is fixed to that mailbox, never typed in.
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
    customers_card = theme.Card(customers_page, t).pack(fill="x")
    theme.empty_state(customers_card.body, t, "◉", "Customer access isn't available yet",
                      "Customer approvals and 21+ age verification switch on once staff sign-in is added. "
                      "Until then, no customer can reach this board.").pack(fill="x")
    planned = ttk.Frame(customers_card.body, style="Card.TFrame")
    planned.pack(pady=(0, t.px(SM)))
    ttk.Label(planned, text="PLANNED", style="Card.Section.TLabel").pack(anchor="w", pady=(0, t.px(XS)))
    for line in ("Approve each customer before they can read or post",
                 f"Confirm every customer is {config.minimum_customer_age} or older",
                 "Choose which boards each customer can see"):
        ttk.Label(planned, text=f"○   {line}", style="Card.Muted.TLabel").pack(anchor="w", pady=1)

    # ==== Settings =========================================================================
    settings_body = ttk.Frame(settings_page)
    settings_body.pack(fill="both", expand=True)
    settings_body.columnconfigure(0, weight=1, uniform="settings")
    settings_body.columnconfigure(1, weight=1, uniform="settings")
    left_settings = ttk.Frame(settings_body)
    left_settings.grid(row=0, column=0, sticky="nsew", padx=(0, t.px(8)))
    right_settings = ttk.Frame(settings_body)
    right_settings.grid(row=0, column=1, sticky="nsew", padx=(t.px(8), 0))

    if config_error:
        problem = theme.Card(right_settings, t, "Settings file couldn't be read",
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
    settings_card(left_settings, "Shop", (
        ("Shop name", config.shop_name, None),
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

    # Backup buttons live in the page header: the left column has no spare height at 900x600.
    settings_card(left_settings, "Storage", (
        ("Settings file", "Found" if config_path.exists() else "Not created (defaults)", short_path(config_path)),
        ("Database", database_state, last_backup),
    ), pady=(t.px(LG), 0))

    def back_up_now():
        try:
            made = backups.create_backup(database, backup_folder)
        except backups.BackupError as exc:
            notify("danger", "Backup not made", str(exc))
            return
        refresh_storage()
        notify("success", "Backup saved", f"{made.summary} copied to {short_path(made.path)}.")

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
        try:
            safety = backups.restore_backup(chosen, database, backup_folder)
        except backups.BackupError as exc:
            notify("danger", "Restore failed", str(exc))
            return
        cancel_edit()
        refresh_boards()
        refresh_mail()
        refresh_overview()
        refresh_storage()
        notify("success", "Backup restored",
               f"{info.summary} restored." + (f" Previous data saved as {safety.path.name}." if safety else ""))

    backup_now = ttk.Button(settings_actions, text="Back up now", command=back_up_now)
    backup_now.pack(side="left")
    ttk.Button(settings_actions, text="Restore…", command=restore_from_backup).pack(side="left", padx=(t.px(SM), 0))
    refresh_storage()
    settings_card(right_settings, "Radio & network", (
        ("Radio transmit", ("success", "On") if config.transmissions_enabled else ("neutral", "Off"),
         "Vapor Board only listens to the mesh. Sending is not available yet."),
        ("MQTT bridge", ("success", "On") if config.mqtt_enabled else ("neutral", "Off"),
         "No internet bridge. Nothing leaves your local network."),
    ))
    settings_card(right_settings, "Customer access", (
        ("Approval before joining", ("success", "Required") if config.customer_access_requires_approval else ("warning", "Not required"), None),
        ("Minimum age", f"{config.minimum_customer_age}+", None),
    ), pady=(t.px(LG), 0))
    ttk.Label(right_settings, text="To change a setting, edit shop.json and restart Vapor Board.",
              style="Caption.TLabel", wraplength=t.px(330), justify="left").pack(anchor="w", pady=(t.px(MD), 0))

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
            (display_state[0].tcp == ConnectionState.CONNECTED, "Connect a radio (optional)", "Listen in on your mesh. Nothing is transmitted.", None, None),
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
        for done, title, detail, action, command in steps:
            row = ttk.Frame(checklist, style="Card.TFrame")
            row.pack(fill="x", pady=(0, t.px(6)))
            tk.Label(row, text="✓" if done else "○", bg=p.card, fg=p.success if done else p.subtle,
                     font=t.fonts["body_bold"], width=2).pack(side="left", anchor="n")
            words = ttk.Frame(row, style="Card.TFrame")
            words.pack(side="left", fill="x", expand=True)
            ttk.Label(words, text=title, style="Card.Muted.TLabel" if done else "Card.Strong.TLabel").pack(anchor="w")
            ttk.Label(words, text=detail, style="Card.Caption.TLabel", wraplength=t.px(270), justify="left").pack(anchor="w")
            if action and not done:
                ttk.Button(words, text=f"{action}  →", style="Link.TButton", command=command).pack(anchor="w")
        checklist.pack(fill="both", expand=True)

    on_show["Overview"] = refresh_overview

    radio_card = theme.Card(lower, t, "Meshtastic radio", "Listen-only connection over Wi-Fi.").grid(row=0, column=1, sticky="nsew")
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
    ttk.Label(radio_card.body, text="The radio's IP address or name on your network. The port is usually 4403.",
              style="Card.Caption.TLabel", wraplength=t.px(330), justify="left").pack(anchor="w", pady=(t.px(6), 0))
    settings_error = ttk.Label(radio_card.body, text="", style="Card.Danger.TLabel", wraplength=t.px(330), justify="left")
    radio_status = tk.StringVar(value=radio_presentation(RadioDisplayState())[2])
    ttk.Label(radio_card.body, textvariable=radio_status, style="Card.TLabel", wraplength=t.px(330), justify="left").pack(anchor="w", pady=(t.px(MD), 0))
    display_state = [RadioDisplayState()]
    pulse_job = [None]

    def connect_radio(_event=None):
        try:
            settings = TcpSettings(host=host_var.get().strip(), port=int(port_var.get()), timeout=3.0)
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
        connect_button.state(["disabled"] if busy else ["!disabled"])
        disconnect_button.state(["!disabled"] if busy else ["disabled"])
        for entry in (host_entry, port_entry):
            entry.state(["disabled"] if busy else ["!disabled"])
        if display_state[0].tcp == ConnectionState.CONNECTING and not t.reduce_motion and pulse_job[0] is None:
            pulse_job[0] = root.after(650, pulse, False)

    def poll_radio():
        if not root.winfo_exists():
            return
        for _ in range(100):
            event = worker.poll()
            if event is None:
                break
            kind, data = event
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

    # ---- status bar, keyboard, start-up ---------------------------------------------------
    root.protocol("WM_DELETE_WINDOW", on_close)
    status_bar = tk.Frame(main_area, bg=p.background)
    status_bar.pack(side="bottom", fill="x")
    tk.Frame(main_area, bg=p.border, height=1).pack(side="bottom", fill="x")
    footer = tk.Label(status_bar, text=StatusSnapshot().footer, bg=p.background, fg=p.muted,
                      font=t.fonts["caption"], padx=t.px(28), pady=t.px(7), anchor="w")
    footer.pack(side="left")
    tk.Label(status_bar, text=f"{key}1–5 switch pages  ·  {key}N new  ·  {key}R refresh", bg=p.background, fg=p.subtle,
             font=t.fonts["caption"], padx=t.px(28)).pack(side="right")
    page_host.pack(fill="both", expand=True)

    order = [name for _section, entries in NAVIGATION for name, _glyph in entries]
    for number, name in enumerate(order, start=1):
        root.bind_all(f"<{mod}-Key-{number}>", lambda _e, name=name: show_page(name))
    root.bind_all(f"<{mod}-n>", lambda _e: new_message() if current[0] == "Messages" else new_post())
    root.bind_all(f"<{mod}-r>", lambda _e: {"Boards": refresh_boards, "Messages": refresh_mail, "Search": run_search}.get(current[0], refresh_overview)())
    root.bind_all(f"<{mod}-f>", focus_search)
    root.bind_all("<Escape>", lambda _e: toast.hide(), add="+")

    unread_count.trace_add("write", lambda *_: unread_note.set(
        "You're all caught up" if unread_count.get() == "0" else f"Waiting in the {mailbox} inbox"))
    refresh_boards()
    refresh_mail()
    if config_error:
        notify("warning", "Settings file couldn't be read", "Using default settings. See Settings for details.")
    update_footer()
    show_page("Overview")
    root.after(100, poll_radio)
    root.mainloop()


if __name__ == "__main__":
    main()
