"""Builds data/corpus.txt: an original training corpus for Sprout.

Everything here is hand-written for this project (no scraped or downloaded
text), which sidesteps licensing questions and network dependence entirely.
To get enough volume for a (tiny) language model to find repeatable
structure in, ~30 hand-written template paragraphs across three "genres"
(fables, dialogues, field notes) are combinatorially filled in with an
original cast of characters/animals/places, using a fixed seed so the
corpus is exactly reproducible.
"""
import random

CHARACTERS = [
    "Nima", "Oskar", "Wren", "Talia", "Beck", "Sable", "Percy", "Ivy",
    "Doran", "Mabel", "Finch", "Corin", "Hazel", "Rook", "Linnet", "Absalom",
]
ANIMALS = [
    "fox", "otter", "heron", "badger", "hare", "crow", "mole", "lynx",
    "wren", "toad", "stoat", "owl", "vole", "newt",
]
PLACES = [
    "the hollow oak", "Widow's Creek", "the tall grass", "the north ridge",
    "the old mill", "Barrow Hill", "the reed bank", "the stone bridge",
    "the birch grove", "Fallow Field",
]
FOODS = ["barley bread", "dried plums", "goat cheese", "wild honey", "smoked fish", "turnip stew"]
WEATHER = ["a hard frost", "a warm rain", "a low fog", "a sharp wind", "an early snow", "a still heat"]
TOPICS = ["the harvest", "the price of wool", "the river's mood", "the coming winter", "the market road", "the new lambs"]

random.seed(20260717)


def cyc(seq, n):
    """n picks from seq, cycling with a shuffled order each lap (varied, deterministic)."""
    out = []
    while len(out) < n:
        lap = seq[:]
        random.shuffle(lap)
        out.extend(lap)
    return out[:n]


FABLE_TEMPLATES = [
    "{c1} kept a {an1} in a wicker cage beside {place}, and every morning fed it {food}. "
    "One day the {an1} spoke and said the cage was not needed, for it had nowhere else to be. "
    "{c1} opened the door and the {an1} stayed anyway, and that was the whole of the lesson.",

    "Near {place} a {an1} and a {an2} argued for a year about who was faster. "
    "{c1} settled it by racing them both to {place2} and back, and beat them there and back again. "
    "The {an1} and the {an2} agreed that speed was not the thing worth arguing about.",

    "{c1} found a {an1} caught in the brambles by {place} and freed it without a word. "
    "Seasons later, when {c1} fell through thin ice near {place2}, the same {an1} led three others to break the surface and pull {c1} clear. "
    "{c1} never again walked past a trapped thing without stopping.",

    "There was a {an1} who envied the {an2} for its wings, and a {an2} who envied the {an1} for its den. "
    "{c1} watched them trade complaints all through {weather}, and said nothing until the frost broke. "
    "By spring the {an1} had learned to climb and the {an2} had learned to burrow, and both were the better for it.",

    "{c1} and {c2} split a field down the middle after their father died, one taking {place} and the other {place2}. "
    "For years neither spoke, until a {an1} wandered onto both halves and neither would claim it as pest or guest. "
    "They mended the fence together instead, and left a gap wide enough for the {an1} to pass through.",

    "A {an1} boasted to {c1} that it needed no help to cross the river by {place}. "
    "Halfway across, the current took it, and a {an2} it had once mocked pulled it to the bank. "
    "{c1} wrote the story down so the boast would not be forgotten before the rescue was.",

    "{c1} planted a row of birches at {place} the year {c2} was born, meaning them to be cut for a roof beam. "
    "By the time {c2} was grown, a {an1} had denned beneath the roots, and the roof went unbuilt another decade. "
    "{c2} liked to say the {an1} owned the trees more than either of them did.",

    "Every {weather}, a {an1} crossed {place} to steal grain from {c1}'s store, and every time {c1} let it go. "
    "{c2} asked why the traps stayed empty on purpose. "
    "{c1} said a fed {an1} was a known thief, and a hungry one was an unknown risk, and the difference was worth the grain.",
]

DIALOGUE_TEMPLATES = [
    '"{topic} again," said {c1}, setting down the bucket. "It will keep us up past dark." '
    '"It always does," said {c2}. "Sit anyway. There is {food} enough for both of us."',

    '{c1} asked {c2} what {weather} meant for {topic}. '
    '"Nothing good," {c2} said, "but nothing we haven\'t seen before." '
    'They ate the {food} in silence after that, and it was enough of an answer.',

    '"I saw a {an1} by {place} this morning," {c1} said. '
    '"Watching the road, or watching the water?" asked {c2}. '
    '"Watching us," said {c1}, and neither of them laughed.',

    '{c2} wanted to know why {c1} still walked to {place2} every {weather} instead of taking the short road. '
    '"The short road doesn\'t pass {place}," {c1} said, "and I like to know what\'s moved through since I last looked."',

    '"You worry too much about {topic}," {c1} told {c2} over the {food}. '
    '"And you worry too little," {c2} answered, "which is why I do it for both of us."',
]

FIELD_NOTE_TEMPLATES = [
    "Day at {place}: {weather} again this morning. Tracks of a {an1} crossed the path near the gate, "
    "heading toward {place2}. No sign of the {an2} that denned here last winter.",

    "{c1} counted fourteen {an1} tracks along {place} before the light gave out. "
    "The ground was soft from {weather}, and every print held clean. Worth returning after the next thaw.",

    "Notes on {topic}, kept by {c1}: three seasons of watching {place} have shown the {an1} return "
    "within a week of the first {weather}, always from the direction of {place2}, never the other way.",

    "A {an1} and a {an2} shared the same stretch of bank at {place} for the third year running. "
    "{c1} still cannot explain why they do not compete for the same fish, only that they do not.",
]


def fill(template):
    c1, c2 = random.sample(CHARACTERS, 2)
    an1, an2 = random.sample(ANIMALS, 2)
    place, place2 = random.sample(PLACES, 2)
    return template.format(
        c1=c1,
        c2=c2,
        an1=an1,
        an2=an2,
        place=place,
        place2=place2,
        food=random.choice(FOODS),
        weather=random.choice(WEATHER),
        topic=random.choice(TOPICS),
    )


def build_corpus(target_chars=170_000):
    paragraphs = []
    all_templates = (
        [(t, "fable") for t in FABLE_TEMPLATES]
        + [(t, "dialogue") for t in DIALOGUE_TEMPLATES]
        + [(t, "field") for t in FIELD_NOTE_TEMPLATES]
    )
    total_chars = 0
    i = 0
    order = cyc(all_templates, 4000)
    while total_chars < target_chars and i < len(order):
        template, _kind = order[i]
        i += 1
        para = fill(template)
        paragraphs.append(para)
        total_chars += len(para) + 2
    return "\n\n".join(paragraphs) + "\n"


if __name__ == "__main__":
    import os

    text = build_corpus()
    out_path = os.path.join(os.path.dirname(__file__), "corpus.txt")
    with open(out_path, "w") as f:
        f.write(text)
    print(f"wrote {len(text):,} chars to {out_path}")
