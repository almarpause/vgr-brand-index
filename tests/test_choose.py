"""Unit tests for candidate selection — the 'never trust the first hit' rule.

No network: candidates are constructed by hand, standing in for what an
enriched wbsearchentities + wbgetentities round-trip would return.
"""

from __future__ import annotations

from vgr_brand_index.wikidata import Candidate, choose


def cand(qid, desc, rank, en=True, **titles):
    t = {}
    if en:
        t["en"] = titles.get("en", f"{qid}_article")
    t.update({k: v for k, v in titles.items() if k != "en"})
    return Candidate(qid=qid, label=qid, description=desc, rank=rank, titles=t, enriched=True)


def test_prefers_fashion_sense_with_en_over_top_hit():
    # Top hit is the wrong sense (a shoe *model*); the company ranks lower but
    # is the right entity and has an en article. The company must win.
    candidates = [
        cand("Q_model", "sneaker model", rank=0),
        cand("Q_company", "German multinational sportswear manufacturer", rank=1),
    ]
    best, flag = choose(candidates, expect=[])
    assert best.qid == "Q_company"
    assert flag == ""


def test_expect_keywords_disambiguate_homonym():
    # 'Celine': the singer is the top hit; the fashion house ranks lower.
    candidates = [
        cand("Q_singer", "French Canadian singer", rank=0),
        cand("Q_house", "French luxury fashion house", rank=1),
    ]
    best, flag = choose(candidates, expect=["fashion", "luxury", "house"])
    assert best.qid == "Q_house"
    assert flag == ""


def test_prefers_en_article_among_matching_senses():
    # Two fashion items match; only the second has an English article. The en
    # one wins because en pageviews are the index backbone.
    candidates = [
        cand("Q_stub", "French fashion brand", rank=0, en=False, fr="Marque"),
        cand("Q_full", "French fashion brand", rank=1, en=True),
    ]
    best, flag = choose(candidates, expect=[])
    assert best.qid == "Q_full"
    assert flag == ""


def test_flags_when_no_en_article_anywhere():
    candidates = [cand("Q_fr", "French fashion brand", rank=0, en=False, fr="Marque")]
    best, flag = choose(candidates, expect=[])
    assert best.qid == "Q_fr"
    assert flag == "NO_EN_ARTICLE"


def test_flags_when_expect_never_matches():
    candidates = [cand("Q_wrong", "commune in France", rank=0)]
    best, flag = choose(candidates, expect=["fashion", "clothing"])
    assert best.qid == "Q_wrong"
    assert flag == "EXPECT_NOT_MATCHED"


def test_no_candidates():
    best, flag = choose([], expect=[])
    assert best is None
    assert flag == "NO_CANDIDATES"
