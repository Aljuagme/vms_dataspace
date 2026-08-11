# Schema and Attribute Mapping Pipeline – Prototype Explanation

This document explains how the **schema and attribute mapping pipeline** works in the prototype, how mapping decisions are made, and why the observed results are correct and expected for the provided examples.

The goal of this pipeline is to **automatically propose mappings** from local platform attributes (e.g., `first_name`, `starts`, `requirements`) to a **canonical Schema.org-based model**, and to allow an administrator to validate and freeze these mappings into a reusable catalog.

---

## 1. When and why this pipeline runs

The schema mapping pipeline is executed **only once**, when an organization joins the federated network.

At this onboarding stage:
- Local data structures are analyzed
- Mapping proposals are generated automatically
- An administrator reviews and approves them
- A **mapping catalog** is stored

After this step:
- No similarity computation
- No embeddings
- No LLMs are needed anymore for schema mapping.

At runtime, the catalog is applied **deterministically**.

---

## 2. Overview of the scoring signals

For each local source field (e.g., `mail`) and each candidate canonical property (e.g., `schema:email`), the pipeline computes four values:

| Signal | Name | Purpose |
|------|-----|--------|
| `sem` | Semantic similarity | Measures meaning similarity using embeddings |
| `lex` | Lexical similarity | Measures string/name similarity |
| `boost` | Structural/type signal | Encodes domain knowledge and data shape |
| `comb` | Combined score | Final decision score |

Only the **combined score** is used to accept, reject, or mark a mapping as ambiguous.

---

## 3. Semantic similarity (`sem`)

### What it is
`sem` is the cosine similarity between:
- the **source field context** (field name + example value)
- the **canonical property signature** (name + description + expected type)

### How it is computed
- Uses **MiniLM-L6-v2** (`sentence-transformers/all-MiniLM-L6-v2`)
- This is a **BERT-like bi-encoder**, as used in ESCOX, SkillMo, and SkillGPT

### Typical values
| Range | Interpretation |
|-----|----------------|
| < 0.25 | Weak or unrelated |
| 0.30–0.45 | Related |
| 0.45–0.65 | Strong semantic match |
| > 0.65 | Very strong / near-equivalent |

Example:
first_name → schema:givenName
sem = 0.493


This already indicates a strong semantic correspondence.

---

## 4. Lexical similarity (`lex`)

### What it is
Character-level similarity between:
- local field name (e.g., `mail`)
- canonical property name or label (e.g., `schema:email`, `Email`)

Computed using `SequenceMatcher`.

### Why it matters
Embeddings alone do not capture naming conventions such as:
- `first_name`
- `mail`
- `starts`
- `place_city`

Lexical similarity handles these cheap but important cases.

### Typical values
| Range | Meaning |
|-----|--------|
| < 0.3 | Weak |
| 0.3–0.6 | Moderate |
| > 0.6 | Strong |

Example:
mail → schema:email
lex = 0.889


---

## 5. Boost signal (`boost`)

The boost encodes **non-ML knowledge** that real systems always use.

It comes from three sources:

### 5.1 Type detection
Based on example value format:
- Email regex → boost `schema:email`
- Date pattern (`YYYY-MM-DD`) → boost date properties
- List value → boost `TextList` properties (skills)

### 5.2 Alias dictionary
A small curated list of known aliases:
- `mail` → `email`
- `first_name` → `givenName`
- `requirements` → `requiredSkill`
- `place_city` → `location`

This simulates:
- schema documentation
- domain conventions
- accumulated onboarding knowledge

### 5.3 Structural hints
Examples:
- `skills = [ ... ]` → skill-related property
- city string → address/location property

### Typical boost values
| Boost | Meaning |
|-----|--------|
| 0.25 | Strong alias match |
| 0.35 | Strong type match |
| 0.40–0.60 | Multiple reinforcing signals |

Example:
mail → schema:email
boost = 0.60


---

## 6. Combined score (`comb`)

The final score is computed as:
comb = 0.70 * sem + 0.20 * lex + 0.10 * boost + boost


### Why this formula
- Semantic similarity dominates (state-of-the-art practice)
- Lexical similarity helps naming conventions
- Boost is intentionally strong to reflect trusted structural signals

This reflects a **retrieval + heuristics** pipeline, not pure ML.

---

## 7. Decision thresholds

### Acceptance threshold (`tau`)
tau = 0.35


Interpretation:
> If the best candidate scores below this, the mapping is rejected.

With MiniLM embeddings:
- Unrelated fields rarely exceed 0.30
- 0.35 ensures at least some meaningful evidence exists

---

### Margin threshold (`margin`)
margin = 0.08


Interpretation:
> If the top candidate is at least 0.08 better than the second one, accept automatically.

This prevents confusion between close alternatives such as:
- `givenName` vs `familyName`
- `description` vs `requiredSkill`

If the margin is smaller, the mapping is marked **AMBIGUOUS**.

---

## 8. Why all mappings were accepted in the example

All provided examples are **easy onboarding cases**:
- Clear field names
- Clear example values
- Strong semantic and structural signals

For example:
starts → schema:startDate
sem = 0.526
lex = 0.625
boost = 0.60
comb = 1.153


This is extremely high confidence and should always be accepted.

The pipeline is behaving exactly as designed.

---

## 9. Why LLM verification is not triggered here

LLM verification is **selective by design**.

It is only used when:
- `comb ≥ tau`, but
- the margin between top candidates is too small

In this example, all margins are large enough, so:
- No LLM calls are needed
- This is desirable and efficient

This follows the same principle as:
- OLaLa
- PDFS-based matching
- Entity Matching with LLMs

LLMs act as **verifiers**, not primary matchers.

---

## 10. Mapping city to the canonical listing structure

In the canonical schema (Chapter 6), locations are not plain strings.

Therefore, when a local field like:
city = "Palma"

is mapped to `schema:location`, a **transform rule** is applied:

### Transformation rule

### Resulting canonical structure
```json
"schema:location": {
  "@type": "schema:Place",
  "schema:address": {
    "@type": "schema:PostalAddress",
    "schema:addressLocality": "Palma"
  }
}

