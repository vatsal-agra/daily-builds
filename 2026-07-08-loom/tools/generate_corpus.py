"""Generates the original training corpus (data/corpus.txt) for Loom.

The corpus is entirely original: hand-written word banks and sentence
templates below are combined by a seeded random generator into ~100 short
fables about a fixed cast of forest animals, plus a smaller block of
hand-written (non-templated) prose. This gives a tiny model recurring
sentence structure, character names, and morals it can plausibly learn from
a small amount of data and CPU-scale training -- while sidestepping any
copyright/accuracy concerns of using a scraped or copied text.

Run: python3 tools/generate_corpus.py
"""
import os
import random

random.seed(1234)

CHARACTERS = [
    "Fox", "Owl", "Bear", "Rabbit", "Otter", "Deer", "Sparrow", "Badger",
    "Hedgehog", "Squirrel", "Heron", "Mole",
]
ADJECTIVES = [
    "clever", "stubborn", "gentle", "restless", "curious", "proud",
    "patient", "timid", "bold", "weary", "cheerful", "quiet",
]
SETTINGS = [
    "the Whispering Forest", "the Silver River", "Hollow Oak",
    "Misty Meadow", "Stonebridge", "the Old Pines", "Bramble Hollow",
    "the Sunken Glade", "Thistle Ridge", "Foxglove Hill",
]
PROBLEMS = [
    "the first snow came earlier than anyone expected",
    "the river rose higher than the oldest trees could remember",
    "a great wind knocked down the tallest pine",
    "the summer drought dried every stream but one",
    "a stranger's tracks appeared at the edge of the meadow",
    "the harvest of nuts and berries was smaller than any winter before",
    "the old bridge across the river finally gave way",
    "a fire had scorched half of Bramble Hollow",
    "no one could find the path home before nightfall",
    "the youngest of the litter had wandered too far from the den",
]
ACTIONS = [
    "gathered the others beneath the great oak to make a plan",
    "set out alone before the others had woken",
    "asked the old {character2} for advice, as was the custom",
    "refused to ask for help, and regretted it by dusk",
    "shared the last of its store without being asked",
    "argued with the {character2} until the sun went down",
    "remembered a trick its mother had taught it long ago",
    "worked through the night while the others slept",
    "traded a favor with the {character2} from Stonebridge",
    "chose the harder path because it was the honest one",
]
OUTCOMES = [
    "By morning, the trouble had passed, though nothing was quite the same.",
    "It took three days, but the forest was whole again by the new moon.",
    "The others were surprised to find the plan had worked after all.",
    "No one spoke of it again, but every animal remembered.",
    "The {character2} never forgot the debt, and repaid it come spring.",
    "It was hard work, and harder than expected, but it held.",
    "The young ones asked about it for many winters afterward.",
    "It was not the outcome anyone had hoped for, but it was enough.",
]
MORALS = [
    "a small kindness is never wasted, even on a stranger",
    "the patient paw gathers more than the hasty one",
    "no one crosses the river alone who does not have to",
    "pride is a heavy thing to carry uphill",
    "the forest remembers debts longer than seasons",
    "a plan shared is a plan that survives the night",
    "the quiet ones often see what the loud ones miss",
    "what is buried in autumn is not always lost by spring",
    "asking for help is not the same as needing rescue",
    "the old paths are old for a reason",
]
OPENERS = [
    "Long ago, in {setting}, there lived a {adjective} {character}.",
    "Near {setting}, before the river changed its course, a {adjective} {character} kept a small den.",
    "It is said that in {setting}, a {adjective} {character} once lived alone by choice.",
    "There was a time, not so long past, when a {adjective} {character} watched over {setting}.",
]
TRANSITIONS = [
    "One year, {problem}.",
    "Then, without warning, {problem}.",
    "It happened that {problem}, and every creature in {setting} took notice.",
    "As the season turned, {problem}.",
]
MORAL_TEMPLATES = [
    "And so the animals of {setting} learned that {moral}.",
    "From that day on, it was said in {setting} that {moral}.",
    "Even now, the young are told that {moral}.",
    "The elders still say that {moral}.",
]


def pick_two_distinct(seq):
    a = random.choice(seq)
    b = random.choice(seq)
    while b == a:
        b = random.choice(seq)
    return a, b


def make_fable():
    character, character2 = pick_two_distinct(CHARACTERS)
    adjective = random.choice(ADJECTIVES)
    setting = random.choice(SETTINGS)
    problem = random.choice(PROBLEMS)
    action = random.choice(ACTIONS).format(character2=character2.lower())
    outcome = random.choice(OUTCOMES).format(character2=character2)
    moral = random.choice(MORALS)

    opener = random.choice(OPENERS).format(
        setting=setting, adjective=adjective, character=character
    )
    transition = random.choice(TRANSITIONS).format(problem=problem, setting=setting)
    moral_line = random.choice(MORAL_TEMPLATES).format(setting=setting, moral=moral)

    body = (
        f"{opener} {transition} The {character} {action} {outcome} "
        f"{moral_line}"
    )
    return body


HAND_WRITTEN_BLOCK = """
A Note on These Tales

The stories collected here were not written down by any one hand at any one
time. They were told by the fire in Stonebridge and along the banks of the
Silver River, passed from the old to the young the way a smooth stone is
passed from paw to paw. Some say the Fox in these stories is always the
same fox; others say every generation has its own Fox, its own Owl, its own
Bear, and the names simply outlast the animals that wear them.

What is certain is this: the Whispering Forest is real, in the sense that
matters. Every creature in it must eventually cross a river, survive a
winter, lose an argument it was sure it would win, and decide whether to
ask for help before it is too late to matter. The forest does not care
whether you are clever or strong. It asks only whether you were paying
attention the last time trouble came this way, and whether you remembered
what it taught you.

The Owl of Hollow Oak kept the only calendar anyone trusted, scratched into
the bark a season at a time. She said the forest had only three real
seasons: the season of gathering, the season of enduring, and the season of
mending what the first two had broken. Everything else, she said, was just
weather.

The Bear of the Old Pines rarely spoke, but when she did, the younger
animals stopped whatever they were doing to listen. She once said that the
biggest mistake any creature makes is believing that the winter that is
coming will be like the winter that came before. No two winters, she said,
ever arrive by the same road.

The Rabbit family at Foxglove Hill was famous for counting everything: nuts,
footsteps, days since the last frost, favors owed and favors paid. It was
a rabbit of that family who first said that a debt remembered is worth more
than a debt repaid, because the remembering is what keeps the forest
honest.

It is in that spirit that these tales are offered: not as instructions, and
not quite as history, but as the kind of thing worth telling on a long
walk between Stonebridge and the Silver River, when the light is going and
the path home is still a fair way off.
""".strip()


def main():
    fables = [make_fable() for _ in range(220)]
    out_dir = os.path.join(os.path.dirname(__file__), "..", "data")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "corpus.txt")
    with open(out_path, "w") as f:
        f.write(HAND_WRITTEN_BLOCK)
        f.write("\n\n")
        for fable in fables:
            f.write(fable)
            f.write("\n\n")
    size = os.path.getsize(out_path)
    print(f"wrote {out_path} ({size} bytes, {len(fables)} fables)")


if __name__ == "__main__":
    main()
