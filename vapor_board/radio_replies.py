"""Answer direct radio messages from approved customers. Off unless transmit is turned on.

Rules, all enforced here:
- Only direct messages to this shop's radio, as text. Channel broadcasts are never answered.
- Only from a node registered to an approved customer. Unknown or unapproved nodes get no reply.
- Messages that came through MQTT are ignored (no internet-to-radio bridge).
- Duplicates (the same packet heard twice) are answered once.
- Rate limits per customer and for the whole shop; anything over the limit gets no reply.
- Customers read only boards marked visible, and only posts inside their show window.
"""
import time
from collections import deque
from dataclasses import dataclass, field
from .bbs import BulletinBoard
from .customers import CustomerBook
from .meshwire import TEXT_MESSAGE_APP, BROADCAST, node_id, split_text

HELP = "Commands: boards · read N · msg <your message> · inbox · help"


@dataclass
class Outcome:
    """What happened to one received packet: replies to send and a note for the activity log."""
    replies: list = field(default_factory=list)
    note: str = ""  # '' means nothing worth logging (not for us, a duplicate, ...)
    customer: str = ""


class RadioReplies:
    def __init__(self, database, shop_name, mailbox, clock=time.monotonic, per_customer=3, per_shop=12, window=60.0):
        self.database = database
        self.shop_name = shop_name
        self.mailbox = mailbox
        self.clock = clock
        self.per_customer, self.per_shop, self.window = per_customer, per_shop, window
        self.my_node = None
        self._seen = deque(maxlen=256)
        self._sent = deque()  # (time, node) of recent replies

    def _allowed(self, node):
        now = self.clock()
        while self._sent and now - self._sent[0][0] >= self.window:
            self._sent.popleft()
        if len(self._sent) >= self.per_shop:
            return False
        return sum(1 for _t, n in self._sent if n == node) < self.per_customer

    def handle(self, event):
        """Decide what to do with one decoded FromRadio dict."""
        if event.get("variant") == "my_info":
            self.my_node = event.get("node_num") or None
            return Outcome()
        if event.get("variant") != "packet" or event.get("portnum") != TEXT_MESSAGE_APP or not event.get("text"):
            return Outcome()
        sender, destination = event.get("from", 0), event.get("to", 0)
        if self.my_node is None or destination != self.my_node or destination == BROADCAST or sender in (0, self.my_node):
            return Outcome()  # not a direct message to us
        if event.get("via_mqtt"):
            return Outcome(note=f"ignored a message from {node_id(sender)} that came through MQTT")
        key = (sender, event.get("id"))
        if event.get("id") and key in self._seen:
            return Outcome()
        self._seen.append(key)
        customer = CustomerBook(self.database).by_node(node_id(sender))
        if customer is None:
            return Outcome(note=f"no reply to unregistered radio {node_id(sender)}")
        if not customer.approved:
            return Outcome(note=f"no reply to {customer.name} ({customer.status_label.lower()})", customer=customer.name)
        if not self._allowed(sender):
            return Outcome(note=f"rate limit: no reply to {customer.name}", customer=customer.name)
        text, note = self._answer(customer, event["text"].strip())
        replies = split_text(text)
        self._sent.append((self.clock(), sender))
        return Outcome(replies=replies, note=note, customer=customer.name)

    # ---- commands ----------------------------------------------------------------------
    def _answer(self, customer, text):
        command, _space, rest = text.lstrip("/").partition(" ")
        command = command.lower()
        bbs = BulletinBoard(self.database)
        if command in ("help", "menu", "?", ""):
            return f"{self.shop_name}. {HELP}", "sent help"
        if command == "boards":
            boards = bbs.customer_boards()
            if not boards:
                return "No boards to read right now.", "listed boards"
            return " · ".join(f"{n} {b['name']}" for n, b in enumerate(boards, start=1)) + ". Send: read N", "listed boards"
        if command == "read":
            boards = bbs.customer_boards()
            try:
                board = boards[int(rest.strip()) - 1]
            except (ValueError, IndexError):
                return f"Send read and a board number from 1 to {len(boards)}." if boards else "No boards to read right now.", "read: bad board number"
            posts = bbs.customer_posts(board["id"], limit=3)
            if not posts:
                return f"{board['name']}: nothing posted.", f"read {board['name']}"
            body = " | ".join(" ".join(p["body"].split()) for p in posts)
            return f"{board['name']}: {body}", f"read {board['name']}"
        if command == "msg":
            message = rest.strip()
            if not message:
                return "Send msg and your message, e.g. msg Do you have size 10?", "msg: empty"
            bbs.send_mail(customer.name, self.mailbox, message[:1000])
            return f"Sent to {self.shop_name}. Staff will reply; send inbox to check.", "message to the shop"
        if command == "inbox":
            unread = [m for m in bbs.inbox(customer.name) if not m.get("read_at")][::-1][:3]
            if not unread:
                return "No new messages.", "checked inbox"
            for message in unread:
                bbs.mark_read(customer.name, message["id"])
            return " | ".join(f"{m['sender']}: {' '.join(m['body'].split())}" for m in unread), f"read {len(unread)} message(s)"
        return f"Unknown command. {HELP}", "unknown command"
