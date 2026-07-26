"""
Procedurally generates an ORIGINAL corpus of short fables for training Loom.

This text is synthetic, assembled from templates + word banks below — it is
not a transcription of any existing book. That is a deliberate choice: the
sandbox this was built in cannot reach arbitrary external hosts (Project
Gutenberg etc. are blocked), and reproducing a real public-domain text from
memory risks silent transcription errors. A generated corpus is honest about
what it is, license-clean, and its intentionally repetitive structure and
small vocabulary are exactly what let a tiny, CPU-only, few-minutes-of-
training model produce genuinely coherent output rather than gibberish.

Run: python3 make_corpus.py > fables.txt
"""
import random

ANIMALS = [
    "fox", "owl", "hare", "bear", "wolf", "crow", "mouse", "otter", "heron",
    "badger", "sparrow", "tortoise", "raven", "beetle", "goat", "deer",
    "squirrel", "fisher-cat", "weasel", "swan",
]

TRAITS = [
    "clever", "vain", "patient", "greedy", "kind", "lazy", "stubborn",
    "brave", "timid", "wise", "hasty", "gentle", "proud", "curious",
    "foolish", "loyal",
]

PLACES = [
    "the old mill", "the river bend", "a stony hill", "the deep wood",
    "a quiet meadow", "the frozen marsh", "the crooked bridge",
    "a dry well", "the tall pines", "the sunlit clearing", "the reed bed",
    "a narrow cave", "the orchard wall", "the salt flats", "the birch grove",
]

WANTS = [
    "a warm place to sleep", "the last apple on the tree",
    "a way across the river", "food before the winter came",
    "a name the others would remember", "peace with a noisy neighbor",
    "the shiniest stone in the stream", "a nest safe from the wind",
    "to be first to the top of the hill", "an answer to a hard riddle",
    "a friend who would not lie", "a way home before dark",
]

OBSTACLES = [
    "a storm was rolling in from the west",
    "the bridge had washed out in the spring flood",
    "a bigger animal already claimed the spot",
    "the path was blocked by fallen branches",
    "night came faster than expected",
    "the ice was thinner than it looked",
    "an old rival stood in the way",
    "the ground was still frozen from the frost",
    "the only way through was guarded by a hive of bees",
    "the well had gone dry",
]

HELPERS = [
    "a passing crow", "an old friend", "a stranger with a quiet voice",
    "a family of otters", "the miller's dog", "a young sparrow",
    "the tortoise who lived by the well", "a traveling badger",
    "the heron who watched the river", "an unexpected ally",
]

MORALS = [
    "Patience finds the door that haste walks past.",
    "A small kindness is never wasted.",
    "Pride climbs fastest and falls hardest.",
    "The clever and the wise are not always the same animal.",
    "What is shared in plenty is remembered in want.",
    "A borrowed plan still needs your own two feet.",
    "The quiet ones often see the most.",
    "Every hill has a longer way around it.",
    "Trust is built one small promise at a time.",
    "The hasty fox often supper's on nothing at all.",
    "It is better to ask the way than to walk it twice.",
    "Even the strongest current bends around a small stone.",
]

OPENERS = [
    "Long before the river changed its course, there lived a {trait} {animal} near {place}.",
    "In the season when the leaves first turned, a {trait} {animal} made its home by {place}.",
    "Not far from {place}, there was once a {animal}, well known for being {trait}.",
    "They still tell of a {trait} {animal} who kept to {place} in those days.",
]

MIDDLES = [
    "More than anything, the {animal} wanted {want}. So it set out one grey morning, "
    "certain the day would go its way.",
    "The {animal} had wanted {want} for as long as anyone could remember, and today "
    "seemed, at last, like the day to get it.",
    "It was said around {place} that the {animal} would do almost anything for {want}, "
    "and today it meant to prove that true.",
]

COMPLICATIONS = [
    "But {obstacle}, and the {animal}'s plan came apart before it had truly begun.",
    "Then, without warning, {obstacle}. The {animal} stopped short, unsure what to do next.",
    "Just as the {animal} was certain of success, {obstacle}, and everything changed.",
]

HELPS = [
    "It was {helper} who found the {animal} sitting there, and offered a better way.",
    "{helper} happened by just then, and did not need to be asked twice to help.",
    "Luck, or something like it, sent {helper} down that same path at that same hour.",
]

ENDINGS = [
    "Together they found a way through, though it was not the way the {animal} first pictured.",
    "In the end the {animal} got {want} after all — just not in the manner it expected.",
    "By evening the {animal} had {want}, and a new friend besides, which mattered more.",
    "The {animal} never forgot that day, nor the help it very nearly refused out of pride.",
]

MORAL_LEAD_INS = [
    "And that is why, to this day, the animals of {place} say:",
    "It is a story told still, near {place}, to end with this:",
    "The old ones who remember it tell the young ones simply this:",
]


def make_fable(rng):
    animal = rng.choice(ANIMALS)
    trait = rng.choice(TRAITS)
    place = rng.choice(PLACES)
    want = rng.choice(WANTS)
    obstacle = rng.choice(OBSTACLES)
    helper = rng.choice(HELPERS)
    moral = rng.choice(MORALS)

    parts = [
        rng.choice(OPENERS).format(trait=trait, animal=animal, place=place),
        rng.choice(MIDDLES).format(animal=animal, want=want, place=place),
        rng.choice(COMPLICATIONS).format(obstacle=obstacle, animal=animal),
        rng.choice(HELPS).format(helper=helper, animal=animal),
        rng.choice(ENDINGS).format(animal=animal, want=want),
        rng.choice(MORAL_LEAD_INS).format(place=place) + " \"" + moral + "\"",
    ]
    return animal, trait, " ".join(parts)


def make_corpus(n_fables, seed):
    rng = random.Random(seed)
    fables = []
    for i in range(n_fables):
        animal, trait, body = make_fable(rng)
        # the title names the SAME protagonist the body is about — a
        # previous version sampled the title's animal independently of the
        # body's, so titles routinely named the wrong animal (e.g. "The
        # Patient Sparrow" about a beetle). See REVIEW.md.
        title = f"The {trait.capitalize()} {animal.capitalize()}"
        fables.append(f"{title}\n\n{body}\n")
    return "\n\n".join(fables) + "\n"


if __name__ == "__main__":
    import sys

    n = int(sys.argv[1]) if len(sys.argv) > 1 else 600
    seed = int(sys.argv[2]) if len(sys.argv) > 2 else 1337
    sys.stdout.write(make_corpus(n, seed))
