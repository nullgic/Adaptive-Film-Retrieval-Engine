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

## What this actually says

**Three distinct failure causes, not one.**

*Tom Hanks* and *film about grief* fail **inside the fusion** — both arms
retrieved reasonable things and RRF combined them badly, promoting weak
agreement over strong single-arm evidence. A reranker could learn to fix these,
because the right documents are already in the candidate pool.

*lonely robot in space* and the Russian query fail **in retrieval** — the right
document was never surfaced highly enough for any reranking to save it. No
amount of reordering fixes a candidate list that does not contain the answer.

*Speilberg* fails **before retrieval**, at query understanding. Neither arm has
any mechanism for edit distance.

That split matters for what comes next. The Learner can only address the first
group. The second needs better retrieval, the third needs `pg_trgm` or a spelling
correction step — and knowing which is which is only possible because the arms
were kept separately inspectable.

**Also worth noting:** the semantic arm always returns exactly 50 candidates,
because every document has a vector and there is always a 50th nearest
neighbour. The lexical arm returned between 0 and 50. When the lexical arm
returns 0, fusion is not doing anything at all — it is just the semantic ranking
with extra arithmetic.
