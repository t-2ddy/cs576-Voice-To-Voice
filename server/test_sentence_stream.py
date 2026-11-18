"""Run from server/: python -m unittest test_sentence_stream"""

import unittest

from sentence_stream import SentenceSplitter


def split(deltas: list[str]) -> list[str]:
    splitter = SentenceSplitter()
    out: list[str] = []
    for delta in deltas:
        out.extend(splitter.feed(delta))
    out.extend(splitter.flush())
    return out


def by_char(text: str) -> list[str]:
    return list(text)


class SentenceSplitterTest(unittest.TestCase):
    def test_two_sentences(self):
        text = "That spell is older than your kingdom. I learned it from Flamme."
        self.assertEqual(
            split(by_char(text)),
            ["That spell is older than your kingdom.", "I learned it from Flamme."],
        )

    def test_short_fragment_merges_with_next(self):
        text = "I see. Then we should leave before the sun sets."
        self.assertEqual(split(by_char(text)), [text])

    def test_short_reply_alone_is_flushed(self):
        self.assertEqual(split(["I see."]), ["I see."])

    def test_abbreviations_do_not_split(self):
        text = "Dr. Stark said e.g. this one works. It does."
        self.assertEqual(split(by_char(text)), ["Dr. Stark said e.g. this one works.", "It does."])

    def test_initials_do_not_split(self):
        text = "The book by J. R. Tolkien is long. Himmel liked it."
        self.assertEqual(split(by_char(text)), ["The book by J. R. Tolkien is long.", "Himmel liked it."])

    def test_question_exclaim_ellipsis_and_quotes(self):
        text = 'Really? That is "rare!" Hmm\u2026 well, maybe it is fine after all.'
        self.assertEqual(
            split(by_char(text)),
            ['Really? That is "rare!"', "Hmm\u2026 well, maybe it is fine after all."],
        )

    def test_decimal_numbers_do_not_split(self):
        text = "It took 3.5 days to get there. Too long."
        self.assertEqual(split(by_char(text)), ["It took 3.5 days to get there.", "Too long."])

    def test_sentence_emitted_before_stream_ends(self):
        splitter = SentenceSplitter()
        self.assertEqual(list(splitter.feed("Grimoires are heavy things. ")), ["Grimoires are heavy things."])
        self.assertEqual(list(splitter.feed("And")), [])
        self.assertEqual(list(splitter.flush()), ["And"])

    def test_empty(self):
        self.assertEqual(split([]), [])
        self.assertEqual(split(["   "]), [])


if __name__ == "__main__":
    unittest.main()
