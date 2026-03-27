# Agent: Event Categorizer

## Purpose
Assign a meaningful category to each scraped event using semantic understanding of the event title and description — not the source's raw tags, which are too coarse (e.g., everything at a library gets "library", even LEGO night and film screenings).

---

## When to Invoke
- After `python agent.py run` completes and `output/events_{city}.json` is fresh
- When category assignments look misaligned (wrong events in wrong buckets)
- When adding a new city with different event types

Trigger phrase: `"categorize events"` / `"recategorize events for [city]"` / `"run categorizer for [city]"`

---

## Category Definitions

Use exactly these 7 categories (filter buttons in the UI are keyed to them):

| Category | What belongs here |
|---|---|
| **Storytime** | Story time, lapsit, baby/toddler read-aloud, bookworm programs, Mother Goose |
| **Arts & Crafts** | Painting, collage, origami, sculpture, sewing, pottery, printmaking, sensory art, craft projects |
| **STEM** | Science experiments, coding, LEGO, robotics, math, engineering, Minecraft, 3D printing, technology clubs |
| **Music & Dance** | Singing, instruments, concerts, rhythm classes, dance, movement-to-music |
| **Play & Games** | Open play, drop-in play, board games, D&D, physical games, superhero day, gym/fitness, sport activities, yoga |
| **Film & Events** | Movie/film screenings, special event days, holiday celebrations, cultural festivals |
| **Community** | Social meetups, parent groups, health/wellness drop-ins, ESL, teen/adult clubs, community workshops not fitting above |

**General** = fallback only — use sparingly when none of the above fits at all.

---

## Process

### Step 1: Read the events JSON
Read `output/events_{city}.json`. Extract each event's: `title`, `description`, `org_name`, `tags`.

### Step 2: Categorize each event semantically

For each event, determine category from the **title first**, **description second**, and **org context third**. Ignore the `tags` field — it reflects source metadata, not event activity type.

**Decision logic (first match wins):**

1. **Storytime** — title or description contains: story time, storytime, lapsit, bookworm, baby time, mother goose, read aloud, pajama story, family story, infant story
2. **Arts & Crafts** — title contains: art, craft, collage, paint, origami, papier, watercolor, draw, mural, sticker, pottery, sewing, knit, crochet, printmaking, paper (as in paper craft), sculpt, jewelry, mask (craft context)
3. **STEM** — title contains: stem, code, coding, science, lego, robot, tech, engineer, math, minecraft, scratch, 3d print, experiment, lab, circuit
4. **Music & Dance** — title contains: music, song, sing, concert, drum, dance, choir, instrument, rhythm, jazz, orchestra, movement
5. **Play & Games** — title contains: play, game, games, sport, gym, active, fitness, yoga, superhero, super hero, d&d, dungeons, puzzle, obstacle, tumble
6. **Film & Events** — title contains: film, movie, screening, cinema, watch, anime, holiday, festival, celebration, fair, expo, convention
7. **Community** — title contains: club (non-game/STEM context), connect, social, health, wellness, esl, english conversation, coloring (adult), meeting, support group, tween, teen (non-STEM/art context)

When in doubt between two categories, pick the one that best represents the **primary activity** a parent would search for.

### Step 3: Update `filters/category_assigner.py`

Rewrite the `CATEGORY_RULES` to use **title keyword matching** instead of tag matching. Structure it as:

```python
TITLE_KEYWORD_RULES: list[tuple[str, list[str]]] = [
    ("Storytime",     ["story time", "storytime", "lapsit", "bookworm", "mother goose", ...]),
    ("Arts & Crafts", ["collage", "origami", "papier", "watercolor", "craft", ...]),
    ("STEM",          ["coding", "lego", "robot", "science", "stem", "experiment", ...]),
    ("Music & Dance", ["music", "singing", "concert", "dance", "rhythm", ...]),
    ("Play & Games",  ["game day", "open play", "super hero", "yoga", "fitness", ...]),
    ("Film & Events", ["film screening", "movie", "screening", "festival", ...]),
    ("Community",     ["esl", "coffee and connections", "adult coloring", "support group", ...]),
]
```

The `_resolve()` function should check `event.title.lower()` for these keywords, then fall back to `event.description.lower()`, then fall back to tag-based rules as a last resort.

### Step 4: Review for misclassifications (required every run)

**Do not skip this step.** Before writing results, audit the category assignments for false positives.

#### 4a. Flag description-triggered matches
Any event where the category was assigned via *description* (not title) is higher-risk. For each such event:
- Ask: does the **title alone** clearly belong to this category?
- If no, override to the category that best matches the title, or fall back to General.

#### 4b. Check for keyword false positives
Common patterns that cause wrong assignments — look for these explicitly:

| Pattern | Example | Wrong category | Correct |
|---|---|---|---|
| "Free [Day/Wednesday/Tuesday]" in title | "Illinois Free Wednesday" | Film & Events | General |
| Facility name in description only | "...in the YOUmedia Design Den" | STEM | Arts & Crafts or General |
| Generic admission/access events (no description, no primary activity) | Museum free day | STEM (via science tag) | General |
| "[Day of week] [audience]" titles with no activity keyword | "Tween Tuesday", "Family Saturday" | anything | General |
| "club" matching Community when it's clearly a STEM/Art club | "LEGO Club" | Community | STEM |

#### 4c. Verify General fallback is non-zero
If **zero** events fall into General, the keyword rules are too greedy — some events with no clear primary activity are being forced into a category. Identify the weakest keyword matches (lowest-confidence assignments) and move them to General.

#### 4d. Spot-check each category
For each category, look at the 3–5 events with the lowest-confidence match (triggered by a short or generic keyword like "craft", "science", "music") and verify they actually belong there. If they don't, either:
- Override the category for that event
- Remove or tighten the keyword in `TITLE_RULES` so it doesn't cause the same false positive on the next run

#### 4e. Update `category_assigner.py` with any fixes found
If step 4 reveals a bad keyword, remove or tighten it in `TITLE_RULES` or `TAG_FALLBACK_RULES` immediately — don't leave it for the next run. This keeps the rules accurate over time.

### Step 5: Update the JSON directly

After review and any overrides, write the corrected `category` field for every event back to `output/events_{city}.json`. Preserve all other fields exactly.

### Step 6: Sync category buttons in `public/index.html`

If you add or rename categories vs. the current button list, update the `<div class="filter-group">` for category in `public/index.html` to match. The current buttons are: All types, Storytime, Arts & Crafts, STEM, Music & Dance, Play & Games, Film & Events, Community, General.

If you change the category set, update both the HTML buttons AND the `filters.category` check in `applyFilters()`.

---

## Output

- Updated `filters/category_assigner.py` (title-keyword rules; any bad keywords tightened)
- Updated `output/events_{city}.json` (category field on every event)
- Updated `public/index.html` filter buttons if category names changed
- Print a summary: category distribution before and after, plus any overrides made in Step 4
