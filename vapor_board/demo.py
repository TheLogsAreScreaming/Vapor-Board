"""Demo mode: a throwaway shop with sample data, kept apart from the real one.

Started with ``--demo``. Everything lives in ``~/.vapor-board-demo``, which is wiped and
re-seeded on every demo launch. The radio cannot be connected in demo mode.
"""
import secrets
import shutil
from pathlib import Path
from .accounts import StaffDirectory
from .bbs import BulletinBoard
from .config import ShopConfig
from .customers import CustomerBook

FOLDER = ".vapor-board-demo"
CONFIG = ShopConfig(shop_name="Corner Shop (demo)", operator_name="Corner Shop", kiosk_fullscreen=False, auto_lock_minutes=0)


def prepare(home=None):
    """Reset the demo folder and seed it. Returns (folder, signed-in staff Account)."""
    folder = Path(home or Path.home()) / FOLDER
    if folder.name != FOLDER:  # never remove anything but the demo folder
        raise ValueError("unexpected demo folder")
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True)
    staff = StaffDirectory(folder / "staff.sqlite")
    owner = staff.create("demo", "Demo Owner", secrets.token_urlsafe(16), iterations=1000)  # password never needed
    staff.create("jess", "Jess", secrets.token_urlsafe(16), actor=owner, iterations=1000)
    bbs = BulletinBoard(folder / "bbs.sqlite")
    hours = bbs.create_board("Store hours")
    news = bbs.create_board("New arrivals")
    notes = bbs.create_board("Staff notes")
    bbs.set_customer_visible(notes, False)
    pinned = bbs.post(hours, "Demo Owner", "Open 10 am – 8 pm Monday to Saturday, 12 – 6 pm Sunday.")
    bbs.pin_post(pinned, True)
    bbs.post(hours, "Jess", "Closing at 4 pm on Thursday for stocktaking.")
    bbs.post(news, "Jess", "New glass and accessories are on the shelves this week.")
    bbs.post(notes, "Demo Owner", "Delivery arrives Tuesday morning. Check the invoice before signing.")
    bbs.send_mail("sam", "Corner Shop", "Hi, do you open early on Saturdays?")
    bbs.send_mail("Corner Shop", "sam", "We open at 10 every day. See you then!")
    bbs.send_mail("alex", "Corner Shop", "Thanks for holding my order.")
    book = CustomerBook(folder / "bbs.sqlite")
    sam = book.add("Sam Lee", "555-0100", "!a1b2c3d4", actor=owner)
    book.approve(sam.id, owner, id_checked_21_plus=True)
    book.add("Alex Kim", "alex@example.com", actor=owner)
    staff.log("demo", "signed in", "demo mode")
    return folder, staff.get("demo")
