"""Drives the real Tk Messages page; skipped where no display is available."""
from unittest import mock
from desktop_harness import DesktopHarness, walk
from vapor_board import desktop
from vapor_board.bbs import BulletinBoard


class DesktopMessagesUiTests(DesktopHarness):
    def setUp(self):
        super().setUp()
        self.bbs = BulletinBoard(self.database)
        self.bbs.send_mail("alice", "Operator", "Can you hold the blue one?\nThanks")
        self.bbs.send_mail("bob", "Operator", "Running late today")
        self.bbs.send_mail("alice", "carol", "Private to carol")

    def widgets(self, root):
        page = self.page(root, "Messages")
        mail_list = self.lists(root, "Messages")[0]
        reader, editor = self.texts(root, "Messages")
        to_entry = next(w for w in walk(page) if w.winfo_class() == "TEntry")
        return mail_list, reader, editor, to_entry

    def tab(self, root, name):
        """Inbox/Sent/Threads segment; Inbox carries its unread count in the label."""
        return next(b for text, b in self.buttons(root, "Messages").items() if text.split("  ")[0] == name)

    def open_inbox(self, root):
        self.tab(root, "Inbox").invoke()
        root.update()

    @staticmethod
    def badge(root):
        badge = next(w for w in walk(root) if w.winfo_name() == "messages_badge")
        return badge.cget("text") if badge.winfo_manager() else None

    def test_delete_a_conversation_and_a_message(self):
        def scenario(root):
            mail_list, _reader, _editor, _to = self.widgets(root)
            self.pick(root, mail_list, 0)  # newest conversation: bob
            with mock.patch.object(desktop.messagebox, "askyesno", return_value=False):
                self.buttons(root, "Messages")["Delete"].invoke()
            self.assertEqual(len(self.bbs.inbox("Operator")), 2)
            with mock.patch.object(desktop.messagebox, "askyesno", return_value=True):
                self.buttons(root, "Messages")["Delete"].invoke()
            self.assertEqual([m["sender"] for m in self.bbs.inbox("Operator")], ["alice"])
            self.open_inbox(root)
            self.pick(root, mail_list, 0)
            with mock.patch.object(desktop.messagebox, "askyesno", return_value=True):
                self.buttons(root, "Messages")["Delete"].invoke()
            self.assertEqual(self.bbs.inbox("Operator"), [])
            self.assert_page_fits(root, "Messages")

        self.run_desktop(scenario, page="Messages")
        self.assertEqual(len(self.bbs.inbox("carol")), 1)  # someone else's mail is untouched

    def test_inbox_shows_only_the_operators_mail_and_marks_it_read(self):
        def scenario(root):
            mail_list, reader, _editor, _to = self.widgets(root)
            self.open_inbox(root)
            self.assertEqual(self.badge(root), "2")
            self.assertEqual(self.rows(mail_list), ("●  bob — Running late today", "●  alice — Can you hold the blue one?"))
            self.assertEqual(mail_list.item("1", "tags"), ("strong",))
            self.pick(root, mail_list, 1)
            self.assertEqual(reader.get("1.0", "end-1c"), "Can you hold the blue one?\nThanks")
            titles = self.card_titles(root, self.page(root, "Messages"))
            self.assertIn("From alice", titles)
            self.assertEqual(self.rows(mail_list)[1], "    alice — Can you hold the blue one?")
            self.assertEqual(mail_list.selection(), ("1",))  # stays selected after the list refreshes
            self.assertEqual(self.badge(root), "1")
            self.assertEqual(self.bbs.unread_count("Operator"), 1)
            self.assertEqual(self.bbs.unread_count("carol"), 1)

        self.run_desktop(scenario, page="Messages")

    def test_reply_sends_as_the_operator_and_shows_in_sent(self):
        def scenario(root):
            mail_list, reader, editor, to_entry = self.widgets(root)
            self.open_inbox(root)
            buttons = self.buttons(root, "Messages")
            self.assertFalse(self.enabled(buttons["Reply"]))
            self.pick(root, mail_list, 1)
            self.assertTrue(self.enabled(buttons["Reply"]))
            buttons["Reply"].invoke()
            self.assertEqual(to_entry.get(), "alice")
            self.assertIn("Reply to alice", self.card_titles(root, self.page(root, "Messages")))
            editor.insert("1.0", "Held at the counter")
            buttons["Send message"].invoke()
            self.assertEqual(to_entry.get(), "")
            self.assertEqual(editor.get("1.0", "end-1c"), "")
            self.assertEqual(self.toast(root), "Message sent: Delivered to alice's inbox on this Mac.")
            self.assertEqual(self.rows(mail_list), ("To alice — Held at the counter",))
            self.pick(root, mail_list, 0)
            self.assertIn("To alice", self.card_titles(root, self.page(root, "Messages")))
            self.assertFalse(self.enabled(buttons["Reply"]))  # replies come from the inbox

        self.run_desktop(scenario, page="Messages")
        sent = self.bbs.sent("Operator")
        self.assertEqual([(m["sender"], m["recipient"], m["body"]) for m in sent], [("Operator", "alice", "Held at the counter")])
        self.assertEqual(self.bbs.inbox("alice")[0]["body"], "Held at the counter")

    def test_invalid_send_is_refused_and_the_draft_kept(self):
        def scenario(root):
            _list, _reader, editor, _to = self.widgets(root)
            editor.insert("1.0", "No recipient")
            self.buttons(root, "Messages")["Send message"].invoke()
            self.assertTrue(self.toast(root).startswith("Message not sent: "))
            self.assertEqual(editor.get("1.0", "end-1c"), "No recipient")

        self.run_desktop(scenario, page="Messages")
        self.assertEqual(self.bbs.sent("Operator"), [])

    def test_no_database_means_empty_inbox_without_creating_one(self):
        self.database.unlink()

        def scenario(root):
            mail_list, reader, _editor, _to = self.widgets(root)
            self.assertEqual(self.rows(mail_list), ())
            self.assertEqual(self.placeholder(mail_list), "No conversations yet")
            self.assertEqual(reader.get("1.0", "end-1c"), "No conversations yet.")
            self.open_inbox(root)
            self.assertEqual(self.placeholder(mail_list), "No messages yet")
            self.assertIsNone(self.badge(root))

        self.run_desktop(scenario, page="Messages")
        self.assertFalse(self.database.exists())

    def test_threads_group_mail_by_person_and_open_the_whole_conversation(self):
        self.bbs.send_mail("Operator", "alice", "Held at the counter")
        self.bbs.send_mail("alice", "Operator", "Thanks!")

        def scenario(root):
            mail_list, reader, _editor, _to = self.widgets(root)
            self.assertEqual(self.tab(root, "Threads").cget("style"), "SegmentActive.TButton")
            self.assertEqual(self.rows(mail_list), ("●  alice (2) — Thanks!", "●  bob (1) — Running late today"))
            self.assertEqual(self.badge(root), "3")
            self.pick(root, mail_list, 0)
            lines = reader.get("1.0", "end-1c").split("\n")
            self.assertEqual([lines[0].split("  ·  ")[0], lines[1], lines[2], lines[4].split("  ·  ")[0], lines[5],
                              lines[7].split("  ·  ")[0], lines[8]],
                             ["alice", "Can you hold the blue one?", "Thanks", "You", "Held at the counter", "alice", "Thanks!"])
            titles = self.card_titles(root, self.page(root, "Messages"))
            self.assertIn("Conversation with alice", titles)
            self.assertEqual(self.rows(mail_list)[0], "    alice — Thanks!")
            self.assertEqual(mail_list.selection(), ("0",))
            self.assertEqual(self.badge(root), "1")
            self.assertTrue(self.enabled(self.buttons(root, "Messages")["Reply"]))

        self.run_desktop(scenario, page="Messages")
        self.assertEqual(self.bbs.unread_count("Operator"), 1)
        self.assertEqual(self.bbs.unread_count("carol"), 1)  # other mailboxes untouched

    def test_replying_in_a_thread_keeps_you_in_the_conversation(self):
        def scenario(root):
            mail_list, reader, editor, to_entry = self.widgets(root)
            self.pick(root, mail_list, 1)  # alice, the older thread
            self.buttons(root, "Messages")["Reply"].invoke()
            self.assertEqual(to_entry.get(), "alice")
            editor.insert("1.0", "Held for you")
            self.buttons(root, "Messages")["Send message"].invoke()
            self.assertEqual(self.tab(root, "Threads").cget("style"), "SegmentActive.TButton")
            self.assertEqual(self.rows(mail_list)[0], "    alice — You: Held for you")
            self.assertEqual(mail_list.selection(), ("0",))
            self.assertTrue(reader.get("1.0", "end-1c").endswith("\nHeld for you"))
            self.assertEqual(self.toast(root), "Message sent: Delivered to alice's inbox on this Mac.")

        self.run_desktop(scenario, page="Messages")
        self.assertEqual(self.bbs.inbox("alice")[0]["body"], "Held for you")

    def test_every_messages_control_fits_the_default_window(self):
        self.run_desktop(lambda root: self.assert_page_fits(root, "Messages"), page="Messages")


if __name__ == "__main__":
    import unittest
    unittest.main()
