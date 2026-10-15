"""Account anchors: conservative title resolution and same-customer grouping."""
from src.belief.reconstruction import reconstruct, resolve_accounts

COMPANIES = {"a1": "Coldharbour Pharma", "a2": "Westra Trading", "a3": "Rhona Transport", "a4": "Mosel Fracht"}
CONTACTS = {"Juhani Korhonen": ["a1"], "Juhani Laine": ["a2"], "Magdalena Wiśniewski": ["a2"]}


def test_titles_resolve_by_name_unique_first_word_initials_and_unique_contact():
    got = resolve_accounts({"n1": "Coldharbour", "n2": "WT", "n3": "Call w/ Juhani", "n4": "Call w Magdalena",
                            "n5": "Rhona followup", "n6": "Mosel Fracht <> Vendora", "n7": "RT", "n8": "Random"},
                           COMPANIES, CONTACTS)
    assert got == {"n1": "a1", "n2": "a2", "n4": "a2", "n5": "a3", "n6": "a4", "n7": "a3"}


def test_ambiguous_titles_stay_unresolved():
    companies = {"a": "Nova Grid", "b": "Nova Mobile"}
    assert resolve_accounts({"x": "Nova sync", "y": "NG"}, companies) == {"y": "a"}


def test_same_account_forms_one_deal_and_different_accounts_never_link():
    sources = {"s1": ["SIGNED. €580k/yr, 2-yr term"], "s2": ["Pilot scope: one distribution centre"], "s3": ["seasonal vaccines"],
               "t1": ["Pilot scope: one distribution centre"], **{f"f{i}": [f"filler {i} item{i}"] for i in range(30)}}
    accounts = {"s1": "Coldharbour", "s2": "Coldharbour", "s3": "Coldharbour", "t1": "Other Co"}
    clusters = reconstruct(sources, accounts=accounts)["clusters"]
    frost = next(c for c in clusters if "s1" in c["groups"])
    assert set(frost["groups"]) == {"s1", "s2", "s3"} and frost["accounts"] == ["Coldharbour"]
    assert all("t1" not in c["groups"] or c["groups"] == ["t1"] for c in clusters)


def test_account_with_two_seeded_scopes_is_not_pre_grouped():
    sources = {"a": ["Scope alpha line"], "b": ["Scope beta line"], "c": ["Unrelated"], **{f"f{i}": [f"x{i}"] for i in range(20)}}
    accounts = {"a": "Acme", "b": "Acme", "c": "Acme"}
    clusters = reconstruct(sources, {"o1": {"a"}, "o2": {"b"}}, accounts=accounts)["clusters"]
    owners = {c["opportunity_id"]: set(c["groups"]) for c in clusters if c["opportunity_id"]}
    assert owners["o1"].isdisjoint(owners["o2"])
