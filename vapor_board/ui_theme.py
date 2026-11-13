"""Vapor Board design system: tokens, ttk styles and the shared desktop components.

Everything visual lives here so screens never hard-code colours, fonts or spacing.
Two palettes (light and dark) share one set of semantic token names; the shop's accent
colour is adjusted per palette so text on it, and text in it, stays readable (WCAG AA).
"""
import subprocess
import sys
import tkinter as tk
import tkinter.font as tkfont
from dataclasses import dataclass, replace
from tkinter import ttk

# Spacing scale (px). Screens use these names, never raw numbers.
XS, SM, MD, LG, XL, XXL = 4, 8, 12, 16, 24, 32

TEXT_SCALES = {"standard": 1.0, "large": 1.15, "larger": 1.3}


@dataclass(frozen=True)
class Palette:
    name: str
    sidebar: str
    background: str
    card: str
    raised: str        # hover and secondary-button surface
    field: str         # inputs, lists and text areas
    border: str
    border_strong: str
    text: str
    muted: str         # secondary text; at least 4.5:1 on card and background
    subtle: str        # disabled controls only; anything meant to be read uses muted
    success: str
    warning: str
    danger: str
    info: str
    # Accent derivations, filled in by with_accent().
    accent: str = "#238C9C"
    accent_fill: str = "#1D7482"   # button background; white text on it is >= 4.5:1
    accent_hover: str = "#20808F"
    accent_text: str = "#1D7482"   # accent used as text/icon colour on cards
    selection: str = "#D4ECEF"     # selected list row
    on_accent: str = "#FFFFFF"


DARK = Palette(
    name="dark", sidebar="#0B1117", background="#10171E", card="#161F28", raised="#1F2A35",
    field="#0E151C", border="#253240", border_strong="#344555", text="#E6EDF3", muted="#9AA6B2",
    subtle="#64717E", success="#3FB950", warning="#D29922", danger="#F85149", info="#58A6FF",
)
LIGHT = Palette(
    name="light", sidebar="#EEF1F5", background="#F6F8FA", card="#FFFFFF", raised="#EDF0F3",
    field="#FFFFFF", border="#D8DEE4", border_strong="#C1C9D2", text="#1F2328", muted="#57606A",
    subtle="#8C959F", success="#1A7F37", warning="#9A6700", danger="#CF222E", info="#0969DA",
)


# --- colour maths -------------------------------------------------------------------------

def _rgb(color):
    return tuple(int(color[i:i + 2], 16) for i in (1, 3, 5))


def _hex(rgb):
    return "#" + "".join(f"{max(0, min(255, round(c))):02X}" for c in rgb)


def shade(color, factor):
    """Lighten (factor > 1) or darken (factor < 1) a #RRGGBB colour."""
    return _hex(c * factor for c in _rgb(color))


def blend(color, base, amount):
    """Mix amount (0–1) of color into base."""
    return _hex(b + (c - b) * amount for c, b in zip(_rgb(color), _rgb(base)))


def luminance(color):
    def channel(c):
        c /= 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (channel(c) for c in _rgb(color))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b):
    """WCAG contrast ratio between two colours (1–21)."""
    hi, lo = sorted((luminance(a), luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def readable(color, against, minimum=4.5):
    """Nudge color toward black or white until it reaches minimum contrast against `against`."""
    target = "#FFFFFF" if luminance(against) < 0.4 else "#000000"
    step = 0.0
    result = color
    while contrast(result, against) < minimum and step < 1.0:
        step += 0.05
        result = blend(target, color, step)
    return result


def with_accent(palette, accent):
    """Derive readable accent tokens for this palette from the shop's chosen colour."""
    fill = accent
    while contrast("#FFFFFF", fill) < 4.5:
        fill = shade(fill, 0.92)
    return replace(
        palette, accent=accent, accent_fill=fill,
        accent_hover=shade(fill, 1.12) if palette.name == "dark" else shade(fill, 0.9),
        accent_text=readable(accent, palette.card),
        selection=blend(accent, palette.field, 0.28 if palette.name == "dark" else 0.16),
    )


# --- system preferences -------------------------------------------------------------------

def _mac_default(*args):
    if sys.platform != "darwin":
        return None
    try:
        result = subprocess.run(["defaults", "read", *args], capture_output=True, text=True, timeout=2)
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def system_appearance():
    """'dark' or 'light' from macOS; light elsewhere or when unknown."""
    return "dark" if _mac_default("-g", "AppleInterfaceStyle") == "Dark" else "light"


def system_reduce_motion():
    return _mac_default("com.apple.universalaccess", "reduceMotion") == "1"


# --- theme --------------------------------------------------------------------------------

@dataclass(frozen=True)
class Theme:
    palette: Palette
    fonts: dict
    scale: float
    reduce_motion: bool
    shortcut: str      # "Command" on macOS, "Control" elsewhere
    shortcut_label: str
    nav_colours: dict = None

    def px(self, value):
        return round(value * self.scale)


def build_fonts(scale):
    family = tkfont.nametofont("TkDefaultFont").actual("family")

    def size(points):
        return round(points * scale)

    return {
        "body": (family, size(13)),
        "body_bold": (family, size(13), "bold"),
        "small": (family, size(12)),
        "caption": (family, size(11)),
        "label": (family, size(11), "bold"),
        "button": (family, size(12), "bold"),
        "nav": (family, size(13)),
        "section": (family, size(10), "bold"),
        "title": (family, size(22), "bold"),
        "headline": (family, size(15), "bold"),
        "brand": (family, size(15), "bold"),
        "monogram": (family, size(16), "bold"),
        "stat": (family, size(28), "bold"),
        "glyph": (family, size(14)),
        "empty_glyph": (family, size(30)),
        "mono": ("Menlo", size(12)),
    }


def resolve_appearance(choice):
    return system_appearance() if choice == "system" else choice


def apply_theme(root, accent, appearance="system", text_size="standard"):
    """Install every Vapor Board style on root and return the Theme screens draw with."""
    palette = with_accent(DARK if resolve_appearance(appearance) == "dark" else LIGHT, accent)
    scale = TEXT_SCALES.get(text_size, 1.0)
    f = build_fonts(scale)
    aqua = root.tk.call("tk", "windowingsystem") == "aqua"
    t = Theme(palette, f, scale, system_reduce_motion(), "Command" if aqua else "Control", "⌘" if aqua else "Ctrl+", {})
    p = palette
    root.configure(bg=p.background)
    style = ttk.Style(root)
    style.theme_use("clam")  # aqua ignores custom colours; clam honours them
    style.configure(".", background=p.background, foreground=p.text, font=f["body"],
                    bordercolor=p.border, lightcolor=p.border, darkcolor=p.border,
                    troughcolor=p.field, focuscolor=p.accent_text, selectbackground=p.selection,
                    selectforeground=p.text, insertcolor=p.text)

    surfaces = (("", p.background), ("Card.", p.card), ("Sidebar.", p.sidebar))
    for prefix, bg in surfaces:
        style.configure(f"{prefix}TFrame", background=bg)
        # ttk resolves "Card.Muted.TLabel" via "Muted.TLabel", not "Card.TLabel", so every
        # combination sets its own background explicitly.
        for role, fg, font in (("", p.text, f["body"]), ("Muted.", p.muted, f["small"]),
                               ("Caption.", p.muted, f["caption"]), ("Field.", p.muted, f["label"]),
                               ("Strong.", p.text, f["body_bold"]), ("Headline.", p.text, f["headline"]),
                               ("Section.", p.muted, f["section"]),
                               ("Accent.", p.accent_text, f["body_bold"]), ("Danger.", readable(p.danger, bg), f["small"]),
                               ("Stat.", p.text, f["stat"]), ("Glyph.", p.muted, f["glyph"])):
            style.configure(f"{prefix}{role}TLabel", background=bg, foreground=fg, font=font)
    style.configure("Title.TLabel", background=p.background, foreground=p.text, font=f["title"])
    style.configure("Sidebar.Brand.TLabel", background=p.sidebar, foreground=p.text, font=f["brand"])

    pad = (t.px(14), t.px(7))

    def button(name, bg, fg, hover, border, pressed=None):
        style.configure(name, background=bg, foreground=fg, font=f["button"], padding=pad, width=-4,
                        borderwidth=1, relief="flat", bordercolor=border, lightcolor=bg, darkcolor=bg,
                        focuscolor=fg, focusthickness=1, anchor="center")
        style.map(name,
                  background=[("disabled", p.raised if bg != p.card else p.card), ("pressed", pressed or hover), ("active", hover)],
                  foreground=[("disabled", p.subtle)],
                  bordercolor=[("disabled", p.border), ("focus", p.accent_text)],
                  lightcolor=[("disabled", p.raised if bg != p.card else p.card), ("active", hover)],
                  darkcolor=[("disabled", p.raised if bg != p.card else p.card), ("active", hover)])

    button("Accent.TButton", p.accent_fill, p.on_accent, p.accent_hover, p.accent_fill, shade(p.accent_fill, 0.9))
    button("TButton", p.raised, p.text, blend(p.text, p.raised, 0.08), p.border_strong)
    button("Ghost.TButton", p.card, p.accent_text, p.raised, p.card)
    button("Link.TButton", p.card, p.accent_text, p.card, p.card)
    style.configure("Link.TButton", padding=(0, t.px(4)), anchor="w")
    style.map("Link.TButton", foreground=[("active", p.text), ("disabled", p.subtle)])
    button("Sidebar.Link.TButton", p.sidebar, p.accent_text, p.sidebar, p.sidebar)
    style.configure("Sidebar.Link.TButton", padding=(0, t.px(2)), anchor="e")
    style.map("Sidebar.Link.TButton", foreground=[("active", p.text), ("disabled", p.subtle)])
    button("Danger.TButton", p.card, readable(p.danger, p.card), blend(p.danger, p.card, 0.12), blend(p.danger, p.card, 0.45))
    button("Segment.TButton", p.field, p.muted, p.raised, p.border)
    button("SegmentActive.TButton", p.selection, p.text, p.selection, p.accent_text)

    nav_active = blend(p.accent, p.sidebar, 0.16)
    nav_hover = blend(p.text, p.sidebar, 0.06)
    for name, bg, fg in (("Nav.TButton", p.sidebar, p.muted), ("NavActive.TButton", nav_active, p.text)):
        style.configure(name, background=bg, foreground=fg, font=f["nav"], anchor="w", width=-4,
                        padding=(t.px(44), t.px(8), t.px(12), t.px(8)), borderwidth=0, relief="flat", focuscolor=p.accent_text,
                        focusthickness=1, lightcolor=bg, darkcolor=bg, bordercolor=bg)
    style.map("Nav.TButton", background=[("active", nav_hover)], foreground=[("active", p.text)])
    style.map("NavActive.TButton", background=[("active", nav_active)])
    t.nav_colours.update(idle=p.sidebar, hover=nav_hover, active=nav_active)

    style.configure("TEntry", fieldbackground=p.field, foreground=p.text, insertcolor=p.text,
                    padding=(t.px(8), t.px(6)), bordercolor=p.border_strong, lightcolor=p.field, darkcolor=p.field,
                    selectbackground=p.selection, selectforeground=p.text)
    style.map("TEntry", bordercolor=[("invalid", p.danger), ("focus", p.accent_text)],
              lightcolor=[("focus", p.accent_text)], fieldbackground=[("disabled", p.raised)],
              foreground=[("disabled", p.subtle)])

    style.configure("List.Treeview", background=p.field, fieldbackground=p.field, foreground=p.text,
                    font=f["body"], rowheight=t.px(32), borderwidth=0, relief="flat", indent=0)
    style.map("List.Treeview", background=[("selected", p.selection)], foreground=[("selected", p.text)])
    style.layout("List.Treeview", [("Treeview.treearea", {"sticky": "nswe"})])

    style.configure("Vertical.TScrollbar", background=p.raised, troughcolor=p.field, bordercolor=p.field,
                    arrowcolor=p.muted, lightcolor=p.raised, darkcolor=p.raised, gripcount=0, arrowsize=t.px(11))
    style.map("Vertical.TScrollbar", background=[("active", p.border_strong)])
    style.configure("TSeparator", background=p.border)
    return t


# --- components ---------------------------------------------------------------------------

def _autohide(scrollbar):
    """yscrollcommand that shows the scrollbar only when content overflows."""
    def update(lo, hi):
        if float(lo) <= 0.0 and float(hi) >= 1.0:
            scrollbar.grid_remove()
        else:
            scrollbar.grid()
        scrollbar.set(lo, hi)
    return update


def _focus_frame(parent, t):
    """Bordered holder whose outline turns accent while its child has keyboard focus."""
    p = t.palette
    return tk.Frame(parent, bg=p.field, highlightthickness=1, highlightbackground=p.border_strong,
                    highlightcolor=p.accent_text)


class Card:
    """Bordered surface with an optional header (title, subtitle, actions) and a body."""

    def __init__(self, parent, t, title=None, subtitle=None, padding=LG):
        p = t.palette
        self.outer = tk.Frame(parent, bg=p.card, highlightthickness=1, highlightbackground=p.border,
                              highlightcolor=p.border)
        # Keep this object (and its StringVars) alive as long as the widget; otherwise a card
        # nobody holds a reference to loses its title when Python collects the variables.
        self.outer.card = self
        inner = ttk.Frame(self.outer, style="Card.TFrame", padding=t.px(padding))
        inner.pack(fill="both", expand=True)
        self.header = ttk.Frame(inner, style="Card.TFrame")
        self.actions = ttk.Frame(self.header, style="Card.TFrame")
        self.title_var = tk.StringVar(value=title or "")
        self.subtitle_var = tk.StringVar(value=subtitle or "")
        if title is not None or subtitle is not None:
            self.header.pack(fill="x", pady=(0, t.px(MD)))
            self.actions.pack(side="right", anchor="n")
            heading = ttk.Frame(self.header, style="Card.TFrame")
            heading.pack(side="left", fill="x", expand=True)
            if title is not None:
                ttk.Label(heading, textvariable=self.title_var, style="Card.Headline.TLabel").pack(anchor="w")
            if subtitle is not None:
                self.subtitle = ttk.Label(heading, textvariable=self.subtitle_var, style="Card.Muted.TLabel",
                                          wraplength=t.px(460), justify="left")
                self.subtitle.pack(anchor="w", pady=(2, 0))
        self.body = ttk.Frame(inner, style="Card.TFrame")
        self.body.pack(fill="both", expand=True)

    def pack(self, **options):
        self.outer.pack(**options)
        return self

    def grid(self, **options):
        self.outer.grid(**options)
        return self


class ListView:
    """Single-selection list with roomy rows, keyboard navigation and an auto-hiding scrollbar.

    on_select(index) runs when the operator picks a row; select() from code does not call it.
    """

    def __init__(self, parent, t, height=6, on_select=None, placeholder=""):
        self.t = t
        self.frame = _focus_frame(parent, t)
        self.frame.columnconfigure(0, weight=1)
        self.frame.rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(self.frame, style="List.Treeview", show="tree", selectmode="browse", height=height)
        self.tree.column("#0", width=t.px(120), stretch=True)
        self.tree.grid(row=0, column=0, sticky="nsew", padx=1, pady=1)
        bar = ttk.Scrollbar(self.frame, orient="vertical", command=self.tree.yview)
        bar.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=_autohide(bar))
        self.tree.tag_configure("strong", font=t.fonts["body_bold"])
        self.tree.tag_configure("placeholder", foreground=t.palette.muted)
        self.tree.tag_configure("error", foreground=readable(t.palette.danger, t.palette.field))
        self.tree.bind("<FocusIn>", lambda _e: self.frame.configure(highlightbackground=t.palette.accent_text))
        self.tree.bind("<FocusOut>", lambda _e: self.frame.configure(highlightbackground=t.palette.border_strong))
        self.on_select = on_select
        self.placeholder = placeholder
        self._count = 0
        self._quiet = None  # pending idle callback while code (not the operator) changes the list
        self._expected = ()
        self.tree.bind("<<TreeviewSelect>>", self._selected)

    def _hush(self):
        """Ignore the selection events our own changes queue (they arrive before the next idle),
        but only while the selection is still the one we set, so an operator's pick always counts."""
        if self._quiet is None:
            # Scheduled on the main window, so a list inside a dialog doesn't leave the dialog owning the callback.
            self._quiet = self.tree._root().after_idle(self._unhush)

    def _unhush(self):
        self._quiet = None

    def _selected(self, _event=None):
        if self._quiet is not None and self.tree.selection() == self._expected:
            return
        self._expected = self.tree.selection()
        index = self.selected()
        if index is not None and self.on_select:
            self.on_select(index)

    def set_rows(self, rows, placeholder=None, tag="placeholder"):
        """rows: list of (text, tags). An empty list shows a muted placeholder row."""
        self._hush()
        self.tree.delete(*self.tree.get_children())
        self._count = len(rows)
        for index, (text, tags) in enumerate(rows):
            self.tree.insert("", "end", iid=str(index), text="  " + text, tags=tags)
        if not rows and (placeholder or self.placeholder):
            self.tree.insert("", "end", iid="placeholder", text="  " + (placeholder or self.placeholder), tags=(tag,))
        self._expected = self.tree.selection()

    def size(self):
        return self._count

    def row_text(self, index):
        return self.tree.item(str(index), "text")[2:]

    def rows(self):
        return tuple(self.row_text(i) for i in range(self._count))

    def selected(self):
        current = self.tree.selection()
        if not current or current[0] == "placeholder":
            return None
        index = int(current[0])
        return index if index < self._count else None

    def select(self, index):
        if 0 <= index < self._count:
            self._hush()
            self.tree.selection_set(str(index))
            self.tree.see(str(index))
            self._expected = self.tree.selection()

    def clear_selection(self):
        if self.tree.selection():
            self._hush()
            self.tree.selection_remove(*self.tree.selection())
            self._expected = ()


def text_area(parent, t, height=4, readonly=False):
    """Multi-line text in a focus-outlined frame with an auto-hiding scrollbar. Returns (holder, text)."""
    p = t.palette
    holder = _focus_frame(parent, t)
    holder.columnconfigure(0, weight=1)
    holder.rowconfigure(0, weight=1)
    text = tk.Text(holder, height=height, width=30, wrap="word", bg=p.field, fg=p.text, font=t.fonts["body"],
                   relief="flat", borderwidth=0, padx=t.px(MD), pady=t.px(10), insertbackground=p.text,
                   highlightthickness=0, selectbackground=p.selection, selectforeground=p.text,
                   spacing1=2, spacing3=2, undo=not readonly, state="disabled" if readonly else "normal",
                   cursor="arrow" if readonly else "xterm")
    text.grid(row=0, column=0, sticky="nsew")
    bar = ttk.Scrollbar(holder, orient="vertical", command=text.yview)
    bar.grid(row=0, column=1, sticky="ns")
    text.configure(yscrollcommand=_autohide(bar))
    text.bind("<FocusIn>", lambda _e: holder.configure(highlightbackground=p.accent_text))
    text.bind("<FocusOut>", lambda _e: holder.configure(highlightbackground=p.border_strong))
    if not readonly:
        # Tab moves focus on (as in every other field) instead of typing a tab character.
        text.bind("<Tab>", lambda e: (e.widget.tk_focusNext().focus_set(), "break")[1])
        text.bind("<Shift-Tab>", lambda e: (e.widget.tk_focusPrev().focus_set(), "break")[1])
    text.tag_configure("author", foreground=p.text, font=t.fonts["body_bold"])
    text.tag_configure("meta", foreground=p.muted, font=t.fonts["caption"])
    text.tag_configure("placeholder", foreground=p.muted, font=t.fonts["body"])
    text.tag_configure("selected", background=blend(p.accent, p.field, 0.12))
    return holder, text


PILL_KINDS = ("neutral", "success", "warning", "danger", "info", "accent")


class Pill:
    """Small rounded-feeling status badge: tinted background, strong text, leading dot."""

    def __init__(self, parent, t, surface, kind="neutral", text="", dot=True):
        self.t, self.surface, self.dot = t, surface, dot
        self.label = tk.Label(parent, font=t.fonts["label"], padx=t.px(10), pady=t.px(3), borderwidth=0)
        self.kind = None
        self.set(kind, text)

    def colour(self, kind):
        p = self.t.palette
        return {"neutral": p.muted, "success": p.success, "warning": p.warning,
                "danger": p.danger, "info": p.info, "accent": p.accent}[kind]

    def set(self, kind, text, dim=False):
        base = self.colour(kind)
        self.kind = kind
        fg = readable(base, blend(base, self.surface, 0.16))
        self.label.configure(text=("●  " if self.dot else "") + text,
                             bg=blend(base, self.surface, 0.16), fg=blend(fg, self.surface, 0.45) if dim else fg)

    def cget_text(self):
        return self.label.cget("text")


class Toast:
    """Non-blocking notice floating over the top-right of a container; never shifts the layout.

    Success and info notices disappear on their own; warnings and errors stay until dismissed.
    """

    ICONS = {"success": "✓", "info": "i", "warning": "!", "danger": "✕"}

    def __init__(self, parent, t):
        p = t.palette
        self.t = t
        self.frame = tk.Frame(parent, name="toast", bg=p.card, highlightthickness=1, highlightbackground=p.border_strong)
        self.stripe = tk.Frame(self.frame, width=4, bg=p.accent)
        self.stripe.pack(side="left", fill="y")
        self.icon = tk.Label(self.frame, bg=p.card, font=t.fonts["body_bold"], width=2)
        self.icon.pack(side="left", padx=(t.px(10), 0), pady=t.px(10))
        body = tk.Frame(self.frame, bg=p.card)
        body.pack(side="left", fill="both", expand=True, padx=(t.px(6), t.px(4)), pady=t.px(10))
        self.title = tk.Label(body, name="toast_title", bg=p.card, fg=p.text, font=t.fonts["body_bold"], anchor="w", justify="left")
        self.title.pack(anchor="w")
        self.message = tk.Label(body, name="toast_message", bg=p.card, fg=p.muted, font=t.fonts["small"],
                                anchor="w", justify="left", wraplength=t.px(320))
        self.close = tk.Label(self.frame, text="✕", bg=p.card, fg=p.muted, font=t.fonts["small"], cursor="hand2",
                              padx=t.px(10))
        self.close.pack(side="right", anchor="n", pady=t.px(8))
        self.close.bind("<Button-1>", lambda _e: self.hide())
        self._after = None
        self.kind = None
        self.root = parent.winfo_toplevel()  # timers live on the window so closing it cancels them cleanly

    def show(self, kind, title, message=""):
        p = self.t.palette
        colour = {"success": p.success, "info": p.info, "warning": p.warning, "danger": p.danger}[kind]
        self.kind = kind
        self.stripe.configure(bg=colour)
        self.icon.configure(text=self.ICONS[kind], fg=readable(colour, p.card))
        self.title.configure(text=title)
        self.message.configure(text=message)
        if message:
            self.message.pack(anchor="w", pady=(2, 0))
        else:
            self.message.pack_forget()
        self.frame.place(relx=1.0, x=-self.t.px(XL), y=self.t.px(LG), anchor="ne")
        self.frame.lift()
        if self._after:
            self.root.after_cancel(self._after)
            self._after = None
        if kind in ("success", "info"):
            self._after = self.root.after(3500, self.hide)

    def hide(self):
        if self._after:
            self.root.after_cancel(self._after)
            self._after = None
        self.frame.place_forget()
        self.kind = None

    def visible(self):
        return self.kind is not None

    def text(self):
        parts = [self.title.cget("text"), self.message.cget("text")]
        return ": ".join(part for part in parts if part)


def empty_state(parent, t, glyph, heading, body, surface="Card."):
    """Centred icon, heading and explanation for a screen or panel with nothing to show yet."""
    holder = ttk.Frame(parent, style=f"{surface}TFrame", padding=t.px(XL))
    ttk.Label(holder, text=glyph, style=f"{surface}Glyph.TLabel", font=t.fonts["empty_glyph"]).pack()
    ttk.Label(holder, text=heading, style=f"{surface}Headline.TLabel").pack(pady=(t.px(SM), 0))
    ttk.Label(holder, text=body, style=f"{surface}Muted.TLabel", wraplength=t.px(420), justify="center").pack(pady=(t.px(XS), 0))
    return holder


def field(parent, t, label, variable, helper=None, width=None):
    """Labelled single-line input with optional helper text. Returns (entry, helper_label)."""
    ttk.Label(parent, text=label, style="Card.Field.TLabel").pack(anchor="w")
    entry = ttk.Entry(parent, textvariable=variable, width=width or 20)
    entry.pack(fill="x", pady=(t.px(XS), 0))
    note = ttk.Label(parent, text=helper or "", style="Card.Caption.TLabel", wraplength=t.px(320), justify="left")
    if helper:
        note.pack(anchor="w", pady=(t.px(XS), 0))
    return entry, note
