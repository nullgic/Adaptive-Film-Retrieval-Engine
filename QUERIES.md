# Query log

Ten queries run against the full corpus, recorded as they came out. Four work,
four fail, one is partial, one is degenerate by design.

This is not an evaluation. There is no metric here and no ground truth — the
Judge layer does not exist yet. It is a record of what the retriever actually
does before anything is tuned, so that later claims of improvement have
something concrete to be measured against.

**Run:** 45,433 documents, `BAAI/bge-small-en-v1.5`, RRF K=60, depth 50 per arm.

**How to read it:** `lex` and `sem` are the document's rank within each arm, and
`-` means that arm did not return it at all. `rrf` is the fused score. A result
that both arms found outranks one that only a single arm found — that is the
whole point of the fusion, and it is also the cause of two of the failures.

---

## 1. `space opera with rebels` — works

Tests whether the semantic arm can match a paraphrase. This exact phrase appears
in no document in the corpus.

| | rrf | lex | sem | title |
|---|---|---|---|---|
| 1 | 0.03226 | 2 | 2 | Rogue One: A Star Wars Story (2016) |
| 2 | 0.03110 | 1 | 8 | Mobile Suit Gundam: Char's Counterattack (1988) |
| 3 | 0.03012 | 4 | 9 | Return of the Jedi (1983) |
| 4 | 0.02921 | 3 | 15 | The Empire Strikes Back (1980) |
| 5 | 0.01639 | - | 1 | Star Command (1996) |

The lexical arm found only 4 documents. The semantic arm carried this. Gundam at
2 is arguably the most interesting hit — a space opera about a rebellion that
shares no vocabulary with Star Wars.

---

## 2. `toy comes to life` — works

Tests D-005, which put keywords into the embedding document. This is a literal
TMDB keyword string, so both arms should fire.

| | rrf | lex | sem | title |
|---|---|---|---|---|
| 1 | 0.03132 | 1 | 7 | Toy Story 3 (2010) |
| 2 | 0.03083 | 2 | 8 | Child's Play 3 (1991) |
| 3 | 0.03062 | 9 | 2 | Toy Story (1995) |
| 4 | 0.02921 | 3 | 15 | The Indian in the Cupboard (1995) |
| 5 | 0.02817 | 10 | 12 | Ted (2012) |

Both arms fired as predicted, 26 lexical candidates and 50 semantic. Child's Play
at 2 is correct and slightly funny — a toy that comes to life is exactly what
Chucky is.

---

## 3. `Tom Hanks` — **fails**

Tests D-004, which kept cast names out of the embedding document on the grounds
that dense models handle proper nouns poorly.

| | rrf | lex | sem | title |
|---|---|---|---|---|
| 1 | 0.03126 | 3 | 5 | From the Earth to the Moon (1998) |
| 2 | 0.02991 | 1 | 14 | The Man with One Red Shoe (1985) |
| **3** | **0.02604** | **7** | **30** | **Tom Sawyer (2000)** |
| 4 | 0.01639 | - | 1 | Blue Sky (1994) |
| 5 | 0.01613 | 2 | - | Bachelor Party (1984) |

D-004 is confirmed: the semantic arm returned *Blue Sky*, *Hank: 5 Years from the
Brink*, *The Power and the Glory* — noise.

But the fusion is worse than the lexical arm alone. Lexical by itself ranked four
genuine Hanks films in the top four. Fused, *Tom Sawyer* — which he is not in —
lands at 3, above *Bachelor Party*, because both arms weakly agree on the token
"Tom": `1/67 + 1/90 = 0.0260` beats `1/62 = 0.0161`.

RRF rewards agreement over strength. Two mediocre ranks outscore one strong rank.
This is the documented cost in D-013 showing up on a real query, and it is the
clearest target for the reranker to fix once there is a metric to prove it.

---

## 4. `Bix` — works

Tests D-011, which encoded the 235 documents that are nothing but a title. *Bix*
is one of them: its entire `search_text` is three characters.

| | rrf | lex | sem | title |
|---|---|---|---|---|
| 1 | 0.03279 | 1 | 1 | Bix (1991) |
| 2 | 0.01613 | 2 | - | Life Without Dick (2002) |
| 3 | 0.01613 | - | 2 | O-Bi, O-Ba: The End of Civilization (1985) |
| 4 | 0.01587 | 3 | - | Voyage to the Prehistoric Planet (1965) |
| 5 | 0.01587 | - | 3 | Bipedalism (2005) |

Rank 1 in **both** arms — the strongest possible RRF score. A three-character
document is perfectly retrievable by its own title. This does not prove thin
documents are harmless; it proves they are findable. Whether their vectors
pollute *other* queries is the open question D-011 defers to the Judge layer.

---

## 5. `heist gone wrong` — works

Plot paraphrase with no single keyword to anchor on.

| | rrf | lex | sem | title |
|---|---|---|---|---|
| 1 | 0.03058 | 3 | 8 | Reservoir Dogs (1992) |
| 2 | 0.01639 | 1 | - | Drive (2011) |
| 3 | 0.01639 | - | 1 | Foolproof (2003) |
| 4 | 0.01613 | 2 | - | Shimmer Lake (2017) |
| 5 | 0.01613 | - | 2 | Blood and Wine (1996) |

*Reservoir Dogs* is the correct answer and it won by being the only film either
arm ranked well. Only 3 lexical candidates, so this is mostly the semantic arm
again. Note how thin the fusion is below rank 1 — everything from 2 down was
found by exactly one arm, and the scores are nearly tied.

---

## 6. `lonely robot in space` — **fails**

Abstract semantic query with no lexical anchor at all.

| | rrf | lex | sem | title |
|---|---|---|---|---|
| 1 | 0.01639 | - | 1 | Love (2011) |
| 2 | 0.01613 | - | 2 | Hal (2013) |
| 3 | 0.01587 | - | 3 | Target Earth (1954) |
| 4 | 0.01562 | - | 4 | Lone Wolves (2016) |
| 5 | 0.01538 | - | 5 | The Stranger: Summoned by Shadows (1991) |

**Zero lexical candidates.** No document contains enough of those terms to match
the tsquery, so the lexical arm contributed nothing and the fused list is just
the semantic ranking copied out.

The obvious answer — *WALL·E* — is not in the top 5. *Hal* at 2 looks like a hit
but is a documentary about Hal Ashby, not HAL 9000. This is the failure mode
where fusion cannot help: when one arm returns nothing, RRF degenerates into
whatever the other arm said, with no second opinion available.

---

## 7. `film about grief` — partial

Abstract concept, weak lexical signal.

| | rrf | lex | sem | title |
|---|---|---|---|---|
| 1 | 0.03083 | 2 | 8 | Boy Interrupted (2009) |
| 2 | 0.02921 | 15 | 3 | A Killer Among Friends (1992) |
| 3 | 0.01639 | 1 | - | Resurrecting Hassan (2017) |
| 4 | 0.01639 | - | 1 | The Left-Handed Woman (1978) |
| 5 | 0.01613 | - | 2 | A Mother Should Be Loved (1934) |

*Boy Interrupted* is a documentary about a family after a son's suicide — a
genuinely good answer. *A Killer Among Friends* at 2 is not about grief, and it
is there for the same reason *Tom Sawyer* was: mediocre agreement between two
arms beating strong single-arm evidence.

The word "film" in the query is also doing damage, matching documents that
describe themselves as films rather than filtering to the subject.

---

## 8. `Speilberg` (misspelled) — **fails**

Tests whether either arm survives a typo in a proper noun.

| | rrf | lex | sem | title |
|---|---|---|---|---|
| 1 | 0.01639 | 1 | - | A Guy Named Joe (1944) |
| 2 | 0.01639 | - | 1 | Ein Schnitzel für drei (2010) |
| 3 | 0.01613 | - | 2 | The Moon and Sixpence (1942) |
| 4 | 0.01587 | - | 3 | Pappa ante Portas (1991) |
| 5 | 0.01562 | - | 4 | 1. Mai – Helden bei der Arbeit (2008) |

Both arms fail, for different reasons worth separating.

The **lexical** arm found exactly one document. Postgres full-text search does
*stemming*, not fuzzy matching — it reduces words to a root form, so `running`
matches `run`, but `Speilberg` and `Spielberg` are simply different tokens with
no relationship. Nothing in `ts_rank` knows about edit distance.

The **semantic** arm returned German-language films. A misspelled proper noun
tokenizes into word-pieces the model never learned a meaning for, so the vector
lands somewhere arbitrary — and apparently that somewhere is German cinema.

Fixing this needs trigram similarity (`pg_trgm`) on the lexical side. It is not
something the reranker can learn away, because neither arm ever retrieves the
right document for it to promote.

---

## 9. `боксёр против мафии` ("boxer against the mafia") — **fails**

Tests the D-009 non-English case directly. *Shadowboxing* is a Russian film,
with a Russian-language overview, about a boxer entangled with organised crime.
It should be the answer.

| | rrf | lex | sem | title |
|---|---|---|---|---|
| 1 | 0.01639 | - | 1 | Moscow (2000) |
| 2 | 0.01613 | - | 2 | Satisfaktsiya (2011) |
| 3 | 0.01587 | - | 3 | Patrioticheskaya Komediya (1992) |
| 4 | 0.01562 | - | 4 | Nasha Russia: Yaytsa sudby (2010) |
| 5 | 0.01538 | - | 5 | Ехали в трамвае Ильф и Петров (1972) |

Zero lexical candidates — the `english` text search configuration has no
stemming rules for Russian.

*Shadowboxing* does appear, at **semantic rank 19**, below eighteen other
Russian films including several comedies. Every top hit has
`original_language = 'ru'`.

So the model is clustering by **language**, not by **content**. It has learned
that Cyrillic text is similar to other Cyrillic text far more strongly than it
has learned what any of it means. That is the expected behaviour of an
English-only model — the `-en` in `bge-small-en-v1.5` is doing real work — and
it is the practical consequence of the tokenizer finding described in D-009.

---

## 10. `the` — degenerate, handled acceptably

A stopword. Included to see whether the system fails loudly or quietly.

| | rrf | lex | sem | title |
|---|---|---|---|---|
| 1 | 0.01639 | - | 1 | The Great Passage (2013) |
| 2 | 0.01613 | - | 2 | Longtime Companion (1990) |
| 3 | 0.01587 | - | 3 | The Reader (1988) |
| 4 | 0.01562 | - | 4 | The Hours (2002) |
| 5 | 0.01538 | - | 5 | The Razor's Edge (1984) |

The lexical arm correctly returns nothing — `to_tsvector('english', ...)` strips
stopwords, so the query reduces to empty and matches no rows. That is right.

The semantic arm cannot decline. Every query becomes a vector, and every vector
has a nearest neighbour, so it confidently returns five films whose only
connection is a definite article. No error, no empty result, no signal that the
query was meaningless.

That asymmetry is worth remembering: the lexical arm can say "nothing matches";
the vector arm structurally cannot.

---

## Tally

| verdict | count | queries |
|---|---|---|
| works | 4 | space opera, toy comes to life, Bix, heist gone wrong |
| partial | 1 | film about grief |
| fails | 4 | Tom Hanks, lonely robot in space, Speilberg, Russian query |
| degenerate | 1 | the |

## Ceiling analysis — where the correct answers actually rank

The narration above says *why* each query failed. It does not say whether the
failure is recoverable, and that is the question that decides how much a
reranker can ever be worth.

Two kinds of failure, and they have completely different futures:

- **Ranking miss** — the correct film *is* in the candidate pool, ranked below
  the cut. A reranker can promote it. These are the Learner's job.
- **Retrieval miss** — the correct film never entered the pool. No reordering
  recovers it. These set the ceiling.

To tell them apart, each failing query was measured against a set of correct
documents, ranking the **whole 45,433-row corpus** per arm with a window
function rather than looking at the truncated top 50.

Two of the target sets are real ground truth, derived from columns the
retriever never sees as a query: `cast_names @> ARRAY['Tom Hanks']` gives 68
films, `directors @> ARRAY['Steven Spielberg']` gives 33. The other two are
target sets I nominated by hand and are labelled as judgment.

### Results

| query | targets | basis | ranking misses | verdict |
|---|---|---|---|---|
| `Tom Hanks` | 68 | ground truth | 47/68 in top 50 | **depth-fixable** |
| `Speilberg` | 33 | ground truth | 0/33 | **not fixable by depth** |
| `Spielberg` (control) | 33 | ground truth | 30/33 in top 50 | works |
| `lonely robot in space` | 6 | judgment | 2/6 | mixed |
| `film about grief` | 11 | judgment | 0/11 | **retrieval failure** |
| `боксёр против мафии` | 1 | objective | 1/1 (rank 19) | **ranking miss** |
| `Bix` (sanity check) | 1 | objective | rank 1 in both arms | control passed |

### Recall@k — the depth question, answered

| k | `Tom Hanks` lexical | `Spielberg` lexical |
|---|---|---|
| 50 | 0.69 | 0.91 |
| **100** | **1.00** | **1.00** |
| 200 | 1.00 | 1.00 |
| 500 | 1.00 | 1.00 |

Every one of the 68 Tom Hanks films sits at lexical rank ≤ 100. At the current
depth of 50, **21 of them are invisible to the reranker before it starts.**
Doubling depth to 100 makes the candidate pool complete for both ground-truth
queries. Nothing beyond 100 adds anything.

The semantic arm is useless for both: recall@1000 is **0.09** for Tom Hanks and
**0.09** for Spielberg. That is D-004 confirmed with a number — dense embeddings
do not retrieve by proper noun, which is exactly why cast and director names
were kept out of `search_text`.

### `Speilberg` — no depth fixes this

Recall is **0.00 at every k, in both arms.** All 33 films are lexically
unreachable, because `Speilberg` and `Spielberg` are simply different tokens
and `ts_rank` has no notion of edit distance. The correctly-spelled control
scores 0.91 at k=50, which isolates the cause precisely: the retriever finds
directors fine, and cannot survive a typo. This needs `pg_trgm`, not depth and
not a reranker.

### `film about grief` — the real ceiling

| film | semantic rank |
|---|---|
| Collateral Beauty | 70 |
| Ordinary People | 82 |
| The Sweet Hereafter | 378 |
| Manchester by the Sea | 560 |
| In the Bedroom | 7,487 |
| A Monster Calls | 18,057 |

Zero of eleven inside the top 50, and all eleven lexically unreachable. Depth
1000 would reach seven of them. *A Monster Calls* — a film explicitly about a
child processing his mother's death — sits at rank **18,057 of 45,433**.

The model is matching surface vocabulary, not theme. A plot summary about grief
rarely contains the word "grief", and nothing in `search_text` encodes what a
film is *about* at that level. No amount of depth or reranking fixes this; it is
a limit of what a 384-dimension sentence embedding of a plot summary can
represent.

### The tension that did not appear

Prediction before measuring: a deeper candidate pool would make RRF worse, since
more candidates means more chances for weak two-arm agreement to outrank strong
single-arm evidence — the `Tom Sawyer` failure mode.

**That did not happen.** Comparing fused top-10s at depth 50 against depth 500
across all ten queries: six were byte-identical, and the four that changed
shuffled the *same* titles rather than admitting new ones. *Tom Sawyer* stayed
at rank 3 in both. *Bachelor Party*, a real Hanks film, moved **up** from 5 to 4.

The reason is the shape of `1/(K + rank)`. At K=60 a rank-500 document
contributes `1/560 = 0.0018` against a rank-1 document's `1/61 = 0.0164` — about
11%. Deep candidates apply small nudges; they cannot stage upsets.

Which yields the important subtlety: **raising depth barely changes what the
user sees today. It changes what the reranker will be able to see.** Depth 500
does not pull *WALL·E* (semantic rank 115) into the visible top 10 either — a
single-arm rank-115 document scores below the cut. But it does put it in the
pool, where a trained reranker could promote it. Depth is an investment in the
ceiling, not a fix for the present.

### The degenerate query is not a bug

`the` was suspected of being structural. It is not.

`websearch_to_tsquery('english', 'the')` returns an **empty tsquery**,
`numnode = 0`, with Postgres explicitly raising `NOTICE: text-search query
contains only stop words or doesn't contain lexemes, ignored`. Returning zero
lexical results is correct and deliberate.

Hubness was the other candidate — the tendency of a few documents in
high-dimensional space to be nearest neighbours to almost anything. Tested with
six degenerate queries:

| pair | Jaccard overlap of top-10 |
|---|---|
| `a` vs `.` | 0.43 |
| `the` vs `a` | 0.18 |
| `the` vs `.` | 0.11 |
| `zzzz` vs `xyzzy` | 0.05 |

So there is **mild, bounded hubness among near-contentless queries** —
*The Great Passage* and *Brief Crossing* recur across `the`, `a` and `.`. That
is expected: short contentless strings embed near each other, so they retrieve
similar neighbourhoods. Nonsense-but-distinct strings (`zzzz`, `xyzzy`) overlap
almost not at all, which confirms these are not global attractors.

Across the ten real queries, exactly one document (*Bipedalism*) appeared in
more than one top 10. **There are no hub documents polluting real results.**

### What this means for the Learner, and for personas

| category | queries | can a reranker help? |
|---|---|---|
| ranking miss | Russian query, `Tom Hanks` (47 of 68), `lonely robot` (2 of 6) | **yes** |
| retrieval miss, depth-fixable | `Tom Hanks` (21 of 68), `lonely robot` (WALL·E at 115) | only after depth rises |
| retrieval miss, not depth-fixable | `film about grief` (all 11) | no |
| query understanding | `Speilberg` (all 33) | no — needs `pg_trgm` |

The reranker has real work available, so the project is not ceiling-bound. But
the ceiling is uneven, and it is uneven **by query type**: proper-noun queries
are healthy once depth reaches 100, and abstract-theme queries are close to
hopeless with this embedding.

That should shape the personas directly. Simulated users whose queries are
mostly proper nouns and concrete plot elements will exercise a retriever that
can actually serve them, and the reranker's improvement will be measurable.
Personas that search by theme and mood would mostly be measuring the embedding
model's ceiling instead of the Learner's contribution — which would make week 4
look like a failure of the reranker when it was a failure of retrieval.

**Also worth noting:** the semantic arm always returns exactly 50 candidates,
because every document has a vector and there is always a 50th nearest
neighbour. The lexical arm returned between 0 and 50. When the lexical arm
returns 0, fusion is not doing anything at all — it is just the semantic ranking
with extra arithmetic.
