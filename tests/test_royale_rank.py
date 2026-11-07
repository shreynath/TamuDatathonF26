import unittest

import duckdb

from domains.royale.report import holm, rank_one_is_lowest


class RankDirectionTests(unittest.TestCase):
    def test_rank_one_is_the_lowest_value(self):
        ranks = rank_one_is_lowest([("A", 10.0), ("B", 50.0), ("C", 5.0)])
        self.assertEqual(ranks["C"], 1)
        self.assertEqual(ranks["A"], 2)
        self.assertEqual(ranks["B"], 3)
        rows = dict(duckdb.sql("""
            SELECT id, RANK() OVER (ORDER BY win) AS rank
            FROM (VALUES ('A', 10), ('B', 50), ('C', 5)) t(id, win)
        """).fetchall())
        self.assertEqual(rows["C"], 1)

    def test_holm_does_not_shrink_a_p_value(self):
        adjusted = holm({"a": 0.01, "b": 0.02, "c": 0.04})
        self.assertGreaterEqual(adjusted["a"], 0.01)
        self.assertLessEqual(max(adjusted.values()), 1)


if __name__ == "__main__":
    unittest.main()
