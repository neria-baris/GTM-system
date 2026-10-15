"""Deal reconstruction from context: link unlinked sources by distinctive anchors.

Soft-to-hard evidence rarely carries clean identifiers. Two sources are linked
when they share at least two distinctive anchors (rare terms or phrases, an
exact annual amount), at least one of which is not a person's name. A shared
name alone never links; generic GTM vocabulary is filtered by document
frequency. Every link records its score and shared anchors, so each
reconstruction is reproducible and reviewable.
"""
from __future__ import annotations

from collections import Counter, defaultdict
import math
import re
from typing import Any, Iterable

from src.ledger.store import stable_id
from src.settings import seller_names

from .signals import AI_ANNOTATION, TARGET_STATEMENT

VERSION = "reconstruction_1.0.0"
WORD = re.compile(r"[a-z][a-z0-9\-]{2,}")
MONEY = re.compile(r"(?P<cur>[$€£])\s*(?P<num>\d+(?:[.,]\d+)?)\s*(?P<scale>[kKmM])?(?P<tail>[^,;.\n]{0,14})")
NAME = re.compile(r"\b([A-Z][a-z]+(?:[- ][A-Z][a-z]+)?)(?:'s team| says| has gone| open to)|\bMet ([A-Z][a-z]+)\b|\bw/ ([A-Z][a-z]+)'s\b")
STOP = frozenset("""
the and for with that this from have has their they them our your are was were will would could into than then
when what which while also only just more most very some such each other about after before over under again
pilot pilots scope budget rollout maybe works work next send team says costs real money keen wants want result results
data signed commercial customer improvement shadow mode zero violations never below above every must one two three
first second weeks week months month year years term verbal yes paid sow being drafted drafting integration setup
intro book scoping deep dive engineers their hard constraint constraints success kpis kpi violation
priority closed lost reply emails chase discussed acv annual fee pricing approved procurement legal contract
""".split()) | frozenset(w for name in seller_names() for w in name.casefold().split())
CURRENCY = {"$": "USD", "€": "EUR", "£": "GBP"}


def money_mentions(text: str) -> list[dict[str, Any]]:
    """Amounts with currency, period and contract-kind hint; targets/AI annotations excluded."""
    if not text or TARGET_STATEMENT.search(text):
        return []
    out = []
    for m in MONEY.finditer(text):
        amount = float(m.group("num").replace(",", "")) * {"k": 1e3, "m": 1e6}.get((m.group("scale") or "").lower(), 1)
        if amount < 1000:
            continue
        tail, before = m.group("tail"), text[max(0, m.start() - 30):m.start()]
        annual = bool(re.search(r"/yr|per year|annual|\bACV\b", tail + " " + before, re.I))
        pilot = bool(re.search(r"\bpilot\b", before, re.I)) and not re.search(r"rollout|commercial", before[-15:], re.I)
        out.append({"amount": round(amount, 2), "currency": CURRENCY[m.group("cur")], "annual": annual,
                    "kind": "pilot" if pilot and not annual else "commercial" if annual or re.search(r"rollout|commercial|ACV", before, re.I)
                    else "unknown", "text": m.group(0).strip(), "ai_annotation": bool(AI_ANNOTATION.search(text))})
    return out


def anchors(texts: Iterable[str]) -> dict[str, set[str]]:
    joined = "\n".join(texts)
    # AI annotations corroborate amounts/dates elsewhere; they never supply topic anchors.
    clean = "\n".join(t for t in joined.splitlines() if not TARGET_STATEMENT.search(t) and not AI_ANNOTATION.search(t))
    lower = clean.lower()
    words = [w for w in WORD.findall(lower)]
    terms = {w for w in words if w not in STOP and not w.isdigit()}
    bigrams = {f"{a} {b}" for a, b in zip(words, words[1:]) if not (a in STOP and b in STOP)}
    names = {next(g for g in m.groups() if g).lower() for m in NAME.finditer(clean)}
    amounts = {f"{m['currency']}{int(m['amount'])}{'/yr' if m['annual'] else ''}" for m in money_mentions(clean)
               if m["annual"] or m["kind"] == "commercial"}
    name_tokens = {t for n in names for t in WORD.findall(n)}
    # Phrases built around a contact's name are name evidence, not topic evidence.
    bigrams = {b for b in bigrams if not set(b.split()) & name_tokens}
    return {"terms": terms - names - name_tokens, "bigrams": bigrams, "names": names, "amounts": amounts}


def _norm(text: str) -> str:
    return " ".join(WORD.findall(text.lower()))


def reconstruct(sources: dict[str, list[str]], seeds: dict[str, set[str]] | None = None,
                *, min_score: float = 4.0, accounts: dict[str, str] | None = None) -> dict[str, Any]:
    """Cluster source groups. `sources`: group -> texts. `seeds`: opportunity_id -> groups already linked.

    Rules (all must hold for a link):
    * sentences repeated verbatim in >= 3 sources are templates and give no anchors;
    * at least one shared rare anchor (phrase or term in <= 3 sources), plus a second shared anchor
      (rare, or an exact amount in <= 6 sources);
    * when both sides name contacts, at least one name is shared (different contacts suggest different accounts);
    * two seeded opportunities are never merged;
    * sources resolved to the same account belong to one deal unless that account has several seeded
      opportunities; sources resolved to different accounts never link.
    """
    seeds = seeds or {}
    accounts = {g: a for g, a in (accounts or {}).items() if a and g in sources}
    sentence_df = Counter(s for texts in sources.values() for s in {_norm(t) for t in texts if _norm(t)})
    templates = {s for s, c in sentence_df.items() if c >= 3}
    profile = {}
    for g, texts in sources.items():
        own = [t for t in texts if _norm(t) not in templates]
        a = anchors(own)
        a["amounts"] = anchors(texts)["amounts"]
        profile[g] = a
    n = max(1, len(profile))
    df: Counter = Counter()
    for pr in profile.values():
        df.update({(k, x) for k, values in pr.items() for x in values})

    def weight(kind: str, anchor: str) -> float:
        d = df[(kind, anchor)]
        limit = 8 if kind == "amounts" else 3
        if d > limit or (kind == "terms" and len(anchor) < 3):
            return 0.0
        return math.log((n + 1) / d) * {"amounts": 1.0, "bigrams": 1.0, "terms": 0.8, "names": 0.5}[kind]

    def score(a: dict[str, set[str]], b: dict[str, set[str]]) -> tuple[float, list[str]]:
        if a["names"] and b["names"] and not a["names"] & b["names"]:
            return 0.0, []
        shared, total, rare, other = [], 0.0, 0, 0
        for kind in ("bigrams", "terms", "amounts", "names"):
            for x in sorted(a[kind] & b[kind]):
                w = weight(kind, x)
                if not w:
                    continue
                shared.append(f"{kind[:-1]}:{x}")
                total += w
                if kind in ("bigrams", "terms"):
                    rare += 1
                elif kind == "amounts":
                    other += 1
        if rare < 1 or rare + other < 2 or total < min_score:
            return 0.0, []
        return total, shared

    parent = {g: g for g in profile}
    links: dict[str, list[dict[str, Any]]] = defaultdict(list)
    # A source linked to several opportunities (one note covering two scopes) is attributed to one
    # of them for context linking (last in seed order); it never merges the opportunities.
    seed_of = {g: oid for oid, gs in seeds.items() for g in gs if g in profile}

    def find(g: str) -> str:
        while parent[g] != g:
            parent[g] = parent[parent[g]]
            g = parent[g]
        return g

    def seeds_in(root: str) -> set[str]:
        return {seed_of[g] for g in profile if g in seed_of and find(g) == root}

    for oid, gs in sorted(seeds.items()):
        gs = sorted(g for g in gs if g in profile and seed_of[g] == oid)
        for g in gs[1:]:
            parent[find(g)] = find(gs[0])
    groups = sorted(profile)
    edges = []
    for i, g in enumerate(groups):
        for h in groups[i + 1:]:
            s, shared = score(profile[g], profile[h])
            if s:
                edges.append((s, g, h, shared))
    def members_of(root: str) -> list[str]:
        return [g for g in profile if find(g) == root]

    def names_of(root: str) -> set[str]:
        return set().union(*(profile[g]["names"] for g in members_of(root)))

    def accounts_of(root: str) -> set[str]:
        return {accounts[g] for g in members_of(root) if g in accounts}

    def mergeable(ra: str, rb: str) -> bool:
        sa, sb = seeds_in(ra), seeds_in(rb)
        na, nb = names_of(ra), names_of(rb)
        aa, ab = accounts_of(ra), accounts_of(rb)
        if aa and ab:
            return aa == ab and not (sa and sb and sa != sb)
        return not (sa and sb and sa != sb) and not (na and nb and not na & nb)

    # Same customer, one deal: group an account's sources first, unless it has several seeded scopes.
    by_account: dict[str, list[str]] = defaultdict(list)
    for g in sorted(accounts):
        by_account[accounts[g]].append(g)
    for account, members in sorted(by_account.items()):
        owners = {seed_of[g] for g in members if g in seed_of}
        if len(owners) > 1:
            continue
        for g in members[1:]:
            ra, rb = find(members[0]), find(g)
            if ra != rb:
                parent[rb] = ra
                links[ra].append({"group": g, "with": members[0], "score": None,
                                  "shared_anchors": [f"account:{account}"]})

    for s, g, h, shared in sorted(edges, key=lambda e: (-e[0], e[1], e[2])):
        rg, rh = find(g), find(h)
        if rg == rh or not mergeable(rg, rh):
            continue
        parent[rh] = rg
        links[rg].append({"group": h, "with": g, "score": round(s, 2), "shared_anchors": shared[:6]})
    # Second pass: a single source may match a reconstructed deal as a whole.
    for g in groups:
        if len(members_of(find(g))) > 1 or g in seed_of:
            continue
        best = None
        for root in sorted({find(x) for x in profile if len(members_of(find(x))) > 1 or x in seed_of}):
            union = {k: set().union(*(profile[x][k] for x in members_of(root))) for k in ("terms", "bigrams", "names", "amounts")}
            s, shared = score(profile[g], union)
            if s and mergeable(root, find(g)) and (best is None or s > best[0]):
                best = (s, root, shared)
        if best:
            parent[find(g)] = best[1]
            links[best[1]].append({"group": g, "with": "cluster", "score": round(best[0], 2), "shared_anchors": best[2][:6]})
    components: dict[str, list[str]] = defaultdict(list)
    for g in groups:
        components[find(g)].append(g)
    all_links = [l for ls in links.values() for l in ls]
    clusters = []
    for root, members in sorted(components.items(), key=lambda kv: kv[1]):
        owners = seeds_in(root)
        if len(members) < 2 and not owners:
            continue
        member_set = set(members)
        union = {k: set().union(*(profile[g][k] for g in members)) for k in ("terms", "bigrams", "names", "amounts")}
        clusters.append({"cluster_id": stable_id("reconstructed_cluster", ",".join(members)),
                         "opportunity_id": next(iter(owners)) if len(owners) == 1 else None,
                         "groups": members, "accounts": sorted({accounts[g] for g in members if g in accounts}),
                         "links": [l for l in all_links if l["group"] in member_set and (l["with"] in member_set or l["with"] == "cluster")],
                         "anchors": sorted(f"{k[:-1]}:{a}" for k, v in union.items() for a in v if weight(k, a))[:12]})
    return {"version": VERSION, "clusters": clusters,
            "group_to_cluster": {g: c["cluster_id"] for c in clusters for g in c["groups"]},
            "templates_excluded": len(templates), "min_score": min_score,
            "accounts_resolved": len(accounts),
            "rule": "same resolved account forms one deal (unless several seeded scopes); otherwise link when >= 1 rare "
                    "shared phrase/term (<= 3 sources) plus a second shared rare anchor or exact amount; different "
                    "accounts or conflicting named contacts never link; two seeded opportunities never merge"}


GENERIC_TITLE = re.compile(r"\b(?:" + "".join(re.escape(n) + "|" for n in seller_names())
                           + r"call|sync|follow-?up|followup|meeting|intro|w/?|with|and|re)\b|<>|[|:]", re.I)


def resolve_accounts(titles: dict[str, str], companies: dict[str, str],
                     contacts: dict[str, list[str]] | None = None) -> dict[str, str]:
    """Map source titles to account ids conservatively.

    `companies`: account_id -> company name; `contacts`: contact full name -> account ids.
    A title resolves when it contains a full company name, a company's first word that no
    other company shares, the company's initials (unique, 2-4 letters, written in capitals),
    or a contact's first or full name that identifies exactly one contact with one account.
    """
    contacts = contacts or {}
    words = lambda t: re.findall(r"[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ'\-]+", t)
    first = Counter(words(n)[0].casefold() for n in companies.values() if words(n))
    initials = Counter("".join(w[0] for w in words(n)).upper() for n in companies.values() if len(words(n)) > 1)
    by_first_name: dict[str, set[str]] = defaultdict(set)
    for name, ids in contacts.items():
        if len(set(ids)) == 1 and words(name):
            by_first_name[words(name)[0].casefold()].add(next(iter(ids)))
            by_first_name[name.casefold()].add(next(iter(ids)))
    out = {}
    for group, title in titles.items():
        if not title:
            continue
        low, hits = title.casefold(), set()
        for aid, name in companies.items():
            w = words(name)
            if not w:
                continue
            full = name.casefold() in low
            lead = first[w[0].casefold()] == 1 and len(w[0]) >= 4 and re.search(r"(?<![\w])" + re.escape(w[0].casefold()) + r"(?![\w])", low)
            abbr = len(w) > 1 and initials["".join(x[0] for x in w).upper()] == 1 and \
                re.search(r"(?<![\w])" + "".join(x[0] for x in w).upper() + r"(?![\w])", title)
            if full or lead or abbr:
                hits.add(aid)
        if not hits:
            rest = [x.casefold() for x in words(GENERIC_TITLE.sub(" ", title))]
            for key in [" ".join(rest)] + rest:
                ids = by_first_name.get(key) or set()
                if len(ids) == 1:
                    hits = set(ids)
                    break
        if len(hits) == 1:
            out[group] = next(iter(hits))
    return out


SIGNED_ON = re.compile(r"\bsigned (?:on )?(\d{1,2}) (jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\b", re.I)
MONTHS = {m: i for i, m in enumerate("jan feb mar apr may jun jul aug sep oct nov dec".split(), 1)}
ISO = re.compile(r"\b(20\d\d)-(\d\d)-(\d\d)\b")


def signature_dates(text: str, context_date: str | None = None) -> list[str]:
    """Explicit 'Signed 16 May' style dates; the year comes from an ISO date in the same text or context."""
    out = []
    for m in SIGNED_ON.finditer(text or ""):
        iso = ISO.search(text) or (ISO.search(context_date) if context_date else None)
        if not iso:
            continue
        year, ref_month = int(iso.group(1)), int(iso.group(2))
        month = MONTHS[m.group(2).lower()[:3]]
        year -= 1 if month > ref_month + 1 else 0
        out.append(f"{year:04d}-{month:02d}-{int(m.group(1)):02d}")
    return out
