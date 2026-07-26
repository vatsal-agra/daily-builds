"""A hand-written, original demo corpus: 50 short articles across five
topics, used by `glean demo` / `glean serve --demo` to give Glean something
real to search. All text below was written for this project."""

TECHNOLOGY = [
    ("The Rise of Compilers", "A compiler translates source code written by a programmer into machine code a computer can execute directly. The first widely used compiler was built for the FORTRAN language in the 1950s, and it proved that automatic translation could produce code nearly as fast as hand-written assembly."),
    ("What Is an Inverted Index", "An inverted index maps each term in a collection of documents to the list of documents containing that term. Search engines build inverted indexes so that a query for a rare word does not require scanning every document, only the short postings list for that word."),
    ("Binary Search Trees Explained", "A binary search tree keeps every value in the left subtree smaller than the node and every value in the right subtree larger. This ordering lets a balanced tree find, insert, or delete a value in logarithmic time, far faster than scanning a plain list."),
    ("The Basics of TCP/IP", "The TCP/IP protocol suite breaks network communication into layers: physical transmission, addressing and routing, reliable delivery, and application data. TCP guarantees that bytes arrive in order and without gaps, while the simpler UDP protocol trades that guarantee for lower latency."),
    ("Garbage Collection Strategies", "A garbage collector reclaims memory that a running program can no longer reach. Mark-and-sweep collectors trace live objects from a set of roots and free everything untouched, while generational collectors exploit the observation that most objects die young and scan young objects far more often."),
    ("Hash Tables and Collisions", "A hash table stores key-value pairs by computing a hash of the key and using it to pick a bucket. Two different keys can hash to the same bucket, a collision, which is usually resolved either by chaining a linked list per bucket or by probing to a nearby open slot."),
    ("A Short History of the Internet", "The Internet grew out of ARPANET, a research network funded by the United States Department of Defense in 1969 to connect a handful of university computers. The adoption of TCP/IP in 1983 let independent networks interconnect, and the World Wide Web arrived in 1991."),
    ("Version Control Concepts", "A version control system records the history of a project as a sequence of snapshots, letting a team see who changed what and revert unwanted changes. Distributed systems such as Git give every clone a full copy of the history, so most operations happen entirely offline."),
    ("Understanding Regular Expressions", "A regular expression describes a pattern of text using a small algebra of literals, concatenation, alternation, and repetition. Engines typically compile a regular expression into a finite automaton, either a nondeterministic automaton simulated with backtracking or a deterministic automaton with no backtracking at all."),
    ("How Caches Speed Up Software", "A cache stores the result of an expensive computation or a slow lookup so that a later request for the same thing can be answered instantly. The central design questions for any cache are what to store, when an entry becomes stale, and what to evict when the cache is full."),
]

SCIENCE = [
    ("The Water Cycle", "Water continuously moves between the ocean, the atmosphere, and the land. The sun evaporates surface water into vapor, which rises, cools, and condenses into clouds; the water eventually falls as rain or snow and flows back toward the ocean through rivers and groundwater."),
    ("How Photosynthesis Works", "Plants convert sunlight, water, and carbon dioxide into glucose and oxygen through photosynthesis. The reaction happens in chloroplasts, where chlorophyll absorbs light energy and drives a chain of chemical reactions that ultimately store energy in the bonds of a sugar molecule."),
    ("Newton's Laws of Motion", "Isaac Newton's three laws describe how objects move under the influence of force. An object at rest stays at rest unless a force acts on it, the acceleration of an object is proportional to the net force applied to it, and every action has an equal and opposite reaction."),
    ("What Causes Earthquakes", "Earthquakes occur when built-up stress along a fault in the Earth's crust suddenly releases, sending seismic waves outward from the point of rupture. Most earthquakes happen along the boundaries of tectonic plates, where plates grind past, collide with, or slide beneath one another."),
    ("The Structure of DNA", "DNA is a double helix made of two strands of nucleotides wound around each other. Each nucleotide carries one of four bases, and the bases on opposite strands pair up in a fixed pattern, which is what lets a cell copy its DNA accurately before it divides."),
    ("An Introduction to Black Holes", "A black hole forms when enough mass collapses into a small enough volume that not even light can escape its gravity. The boundary beyond which nothing returns is called the event horizon, and the first direct image of a black hole's shadow was published in 2019."),
    ("The Periodic Table", "The periodic table arranges the chemical elements by increasing atomic number so that elements with similar chemical properties line up in the same column. Dmitri Mendeleev published an early version in 1869 and famously left gaps for elements that had not yet been discovered."),
    ("How Vaccines Train Immunity", "A vaccine introduces a weakened, inactivated, or partial form of a pathogen so the immune system can learn to recognize it without causing the disease itself. If the real pathogen appears later, memory cells produced during vaccination respond far faster than they would on a first exposure."),
    ("The Greenhouse Effect", "Certain gases in the atmosphere, including carbon dioxide and methane, trap heat that would otherwise radiate back into space, warming the planet's surface. This greenhouse effect is a natural process that keeps Earth habitable, but the added gases from burning fossil fuels have intensified it."),
    ("Why the Sky Is Blue", "Sunlight looks white but contains every color of the visible spectrum. Air molecules scatter shorter wavelengths of light, such as blue, far more strongly than longer wavelengths, such as red, and that scattered blue light reaches our eyes from every direction across the sky."),
]

HISTORY = [
    ("The Fall of the Roman Empire", "The Western Roman Empire fractured over the fifth century under pressure from invading groups, economic strain, and political instability, with the deposition of the last emperor in 476 CE conventionally marking its end. The Eastern Roman Empire, later called Byzantine, endured for another thousand years."),
    ("The Printing Press and Its Impact", "Johannes Gutenberg introduced a printing press with movable metal type in the German city of Mainz around 1440. The press made books dramatically cheaper to produce, accelerated the spread of literacy, and helped fuel the Reformation and the wider scientific revolution."),
    ("The Silk Road Trade Routes", "The Silk Road was a network of trade routes connecting China to the Mediterranean world, carrying silk, spices, and other goods across Central Asia for over a thousand years. The routes also carried ideas, religions, and technologies between distant civilizations."),
    ("The French Revolution", "The French Revolution began in 1789 amid financial crisis, food shortages, and resentment of aristocratic privilege. It swept away the monarchy, introduced the Declaration of the Rights of Man, and eventually gave rise to Napoleon Bonaparte's rule over France and much of Europe."),
    ("The Moon Landing", "On July 20, 1969, astronauts Neil Armstrong and Buzz Aldrin became the first humans to walk on the Moon as part of NASA's Apollo 11 mission. Michael Collins remained in lunar orbit aboard the command module while the two others explored the surface."),
    ("The Construction of the Great Wall", "The Great Wall of China was built and rebuilt over many centuries by successive dynasties to defend against raids from northern nomadic groups. The best-preserved sections date from the Ming dynasty, which reinforced the wall with brick and stone starting in the fourteenth century."),
    ("The Industrial Revolution", "The Industrial Revolution began in Britain in the late eighteenth century as steam power, mechanized textile production, and new iron-making techniques transformed manufacturing. Factories drew workers from the countryside into rapidly growing cities, reshaping both the economy and daily life."),
    ("The Voyages of Zheng He", "Admiral Zheng He led seven major naval expeditions for the Ming dynasty between 1405 and 1433, commanding fleets that reached as far as East Africa. The voyages demonstrated Chinese naval power and opened diplomatic and trade contacts across the Indian Ocean."),
    ("The Berlin Wall", "The Berlin Wall was built in 1961 to separate East and West Berlin, becoming the most visible symbol of the Cold War division of Europe. It stood for twenty-eight years before being torn down in November 1989 amid a wave of political change across Eastern Europe."),
    ("The Founding of the United Nations", "The United Nations was founded in 1945 in the aftermath of the Second World War, when representatives of fifty countries signed its charter in San Francisco. Its stated goals were to prevent future wars, promote human rights, and foster international cooperation."),
]

COOKING = [
    ("The Science of Bread Baking", "Bread rises because yeast consumes sugars in the dough and releases carbon dioxide gas, which gets trapped in a stretchy network of gluten proteins formed as flour is kneaded with water. Baking then sets that structure permanently as the starches gelatinize and the crust browns."),
    ("How to Make a Roux", "A roux is made by cooking equal parts flour and fat together until the raw flour taste disappears, then used to thicken sauces, soups, and gravies. A roux cooked only briefly stays pale and thickens strongly, while a roux cooked longer turns brown and nutty but thickens less."),
    ("The Maillard Reaction", "The Maillard reaction is a chemical reaction between amino acids and reducing sugars that browns food and produces hundreds of new flavor compounds. It is responsible for the crust on seared steak, the color of toasted bread, and the aroma of roasted coffee."),
    ("Knife Skills for Home Cooks", "A sharp knife is safer than a dull one because it requires less pressure and is less likely to slip. Learning a few basic cuts, such as the dice, the julienne, and the chiffonade, makes prep work faster and gives finished dishes a more even cook."),
    ("Understanding Emulsions", "An emulsion suspends tiny droplets of one liquid, such as oil, within another liquid that would not normally mix with it, such as vinegar or egg yolk. Mayonnaise and vinaigrette are both classic emulsions, held stable by an emulsifier like lecithin that coats each droplet."),
    ("The History of Pasta", "Dried pasta has been documented in Italy since at least the twelfth century, though wheat noodles appear far earlier in Chinese cooking. Pasta became a staple of southern Italian cuisine once industrial drying and cheap durum wheat made it affordable to produce in large quantities."),
    ("Why Onions Make You Cry", "Cutting an onion ruptures its cells and releases an enzyme that reacts with sulfur compounds to form a volatile gas. The gas drifts up and irritates the eyes, triggering tears as a defensive reflex, an effect that chilling the onion beforehand can noticeably reduce."),
    ("The Art of Fermentation", "Fermentation uses bacteria, yeast, or mold to transform food, producing everything from sourdough bread and cheese to kimchi and soy sauce. Beyond flavor, fermentation often preserves food by producing acids or alcohol that make the environment hostile to spoilage organisms."),
    ("Choosing the Right Cooking Oil", "Different cooking oils have different smoke points, the temperature at which an oil starts to break down and burn. Oils with a high smoke point, such as refined peanut or avocado oil, suit high-heat searing, while delicate oils like extra virgin olive oil are best added after cooking."),
    ("The Basics of Stock", "A good stock is built by simmering bones, vegetables, and aromatics in water for hours, slowly extracting collagen, flavor, and gelatin. Chicken stock and beef stock differ mainly in cooking time, since larger, denser bones need longer simmering to release their gelatin."),
]

SPORTS = [
    ("The Origins of the Marathon", "The modern marathon commemorates the legendary run of a Greek messenger from the battle of Marathon to Athens. The distance was standardized at 26.2 miles for the 1908 London Olympics, extended slightly so the race could finish in front of the royal viewing box."),
    ("How the Offside Rule Works", "In association football, an attacking player is offside if they are nearer to the opponents' goal line than both the ball and the second-last opponent when the ball is played to them. The rule prevents attackers from simply waiting near the goal for a long pass."),
    ("The History of the Olympic Games", "The ancient Olympic Games were held every four years in Olympia, Greece, starting around 776 BCE, as part of a religious festival honoring Zeus. The modern Olympics were revived in 1896 in Athens and have since grown into the largest international sporting event in the world."),
    ("What Makes a Curveball Curve", "A curveball spins so that the air moving with the spin on one side of the ball travels faster than the air moving against it on the other side, creating a pressure difference that pushes the ball off a straight path, an effect known as the Magnus effect."),
    ("The Rules of Chess Notation", "Algebraic chess notation labels each square by its file, a letter from a to h, and its rank, a number from one to eight, so that any move can be written as the piece and its destination square. This compact notation lets an entire game be recorded in a few lines."),
    ("The Evolution of the Basketball Three-Pointer", "The three-point line was introduced in the American Basketball Association in 1967 and adopted by the NBA in the 1979-80 season to reward long-range shooting. Its growing use has steadily pushed professional basketball offenses to spread out and shoot from farther beyond the key."),
    ("Why Cyclists Draft Behind Each Other", "Drafting lets a cyclist ride close behind another rider to shelter from the wind, cutting the energy needed to maintain the same speed by a large margin. Teams use drafting tactically, rotating riders at the front so the group as a whole conserves energy."),
    ("The Physics of a Golf Swing", "A golf swing converts rotational body motion into club head speed through a kinetic chain, transferring energy from the hips through the torso, arms, and finally the club. Small changes in the angle of the clubface at impact make a large difference in the ball's resulting flight path."),
    ("The History of the World Cup", "The first FIFA World Cup was held in Uruguay in 1930, with thirteen national teams competing in the host country. The tournament has been held every four years since, except for a break during the Second World War, and now draws billions of television viewers."),
    ("How Tennis Scoring Got Its Numbers", "Tennis scores points as love, fifteen, thirty, and forty rather than zero, one, two, and three, a quirk usually traced to medieval French clock faces used to track games. A player must win by two clear points once a game reaches deuce at forty-forty."),
]

ALL_ARTICLES = []
for topic, articles in (
    ("technology", TECHNOLOGY),
    ("science", SCIENCE),
    ("history", HISTORY),
    ("cooking", COOKING),
    ("sports", SPORTS),
):
    for title, text in articles:
        ALL_ARTICLES.append({"topic": topic, "title": title, "text": text})


def load_corpus():
    """Return the full 50-article demo corpus as a list of dicts."""
    return list(ALL_ARTICLES)
